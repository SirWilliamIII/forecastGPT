"""
Database migration: Add forecast_snapshots table.

This script creates the forecast_snapshots table and indexes in an existing database.
Safe to run multiple times (uses IF NOT EXISTS).

Usage:
    python -m migrate_forecast_snapshots
"""

from db import get_conn


def migrate():
    """Add forecast_snapshots table to database."""
    print("[migrate] Adding forecast_snapshots table...")

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Create table
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS forecast_snapshots (
                    id SERIAL PRIMARY KEY,

                    -- What is being forecasted
                    symbol VARCHAR(50) NOT NULL,             -- 'NFL:DAL_COWBOYS', 'BTC-USD', etc.
                    forecast_type VARCHAR(50) NOT NULL,      -- 'win_probability', 'price_return', 'point_spread'

                    -- When this forecast was made
                    snapshot_at TIMESTAMPTZ NOT NULL,        -- When this forecast snapshot was taken

                    -- The forecast value
                    forecast_value DOUBLE PRECISION NOT NULL, -- Win probability (0.0-1.0), return %, spread, etc.
                    confidence DOUBLE PRECISION,              -- Confidence score (0.0-1.0), nullable
                    sample_size INTEGER,                      -- Number of similar events/games used, nullable

                    -- Forecast source and version
                    model_source VARCHAR(50) NOT NULL,       -- 'ml_model_v2', 'baker_api', 'event_weighted', 'naive_baseline'
                    model_version VARCHAR(20),               -- 'v2.0', 'v2.1', etc. (nullable for external sources)

                    -- Optional event attribution (what triggered this snapshot?)
                    event_id UUID REFERENCES events(id) ON DELETE SET NULL,  -- Triggering event (nullable)
                    event_summary TEXT,                      -- Brief event description for UI tooltips

                    -- Target prediction metadata
                    target_date TIMESTAMPTZ,                 -- When the forecasted event will occur (e.g., game date)
                    horizon_minutes INTEGER,                 -- Forecast horizon in minutes (nullable for non-time-based)

                    -- Model metadata (flexible JSON for features, hyperparams, etc.)
                    metadata JSONB,                          -- {features_used: [...], feature_version: "v1.0", training_date: "2025-12-01"}

                    -- Audit trail
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

                    -- Prevent exact duplicates (same symbol + type + source + time)
                    -- Allows multiple snapshots at the same timestamp from different sources
                    CONSTRAINT forecast_snapshots_unique UNIQUE(symbol, forecast_type, model_source, snapshot_at)
                )
                """
            )
            print("[migrate] ✓ Table created")

            # Create indexes
            indexes = [
                (
                    "idx_forecast_snapshots_timeline",
                    "CREATE INDEX IF NOT EXISTS idx_forecast_snapshots_timeline ON forecast_snapshots (symbol, forecast_type, snapshot_at DESC)",
                ),
                (
                    "idx_forecast_snapshots_compare",
                    "CREATE INDEX IF NOT EXISTS idx_forecast_snapshots_compare ON forecast_snapshots (symbol, snapshot_at DESC, model_source)",
                ),
                (
                    "idx_forecast_snapshots_event",
                    "CREATE INDEX IF NOT EXISTS idx_forecast_snapshots_event ON forecast_snapshots (event_id) WHERE event_id IS NOT NULL",
                ),
                (
                    "idx_forecast_snapshots_recent",
                    "CREATE INDEX IF NOT EXISTS idx_forecast_snapshots_recent ON forecast_snapshots (snapshot_at DESC)",
                ),
                (
                    "idx_forecast_snapshots_target",
                    "CREATE INDEX IF NOT EXISTS idx_forecast_snapshots_target ON forecast_snapshots (target_date) WHERE target_date IS NOT NULL",
                ),
                (
                    "idx_forecast_snapshots_model",
                    "CREATE INDEX IF NOT EXISTS idx_forecast_snapshots_model ON forecast_snapshots (model_source, model_version) WHERE model_version IS NOT NULL",
                ),
                (
                    "idx_forecast_snapshots_metadata",
                    "CREATE INDEX IF NOT EXISTS idx_forecast_snapshots_metadata ON forecast_snapshots USING GIN (metadata)",
                ),
            ]

            for name, sql in indexes:
                cur.execute(sql)
                print(f"[migrate] ✓ Index created: {name}")

            conn.commit()

    print("[migrate] ✓ Migration complete!")


def verify():
    """Verify the table was created successfully."""
    print("[migrate] Verifying migration...")

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Check table exists
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'forecast_snapshots'
                ) as exists
                """
            )
            row = cur.fetchone()
            exists = row["exists"] if row else False

            if not exists:
                print("[migrate] ✗ Table not found!")
                return False

            # Count rows
            cur.execute("SELECT COUNT(*) as count FROM forecast_snapshots")
            row = cur.fetchone()
            count = row["count"] if row else 0
            print(f"[migrate] ✓ Table exists with {count} rows")

            # Check indexes
            cur.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE tablename = 'forecast_snapshots'
                ORDER BY indexname
                """
            )
            indexes = cur.fetchall()
            print(f"[migrate] ✓ Found {len(indexes)} indexes:")
            for idx in indexes:
                print(f"[migrate]   - {idx['indexname']}")

    return True


if __name__ == "__main__":
    print("="*70)
    print("Forecast Snapshots Table Migration")
    print("="*70)
    print()

    migrate()
    print()
    verify()

    print()
    print("="*70)
    print("Next steps:")
    print("  1. Run backfill: python -m ingest.backfill_forecasts --dry-run")
    print("  2. Test backfill: python -m ingest.backfill_forecasts --symbol NFL:DAL_COWBOYS --days 7")
    print("  3. Full backfill: python -m ingest.backfill_forecasts --days 60")
    print("="*70)
