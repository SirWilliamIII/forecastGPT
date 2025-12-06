#!/usr/bin/env python3
"""
Migrate existing event vectors from PostgreSQL to Weaviate.

This script:
1. Reads all events with embeddings from PostgreSQL
2. Uploads them in batches to Weaviate
3. Verifies the migration

Usage:
    python migrate_to_weaviate.py [--batch-size 100] [--dry-run]

Environment variables required:
    WEAVIATE_URL - Weaviate cluster URL
    WEAVIATE_API_KEY - Weaviate API key
    DATABASE_URL - PostgreSQL connection string (or default)
"""

import argparse
import os
import sys
from datetime import datetime

from db import get_conn
from vector_store import get_vector_store, WeaviateVectorStore


def count_postgres_vectors() -> int:
    """Count events with embeddings in PostgreSQL."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM events WHERE embed IS NOT NULL")
            row = cur.fetchone()
            return int(row["count"]) if row else 0


def migrate_vectors(batch_size: int = 100, dry_run: bool = False) -> int:
    """
    Migrate vectors from PostgreSQL to Weaviate.

    Args:
        batch_size: Number of vectors to process per batch
        dry_run: If True, only count vectors without migrating

    Returns:
        Number of vectors migrated
    """
    print("=" * 70)
    print("PostgreSQL → Weaviate Migration")
    print("=" * 70)
    print()

    # Check that Weaviate is configured
    if not os.getenv("WEAVIATE_URL") or not os.getenv("WEAVIATE_API_KEY"):
        print("❌ Error: WEAVIATE_URL and WEAVIATE_API_KEY must be set")
        print()
        print("Set these environment variables:")
        print("  export WEAVIATE_URL=https://your-cluster.cloud.weaviate.cloud")
        print("  export WEAVIATE_API_KEY=your-api-key")
        sys.exit(1)

    # Count total vectors to migrate
    total = count_postgres_vectors()
    print(f"📊 Found {total:,} events with embeddings in PostgreSQL")
    print()

    if dry_run:
        print("🔍 Dry run mode - no data will be migrated")
        return 0

    if total == 0:
        print("✓ Nothing to migrate")
        return 0

    # Initialize vector store
    try:
        vector_store = get_vector_store()
        if not isinstance(vector_store, WeaviateVectorStore):
            print("❌ Error: Vector store is not configured for Weaviate")
            print("   Check WEAVIATE_URL and WEAVIATE_API_KEY environment variables")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Error initializing Weaviate: {e}")
        sys.exit(1)

    print(f"🚀 Starting migration (batch size: {batch_size})")
    print()

    # Fetch and migrate in batches
    migrated = 0
    offset = 0

    with get_conn() as conn:
        with conn.cursor() as cur:
            while True:
                # Fetch batch
                cur.execute(
                    """
                    SELECT id, embed, timestamp, source, categories, tags
                    FROM events
                    WHERE embed IS NOT NULL
                    ORDER BY timestamp DESC
                    LIMIT %s OFFSET %s
                    """,
                    (batch_size, offset),
                )

                rows = cur.fetchall()
                if not rows:
                    break

                # Prepare vectors for batch insert
                vectors = []
                for row in rows:
                    vectors.append(
                        (
                            row["id"],
                            row["embed"],
                            {
                                "timestamp": row["timestamp"],
                                "source": row["source"],
                                "categories": row["categories"] or [],
                                "tags": row["tags"] or [],
                            },
                        )
                    )

                # Insert batch
                try:
                    inserted = vector_store.insert_batch(vectors)
                    migrated += inserted

                    progress = (migrated / total) * 100
                    print(
                        f"  ✓ Migrated {migrated:,} / {total:,} vectors ({progress:.1f}%)"
                    )

                    if inserted < len(vectors):
                        print(
                            f"  ⚠️  Warning: Only {inserted}/{len(vectors)} vectors inserted in this batch"
                        )

                except Exception as e:
                    print(f"  ❌ Error inserting batch at offset {offset}: {e}")
                    break

                offset += batch_size

    print()
    print("=" * 70)
    print(f"✓ Migration complete: {migrated:,} vectors migrated")
    print("=" * 70)
    print()

    # Verify
    print("🔍 Verifying migration...")
    weaviate_count = vector_store.count()
    print(f"  PostgreSQL: {total:,} vectors")
    print(f"  Weaviate:   {weaviate_count:,} vectors")

    if weaviate_count >= migrated:
        print()
        print("✅ Migration verified successfully!")
    else:
        print()
        print(
            f"⚠️  Warning: Expected {migrated:,} vectors but Weaviate has {weaviate_count:,}"
        )

    return migrated


def main():
    parser = argparse.ArgumentParser(
        description="Migrate event vectors from PostgreSQL to Weaviate"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of vectors to process per batch (default: 100)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count vectors without migrating",
    )

    args = parser.parse_args()

    try:
        migrated = migrate_vectors(batch_size=args.batch_size, dry_run=args.dry_run)

        if not args.dry_run:
            print()
            print("Next steps:")
            print("1. Verify vector search works: GET /events/{event_id}/similar")
            print("2. Test event forecasting: GET /forecast/event/{event_id}")
            print("3. (Optional) Remove embed column from PostgreSQL:")
            print("   ALTER TABLE events DROP COLUMN embed;")

    except KeyboardInterrupt:
        print()
        print("❌ Migration interrupted by user")
        sys.exit(1)
    except Exception as e:
        print()
        print(f"❌ Migration failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
