# backend/ingest/nfl_news_api.py
"""
NFL News API ingestion module.

Fetches NFL news from RapidAPI NFL News endpoint and stores as events.
"""
import os
import sys
import time
import requests
from datetime import datetime, timezone
from uuid import uuid4
from typing import List, Tuple, Set, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from db import get_conn
from embeddings import embed_text
from ingest.status import update_ingest_status
from ingest.rss_ingest import DOMAIN_SPORTS

# API Configuration (loaded from config.py)
from config import (
    NFL_NEWS_API_URL,
    NFL_NEWS_API_KEY,
    NFL_NEWS_API_HOST,
    MAX_FETCH_RETRIES,
    FETCH_TIMEOUT,
)


def fetch_nfl_news(max_attempts: int = MAX_FETCH_RETRIES) -> dict:
    """
    Fetch NFL news from RapidAPI with retry logic and exponential backoff.

    Returns:
        dict: API response with articles list
    """
    headers = {
        'x-rapidapi-host': NFL_NEWS_API_HOST,
        'x-rapidapi-key': NFL_NEWS_API_KEY,
    }

    last_error: Exception | None = None

    for attempt in range(max_attempts):
        try:
            resp = requests.get(
                NFL_NEWS_API_URL,
                headers=headers,
                timeout=FETCH_TIMEOUT
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            last_error = e
            if attempt < max_attempts - 1:
                delay = 2 ** attempt
                print(f"[nfl_news_api] Error fetching NFL news ({e}); retrying in {delay}s...")
                time.sleep(delay)

    print(f"[nfl_news_api] Failed to fetch NFL news after {max_attempts} retries: {last_error}")
    raise last_error if last_error else RuntimeError("Unknown fetch error")


def get_existing_article_ids(article_ids: List[str]) -> Set[str]:
    """
    Batch check which article IDs already exist in the database.

    We store the RapidAPI article ID in the URL field as a unique identifier.
    """
    if not article_ids:
        return set()

    # Convert IDs to URL format for checking
    urls = [f"rapidapi://nfl-news/{article_id}" for article_id in article_ids]

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT url FROM events WHERE url = ANY(%s)",
                (urls,)
            )
            return {row["url"].replace("rapidapi://nfl-news/", "") for row in cur.fetchall()}


