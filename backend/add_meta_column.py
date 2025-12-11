"""
Add meta JSONB column to events table for storing additional metadata.

This migration adds a meta column to store NewsID, PlayerID, and other
metadata from external sources like SportsData.io.

Usage:
    python -m add_meta_column
"""

from db import get_conn

def add_meta_column():
    """Add meta JSONB column to events table if it doesn't exist."""

    print("[migration] Adding meta column to events table...")

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Check if column exists
            cur.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'events'
                  AND column_name = 'meta'
            """)

            if cur.fetchone():
                print("[migration] ✓ meta column already exists")
                return

            # Add column
            cur.execute("""
                ALTER TABLE events
                ADD COLUMN meta JSONB
            """)

            print("[migration] ✓ Added meta JSONB column to events table")

            # Create GIN index for efficient JSONB queries
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_meta
                ON events USING GIN (meta)
            """)

            print("[migration] ✓ Created GIN index on meta column")


if __name__ == "__main__":
    add_meta_column()
    print("[migration] Migration complete!")
