import os
import sys
import feedparser
import requests
from datetime import datetime, timezone
from uuid import uuid4

# Add the parent directory (backend/) to sys.path so we can import db, embeddings
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from db import get_conn
from embeddings import embed_text
from utils.url_utils import canonicalize_url

# You can swap this for any finance/crypto/news RSS URL
RSS_URL = "https://www.wired.com/feed/tag/ai/latest/rss"


def fetch_feed(url: str):
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return feedparser.parse(resp.text)


def event_exists(url: str) -> bool:
    if not url:
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM events WHERE url = %s LIMIT 1", (url,))
            return cur.fetchone() is not None


def insert_event(entry) -> str:
    event_id = uuid4()

    # Timestamp: RSS published or "now"
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        ts = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
    else:
        ts = datetime.now(timezone.utc)

    source = "wired_ai"

    raw_url = getattr(entry, "link", None)
    url = canonicalize_url(raw_url)
    title = getattr(entry, "title", "") or ""
    summary = getattr(entry, "summary", "") or ""

    # Raw + clean text
    raw_text = f"{title}\n\n{summary}".strip()
    clean_text = raw_text  # later: you can normalize more aggressively here

    # RSS tags → categories/tags lists
    if hasattr(entry, "tags"):
        categories = [tag.term for tag in entry.tags if hasattr(tag, "term")]
    else:
        categories = []

    tags = list(categories)  # you can specialize later (e.g. only tickers)

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
        categories,  # always a list, never None
        tags,        # always a list
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
                # Most likely a unique violation on URL; log and skip
                print(f"[ingest] Skipping URL (probably duplicate): {url} ({e})")
                return str(event_id)

    print(f"[ingest] Inserted event {event_id} for URL: {url}")
    return str(event_id)


def main():
    print(f"[ingest] Fetching feed: {RSS_URL}")
    feed = fetch_feed(RSS_URL)
    print(f"[ingest] Found {len(feed.entries)} entries")

    inserted = 0
    skipped = 0

    for entry in feed.entries:
        url = getattr(entry, "link", None)
        if not url:
            print("[ingest] Skipping entry with no URL")
            skipped += 1
            continue

        try:
            insert_event(entry)
            inserted += 1
        except Exception as e:
            print(f"[iggest] Error inserting entry for {url}: {e}")
            skipped += 1

    print(f"[ingest] Done. Inserted={inserted}, skipped={skipped}")


if __name__ == "__main__":
    main()
