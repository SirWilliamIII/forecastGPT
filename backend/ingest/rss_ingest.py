# backend/ingest/rss_ingest.py
import os
import sys
import time
import feedparser
import requests
import requests_cache
from requests.exceptions import RequestException
from datetime import datetime, timezone
from uuid import uuid4
from typing import Dict, List, Set, Optional, Tuple

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from db import get_conn
from embeddings import embed_text
from utils.url_utils import canonicalize_url
from ingest.status import update_ingest_status

# Domain categories for feeds
DOMAIN_CRYPTO = "crypto"
DOMAIN_SPORTS = "sports"
DOMAIN_TECH = "tech"
DOMAIN_GENERAL = "general"

# RSS Feed Configuration with domain categorization
# Format: { source_name: { "url": ..., "domain": ... } }
# Only market-relevant feeds - crypto, tech/AI, and sports betting markets
RSS_FEEDS: Dict[str, Dict[str, str]] = {
    # Crypto feeds - Direct market impact
    "coindesk": {
        "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "domain": DOMAIN_CRYPTO,
    },
    "coindoo": {
        "url": "https://coindoo.com/feed/",
        "domain": DOMAIN_CRYPTO,
    },
    "cointelegraph": {
        "url": "https://cointelegraph.com/rss",
        "domain": DOMAIN_CRYPTO,
    },
    "decrypt": {
        "url": "https://decrypt.co/feed",
        "domain": DOMAIN_CRYPTO,
    },
    "coinjournal": {
        "url": "https://coinjournal.net/feed/",
        "domain": DOMAIN_CRYPTO,
    },
    "blockworks": {
        "url": "https://blockworks.co/feed",
        "domain": DOMAIN_CRYPTO,
    },
    "bitcoin_magazine": {
        "url": "https://bitcoinmagazine.com/feed",
        "domain": DOMAIN_CRYPTO,
    },

    # Tech/AI feeds - Market-moving tech (IPOs, product launches, AI breakthroughs)
    "techcrunch": {
        "url": "https://techcrunch.com/feed/",
        "domain": DOMAIN_TECH,
    },
    "new_york_times_tech": {
        "url": "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
        "domain": DOMAIN_TECH,
    },
    "mit_tech_review": {
        "url": "https://www.technologyreview.com/feed/",
        "domain": DOMAIN_TECH,
    },
    "ars_technica": {
        "url": "https://feeds.arstechnica.com/arstechnica/index",
        "domain": DOMAIN_TECH,
    },
    "wired": {
        "url": "https://www.wired.com/feed",
        "domain": DOMAIN_TECH,
    },

    # Sports feeds - Sports betting markets
    "sports_insight": {
        "url": "https://www.sportsinsights.com/feed/",
        "domain": DOMAIN_SPORTS,
    },
    "roto_wire": {
        "url": "https://www.rotowire.com/rss/news.php?sport=NFL",
        "domain": DOMAIN_SPORTS,
    },
    "the_athletic": {
        "url": "https://theathletic.com/feeds/rss/news/",
        "domain": DOMAIN_SPORTS,
    },
    "new_york_times_sports": {
        "url": "http://feeds1.nytimes.com/nyt/rss/Sports",
        "domain": DOMAIN_SPORTS,
    },
    "yahoo_sports": {
        "url": "https://sports.yahoo.com/rss/",
        "domain": DOMAIN_SPORTS,
    },
    "talk_sport": {
        "url": "https://talksport.com/sports-news/all/feed/",
        "domain": DOMAIN_SPORTS,
    },
}

# Disabled/Removed feeds (403 Forbidden / 404 Not Found / blocks bots):
# - bitcoin_magazine: 403 Forbidden
# - espn (https://www.espn.com/espn/rss/nfl/news): 403 Forbidden - REMOVED
# - nfl_news: Doesn't parse correctly
# - bleacher_report: 404 Not Found
#
# To add more feeds, verify they work first:
#   curl -I <feed_url>
# Should return 200 OK, not 403/404

