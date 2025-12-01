# backend/ingest/rss_ingest.py
import os
import sys
import time
import feedparser
import requests
from requests.exceptions import RequestException
from datetime import datetime, timezone
from uuid import uuid4
from typing import Dict, List, Set, Optional, Tuple
from urllib.parse import urlparse

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from db import get_conn
from embeddings import embed_text
from utils.url_utils import canonicalize_url

# RSS Feed Configuration: { source_name: url }
RSS_FEEDS: Dict[str, str] = {
    "wired_ai": "https://www.wired.com/feed/tag/ai/latest/rss",
    "stoic_manual": "https://www.thestoicmanual.com/feed",
    "philosophize_this": "https://philosophizethis.substack.com/feed",
    "hardcore_software": "https://hardcoresoftware.learningbyshipping.com/feed",
    "nietzsche_wisdoms": "https://nietzschewisdoms.substack.com/feed",
    "hacker_news": "https://news.ycombinator.com/rss",
    "cabassa": "https://cabassa.substack.com/feed",
    "official_urban": "https://theofficialurban.substack.com/feed",
}

MAX_FETCH_RETRIES = int(os.getenv("MAX_FETCH_RETRIES", "3"))
FETCH_TIMEOUT = int(os.getenv("FETCH_TIMEOUT", "10"))


def fetch_feed(url: str, max_attempts: int = MAX_FETCH_RETRIES):
    """Fetch RSS feed with retry logic and exponential backoff."""
    last_error: Exception | None = None

    for attempt in range(max_attempts):
        try:
            resp = requests.get(url, timeout=FETCH_TIMEOUT)
            resp.raise_for_status()
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


def insert_event(entry, source: str, url: str) -> str:
    """Insert a single event into the database. URL should already be canonicalized and checked."""
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

    tags = list(categories)

    # Generate embedding
    print(f"[ingest] Embedding: {title[:60]!r}...")
    embed_vector = embed_text(clean_text or title or summary)
    embed_literal = "[" + ",".join(str(x) for x in embed_vector) + "]"

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

    placeholders = ", ".join(["%s"] * len(cols))
    colnames = ", ".join(cols)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO events ({colnames}) VALUES ({placeholders})",
                values,
            )

    print(f"[ingest] ✓ Inserted event {event_id}")
    return str(event_id)


def ingest_feed(source: str, url: str, skip_recent: bool = False) -> Tuple[int, int]:
    """
    Ingest a single RSS feed with optimized batch duplicate checking.

    Args:
        source: Source identifier (e.g., 'wired_ai')
        url: RSS feed URL
        skip_recent: If True, skip entries older than last fetch time

    Returns:
        Tuple of (inserted_count, skipped_count)
    """
    print(f"\n[ingest] Fetching {source}: {url}")

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

    # Insert only new entries
    inserted = 0
    skipped = 0

    for entry, canonical_url in entries_to_process:
        if canonical_url in existing_urls:
            skipped += 1
            continue

        try:
            insert_event(entry, source, canonical_url)
            inserted += 1
        except Exception as e:
            print(f"[ingest] ✗ Error inserting {canonical_url}: {e}")
            skipped += 1

    # Update feed metadata
    update_feed_metadata(source, total_entries, inserted)

    print(f"[ingest] {source}: Inserted {inserted}, Skipped {skipped}")
    return inserted, skipped


def main(feeds: Dict[str, str] | None = None, skip_recent: bool = True):
    """
    Ingest all configured RSS feeds.

    Args:
        feeds: Dictionary of {source: url}. Defaults to RSS_FEEDS.
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

    for source, url in feeds.items():
        inserted, skipped = ingest_feed(source, url, skip_recent=skip_recent)
        total_inserted += inserted
        total_skipped += skipped

    print(f"\n{'='*60}")
    print(f"[ingest] ✓ Complete!")
    print(f"[ingest] Inserted: {total_inserted} new events")
    print(f"[ingest] Skipped:  {total_skipped} duplicates/old")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    # When run directly, do full ingestion (skip_recent=False)
    main(skip_recent=False)
