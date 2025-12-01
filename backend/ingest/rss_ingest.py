# backend/ingest/rss_ingest.py
import os
import sys
import time
import feedparser
import requests
from requests.exceptions import RequestException
from datetime import datetime, timezone
from uuid import uuid4
from typing import Dict, List
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


def event_exists(url: str) -> bool:
    if not url:
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM events WHERE url = %s LIMIT 1", (url,))
            return cur.fetchone() is not None


def insert_event(entry, source: str) -> str:
    event_id = uuid4()

    if hasattr(entry, "published_parsed") and entry.published_parsed:
        ts = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
    else:
        ts = datetime.now(timezone.utc)

    raw_url = getattr(entry, "link", None)
    url = canonicalize_url(raw_url)
    title = getattr(entry, "title", "") or ""
    summary = getattr(entry, "summary", "") or ""

    raw_text = f"{title}\n\n{summary}".strip()
    clean_text = raw_text

    if hasattr(entry, "tags"):
        categories = [tag.term for tag in entry.tags if hasattr(tag, "term")]
    else:
        categories = []

    tags = list(categories)

    print(f"[ingest] Embedding entry: {title[:80]!r}")
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
            try:
                cur.execute(
                    f"INSERT INTO events ({colnames}) VALUES ({placeholders})",
                    values,
                )
            except Exception as e:
                print(f"[ingest] Skipping URL (probably duplicate): {url} ({e})")
                return str(event_id)

    print(f"[ingest] Inserted event {event_id} for URL: {url}")
    return str(event_id)


def ingest_feed(source: str, url: str) -> tuple[int, int]:
    """Ingest a single RSS feed. Returns (inserted, skipped) counts."""
    print(f"\n[ingest] Fetching {source}: {url}")
    
    try:
        feed = fetch_feed(url)
    except Exception as e:
        print(f"[ingest] Failed to fetch {source}: {e}")
        return 0, 0

    print(f"[ingest] Found {len(feed.entries)} entries in {source}")

    inserted = 0
    skipped = 0

    for entry in feed.entries:
        entry_url = getattr(entry, "link", None)
        if not entry_url:
            print("[ingest] Skipping entry with no URL")
            skipped += 1
            continue

        try:
            insert_event(entry, source)
            inserted += 1
        except Exception as e:
            print(f"[ingest] Error inserting entry for {entry_url}: {e}")
            skipped += 1

    return inserted, skipped


def main(feeds: Dict[str, str] | None = None):
    """Ingest all configured RSS feeds."""
    if feeds is None:
        feeds = RSS_FEEDS

    print(f"[ingest] Starting ingestion of {len(feeds)} feeds...")
    
    total_inserted = 0
    total_skipped = 0

    for source, url in feeds.items():
        inserted, skipped = ingest_feed(source, url)
        total_inserted += inserted
        total_skipped += skipped

    print(f"\n[ingest] Complete! Total inserted={total_inserted}, skipped={total_skipped}")


if __name__ == "__main__":
    main()