MAX_FETCH_RETRIES = int(os.getenv("MAX_FETCH_RETRIES", "3"))
FETCH_TIMEOUT = int(os.getenv("FETCH_TIMEOUT", "10"))

# HTTP caching for RSS feeds (1-hour expiry, reduces redundant fetches)
_cached_session = None


def get_cached_session():
    """Get or create cached session for RSS fetching."""
    global _cached_session
    if _cached_session is None:
        # Create cache in backend directory
        cache_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".cache")
        os.makedirs(cache_dir, exist_ok=True)
        cache_file = os.path.join(cache_dir, "rss_cache")

        _cached_session = requests_cache.CachedSession(
            cache_file,
            backend="sqlite",
            expire_after=3600,  # 1 hour
            allowable_codes=(200,),
            stale_if_error=True,  # Use stale cache if fetch fails
        )
    return _cached_session


def get_feeds_by_domain(domain: Optional[str] = None) -> Dict[str, str]:
    """Get feeds filtered by domain. Returns {source: url} dict."""
    result = {}
    for source, config in RSS_FEEDS.items():
        if domain is None or config["domain"] == domain:
            result[source] = config["url"]
    return result


def get_source_domain(source: str) -> str:
    """Get the domain for a source name."""
    if source in RSS_FEEDS:
        return RSS_FEEDS[source]["domain"]
    return DOMAIN_GENERAL


def fetch_feed(url: str, max_attempts: int = MAX_FETCH_RETRIES):
    """Fetch RSS feed with HTTP caching, retry logic and exponential backoff."""
    last_error: Exception | None = None
    session = get_cached_session()

    for attempt in range(max_attempts):
        try:
            resp = session.get(url, timeout=FETCH_TIMEOUT)
            resp.raise_for_status()

            # Check if from cache
            if hasattr(resp, 'from_cache') and resp.from_cache:
                print(f"[ingest] ✓ Using cached feed (saved network call)")

            return feedparser.parse(resp.text)
        except RequestException as e:
            last_error = e
            if attempt < max_attempts - 1:
                delay = 2 ** attempt
                print(f"[ingest] Error fetching feed ({e}); retrying in {delay}s...")
                time.sleep(delay)

    print(f"[ingest] Failed to fetch feed after {max_attempts} retries: {last_error}")
    raise last_error if last_error else RuntimeError("Unknown fetch error")


def get_existing_urls(urls: List[str]) -> Set[str]:
    """Batch check which URLs already exist in the database."""
    if not urls:
        return set()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT url FROM events WHERE url = ANY(%s)",
                (urls,)
            )
            return {row["url"] for row in cur.fetchall()}