def get_last_fetched() -> Optional[datetime]:
    """Get the last fetch timestamp for NFL news API."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT last_fetched FROM feed_metadata WHERE source = %s",
                ("nfl_news_api",)
            )
            row = cur.fetchone()
            return row["last_fetched"] if row else None


def update_feed_metadata(article_count: int, inserted_count: int) -> None:
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
                ("nfl_news_api", datetime.now(timezone.utc), article_count, inserted_count)
            )


def prepare_article_event(article: dict) -> Tuple[uuid4, List, list, dict]:
    """
    Prepare article data for insertion.

    Args:
        article: Article dict from API response

    Returns:
        Tuple of (event_id, postgres_values, vector, metadata)
    """
    event_id = uuid4()

    # Parse timestamp
    published_str = article.get("published", article.get("lastModified", ""))
    if published_str:
        # Parse ISO 8601 timestamp: "2025-12-12T16:05:46Z"
        ts = datetime.fromisoformat(published_str.replace('Z', '+00:00'))
    else:
        ts = datetime.now(timezone.utc)

    # Extract fields
    title = article.get("headline", "").strip()
    summary = article.get("description", "").strip()
    article_id = str(article.get("id", ""))

    # Use RapidAPI article ID as unique URL identifier
    url = f"rapidapi://nfl-news/{article_id}"

    # Build text for embedding
    raw_text = f"{title}\n\n{summary}".strip()
    clean_text = raw_text

    # Categories: always sports domain + article type
    categories = [DOMAIN_SPORTS]
    article_type = article.get("type", "")
    if article_type:
        categories.append(article_type.lower())

    tags = list(categories)

    # Generate embedding
    print(f"[nfl_news_api] Embedding: {title[:60]!r}...")
    embed_vector = embed_text(clean_text or title or summary)
    embed_literal = "[" + ",".join(str(x) for x in embed_vector) + "]"

    values = [
        event_id,
        ts,
        "nfl_news_api",  # source
        url,
        title,
        summary,
        raw_text,
        clean_text,
        categories,
        tags,
        embed_literal,
    ]

    # Vector metadata for vector store
    vector_metadata = {
        "timestamp": ts,
        "source": "nfl_news_api",
        "categories": categories,
        "tags": tags,
    }

    return event_id, values, embed_vector, vector_metadata


def insert_articles_batch(articles_data: List[Tuple]) -> int:
    """
    Batch insert articles into the database and vector store.

    Args:
        articles_data: List of (event_id, values, vector, metadata) tuples

    Returns:
        Number of successfully inserted articles
    """
    if not articles_data:
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
            query = sql.SQL("INSERT INTO events ({}) VALUES ({})").format(
                sql.SQL(", ").join(sql.Identifier(col) for col in cols),
                sql.SQL(", ").join(sql.Placeholder() * len(cols)),
            )

            try:
                # Batch insert all at once
                cur.executemany(query, [values for _, values, _, _ in articles_data])
                inserted = len(articles_data)
                print(f"[nfl_news_api] ✓ Batch inserted {inserted} articles to PostgreSQL")
            except Exception as e:
                print(f"[nfl_news_api] ✗ Batch insert failed: {e}")
                # Fallback to individual inserts
                for event_id, values, _, _ in articles_data:
                    try:
                        cur.execute(query, values)
                        inserted += 1
                    except Exception as inner_e:
                        print(f"[nfl_news_api] ✗ Failed to insert {event_id}: {inner_e}")

    # Step 2: Insert vectors into vector store
    try:
        vector_store = get_vector_store()
        vectors = [
            (event_id, vector, metadata)
            for event_id, _, vector, metadata in articles_data
        ]
        vector_store.insert_batch(vectors)
    except Exception as e:
        print(f"[nfl_news_api] ⚠️  Vector store insertion failed: {e}")
        # Continue anyway - vectors can be backfilled later

    return inserted


def ingest_nfl_news(skip_recent: bool = False) -> Tuple[int, int]:
    """
    Ingest NFL news articles from RapidAPI.

    Args:
        skip_recent: If True, skip articles older than last fetch time

    Returns:
        Tuple of (inserted_count, skipped_count)
    """
    print(f"\n[nfl_news_api] Fetching NFL news from RapidAPI...")

    try:
        data = fetch_nfl_news()
    except Exception as e:
        print(f"[nfl_news_api] ✗ Failed to fetch NFL news: {e}")
        return 0, 0

    articles = data.get("articles", [])
    total_articles = len(articles)
    print(f"[nfl_news_api] Found {total_articles} articles")

    if not articles:
        print(f"[nfl_news_api] No articles to process")
        update_feed_metadata(0, 0)
        return 0, 0

    # Get last fetch time for filtering
    last_fetched = None
    if skip_recent:
        last_fetched = get_last_fetched()
        if last_fetched:
            print(f"[nfl_news_api] Last fetched: {last_fetched.strftime('%Y-%m-%d %H:%M:%S UTC')}")

    # Filter articles by timestamp if needed
    articles_to_process = []
    for article in articles:
        # Check timestamp if filtering by last fetch
        if last_fetched:
            published_str = article.get("published", article.get("lastModified", ""))
            if published_str:
                article_ts = datetime.fromisoformat(published_str.replace('Z', '+00:00'))
                if article_ts <= last_fetched:
                    continue

        articles_to_process.append(article)

    if not articles_to_process:
        print(f"[nfl_news_api] No new articles to process")
        update_feed_metadata(total_articles, 0)
        return 0, total_articles

    print(f"[nfl_news_api] Processing {len(articles_to_process)} articles (after timestamp filter)")

    # Batch check existing article IDs
    article_ids = [str(a.get("id", "")) for a in articles_to_process]
    existing_ids = get_existing_article_ids(article_ids)
    print(f"[nfl_news_api] Found {len(existing_ids)} existing articles in database")

    # Prepare new articles for batch insert
    articles_to_insert = []
    skipped = 0

    for article in articles_to_process:
        article_id = str(article.get("id", ""))
        if article_id in existing_ids:
            skipped += 1
            continue

        try:
            article_data = prepare_article_event(article)
            articles_to_insert.append(article_data)
        except Exception as e:
            print(f"[nfl_news_api] ✗ Error preparing article {article_id}: {e}")
            skipped += 1

    # Batch insert all new articles
    inserted = insert_articles_batch(articles_to_insert)

    # Update feed metadata
    update_feed_metadata(total_articles, inserted)

    print(f"[nfl_news_api] Inserted {inserted}, Skipped {skipped}")
    return inserted, skipped


def main(skip_recent: bool = True):
    """
    Main entry point for NFL news API ingestion.

    Args:
        skip_recent: If True, skip articles older than last fetch (much faster)
    """
    print(f"\n{'='*60}")
    print(f"[nfl_news_api] Starting NFL News API ingestion")
    print(f"[nfl_news_api] Skip recent: {skip_recent}")
    print(f"{'='*60}")

    inserted, skipped = ingest_nfl_news(skip_recent=skip_recent)

    print(f"\n{'='*60}")
    print(f"[nfl_news_api] ✓ Complete!")
    print(f"[nfl_news_api] Inserted: {inserted} new articles")
    print(f"[nfl_news_api] Skipped:  {skipped} duplicates/old")
    print(f"{'='*60}\n")

    # Update ingest status
    update_ingest_status("nfl_news_api", inserted)


if __name__ == "__main__":
    # When run directly, do full ingestion (skip_recent=False)
    main(skip_recent=False)