def get_feed_last_fetched(source: str) -> Optional[datetime]:
    """Get the last fetch timestamp for a feed source."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT last_fetched FROM feed_metadata WHERE source = %s",
                (source,)
            )
            row = cur.fetchone()
            return row["last_fetched"] if row else None


def update_feed_metadata(source: str, entry_count: int, inserted_count: int) -> None:
    """Update feed metadata after ingestion."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO feed_metadata (source, last_fetched, last_entry_count, last_inserted_count, updated_at)
                VALUES (%s, %s, %s, %s, now())
                ON CONFLICT (source)
                DO UPDATE SET
                    last_fetched = EXCLUDED.last_fetched,
                    last_entry_count = EXCLUDED.last_entry_count,
                    last_inserted_count = EXCLUDED.last_inserted_count,
                    updated_at = now()
                """,
                (source, datetime.now(timezone.utc), entry_count, inserted_count)
            )


def prepare_event_data(entry, source: str, url: str, domain: str) -> Tuple[uuid4, List]:
    """
    Prepare event data for insertion without actually inserting.
    Returns (event_id, values_list) for batch insertion.
    """
    event_id = uuid4()

    if hasattr(entry, "published_parsed") and entry.published_parsed:
        ts = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
    else:
        ts = datetime.now(timezone.utc)

    title = getattr(entry, "title", "") or ""
    summary = getattr(entry, "summary", "") or ""

    raw_text = f"{title}\n\n{summary}".strip()
    clean_text = raw_text

    if hasattr(entry, "tags"):
        categories = [tag.term for tag in entry.tags if hasattr(tag, "term")]
    else:
        categories = []

    # Add domain as a category for filtering
    if domain and domain not in categories:
        categories.append(domain)

    tags = list(categories)

    # Generate embedding
    print(f"[ingest] Embedding: {title[:60]!r}...")
    embed_vector = embed_text(clean_text or title or summary)
    embed_literal = "[" + ",".join(str(x) for x in embed_vector) + "]"

    values = [
        event_id,
        ts,
        source,
        url,
        title,
        summary,
        raw_text,
        clean_text,
        categories,
        tags,
        embed_literal,
    ]

    # Return event_id, postgres values, vector, and metadata for vector store
    vector_metadata = {
        "timestamp": ts,
        "source": source,
        "categories": categories,
        "tags": tags,
    }

    return event_id, values, embed_vector, vector_metadata


def insert_events_batch(events_data: List[Tuple]) -> int:
    """
    Batch insert events into the database and vector store.

    Args:
        events_data: List of (event_id, values, vector, metadata) tuples from prepare_event_data

    Returns:
        Number of successfully inserted events
    """
    if not events_data:
        return 0

    cols = [
        "id",
        "timestamp",
        "source",
        "url",
        "title",
        "summary",
        "raw_text",
        "clean_text",
        "categories",
        "tags",
        "embed",
    ]

    from psycopg import sql
    from vector_store import get_vector_store

    # Step 1: Insert metadata into PostgreSQL
    inserted = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Use executemany for batch insert
            query = sql.SQL("INSERT INTO events ({}) VALUES ({})").format(
                sql.SQL(", ").join(sql.Identifier(col) for col in cols),
                sql.SQL(", ").join(sql.Placeholder() * len(cols)),
            )

            try:
                # Insert all at once
                cur.executemany(query, [values for _, values, _, _ in events_data])
                inserted = len(events_data)
                print(f"[ingest] ✓ Batch inserted {inserted} events to PostgreSQL")
            except Exception as e:
                print(f"[ingest] ✗ Batch insert failed: {e}")
                # Fallback to individual inserts
                for event_id, values, _, _ in events_data:
                    try:
                        cur.execute(query, values)
                        inserted += 1
                    except Exception as inner_e:
                        print(f"[ingest] ✗ Failed to insert {event_id}: {inner_e}")

    # Step 2: Insert vectors into vector store (Weaviate or PostgreSQL)
    try:
        vector_store = get_vector_store()
        vectors = [
            (event_id, vector, metadata)
            for event_id, _, vector, metadata in events_data
        ]
        vector_store.insert_batch(vectors)
    except Exception as e:
        print(f"[ingest] ⚠️  Vector store insertion failed: {e}")
        # Continue anyway - vectors can be backfilled later

    return inserted


def insert_event(entry, source: str, url: str, domain: str) -> str:
    """Insert a single event into the database. URL should already be canonicalized and checked."""
    event_id, values = prepare_event_data(entry, source, url, domain)

    cols = [
        "id",
        "timestamp",
        "source",
        "url",
        "title",
        "summary",
        "raw_text",
        "clean_text",
        "categories",
        "tags",
        "embed",
    ]

    with get_conn() as conn:
        with conn.cursor() as cur:
            from psycopg import sql
            cur.execute(
                sql.SQL("INSERT INTO events ({}) VALUES ({})").format(
                    sql.SQL(", ").join(sql.Identifier(col) for col in cols),
                    sql.SQL(", ").join(sql.Placeholder() * len(cols)),
                ),
                values,
            )

    print(f"[ingest] ✓ Inserted event {event_id} [{domain}]")
    return str(event_id)


def ingest_feed(source: str, url: str, domain: str, skip_recent: bool = False) -> Tuple[int, int]:
    """
    Ingest a single RSS feed with optimized batch duplicate checking.

    Args:
        source: Source identifier (e.g., 'coindesk')
        url: RSS feed URL
        domain: Domain category (crypto, sports, tech, general)
        skip_recent: If True, skip entries older than last fetch time

    Returns:
        Tuple of (inserted_count, skipped_count)
    """
    print(f"\n[ingest] Fetching {source} [{domain}]: {url}")

    try:
        feed = fetch_feed(url)
    except Exception as e:
        print(f"[ingest] ✗ Failed to fetch {source}: {e}")
        return 0, 0

    total_entries = len(feed.entries)
    print(f"[ingest] Found {total_entries} entries in {source}")

    # Get last fetch time for this source
    last_fetched = None
    if skip_recent:
        last_fetched = get_feed_last_fetched(source)
        if last_fetched:
            print(f"[ingest] Last fetched: {last_fetched.strftime('%Y-%m-%d %H:%M:%S UTC')}")

    # Filter entries and canonicalize URLs
    entries_to_process = []
    for entry in feed.entries:
        entry_url = getattr(entry, "link", None)
        if not entry_url:
            continue

        # Check timestamp if filtering by last fetch
        if last_fetched and hasattr(entry, "published_parsed") and entry.published_parsed:
            entry_ts = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            if entry_ts <= last_fetched:
                continue

        canonical_url = canonicalize_url(entry_url)
        entries_to_process.append((entry, canonical_url))

    if not entries_to_process:
        print(f"[ingest] No new entries to process")
        update_feed_metadata(source, total_entries, 0)
        return 0, total_entries

    print(f"[ingest] Processing {len(entries_to_process)} entries (after timestamp filter)")

    # Batch check existing URLs
    urls_to_check = [url for _, url in entries_to_process]
    existing_urls = get_existing_urls(urls_to_check)
    print(f"[ingest] Found {len(existing_urls)} existing URLs in database")

    # Prepare new entries for batch insert
    events_to_insert = []
    skipped = 0

    for entry, canonical_url in entries_to_process:
        if canonical_url in existing_urls:
            skipped += 1
            continue

        try:
            event_data = prepare_event_data(entry, source, canonical_url, domain)
            events_to_insert.append(event_data)
        except Exception as e:
            print(f"[ingest] ✗ Error preparing {canonical_url}: {e}")
            skipped += 1

    # Batch insert all new events
    inserted = insert_events_batch(events_to_insert)

    # Update feed metadata
    update_feed_metadata(source, total_entries, inserted)

    print(f"[ingest] {source}: Inserted {inserted}, Skipped {skipped}")
    return inserted, skipped


def main(feeds: Dict[str, Dict[str, str]] | None = None, skip_recent: bool = True):
    """
    Ingest all configured RSS feeds.

    Args:
        feeds: Dictionary of {source: {url, domain}}. Defaults to RSS_FEEDS.
        skip_recent: If True, skip entries older than last fetch (much faster on subsequent runs)
    """
    if feeds is None:
        feeds = RSS_FEEDS

    print(f"\n{'='*60}")
    print(f"[ingest] Starting ingestion of {len(feeds)} feeds")
    print(f"[ingest] Skip recent: {skip_recent}")
    print(f"{'='*60}")

    total_inserted = 0
    total_skipped = 0

    for source, config in feeds.items():
        url = config["url"] if isinstance(config, dict) else config
        domain = config.get("domain", DOMAIN_GENERAL) if isinstance(config, dict) else DOMAIN_GENERAL
        inserted, skipped = ingest_feed(source, url, domain, skip_recent=skip_recent)
        total_inserted += inserted
        total_skipped += skipped

    print(f"\n{'='*60}")
    print(f"[ingest] ✓ Complete!")
    print(f"[ingest] Inserted: {total_inserted} new events")
    print(f"[ingest] Skipped:  {total_skipped} duplicates/old")
    print(f"{'='*60}\n")

    # Update ingest status
    update_ingest_status("rss_ingest", total_inserted)


if __name__ == "__main__":
    # When run directly, do full ingestion (skip_recent=False)
    main(skip_recent=False)
