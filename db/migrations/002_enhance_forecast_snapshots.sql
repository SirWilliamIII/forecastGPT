-- Migration: Enhance Forecast Snapshots Table
-- Created: 2025-12-11
-- Purpose: Upgrade existing forecast_snapshots table to support timeline graphs
--
-- This migration enhances the forecast_snapshots table from the simple version
-- to the production-ready version with:
-- - Better column naming (timestamp → snapshot_at, forecast_type → model_source)
-- - Separate forecast_type field for metric type (win_probability, point_spread, etc.)
-- - Model versioning support (model_version field)
-- - Event summary denormalization for UI performance
-- - Target date tracking for upcoming games
-- - Enhanced indexes for timeline and comparison queries
--
-- IMPORTANT: This migration preserves existing data during the upgrade.

-- ═══════════════════════════════════════════════════════════════════════
-- Step 1: Check if table exists and needs migration
-- ═══════════════════════════════════════════════════════════════════════

DO $$
BEGIN
    -- Check if the table exists with the old schema (has 'timestamp' column)
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'forecast_snapshots'
        AND column_name = 'timestamp'
    ) THEN
        RAISE NOTICE 'Found old forecast_snapshots schema. Starting migration...';
    ELSE
        RAISE NOTICE 'Table either does not exist or already has new schema. Skipping migration.';
        RETURN;
    END IF;
END $$;

-- ═══════════════════════════════════════════════════════════════════════
-- Step 2: Rename table for safe migration
-- ═══════════════════════════════════════════════════════════════════════

-- Create backup of existing data
CREATE TABLE IF NOT EXISTS forecast_snapshots_old AS
SELECT * FROM forecast_snapshots;

-- Drop the old table (we have backup)
DROP TABLE IF EXISTS forecast_snapshots CASCADE;

-- ═══════════════════════════════════════════════════════════════════════
-- Step 3: Create new table with enhanced schema
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE forecast_snapshots (
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
);

-- ═══════════════════════════════════════════════════════════════════════
-- Step 4: Migrate existing data
-- ═══════════════════════════════════════════════════════════════════════

INSERT INTO forecast_snapshots (
    symbol,
    forecast_type,
    snapshot_at,
    forecast_value,
    confidence,
    sample_size,
    model_source,
    model_version,
    event_id,
    target_date,
    horizon_minutes,
    metadata,
    created_at
)
SELECT
    symbol,
    'win_probability' AS forecast_type,           -- Default to win_probability (can be updated manually)
    timestamp AS snapshot_at,                      -- Rename timestamp → snapshot_at
    forecast_value,
    confidence,
    COALESCE(sample_size, 0) AS sample_size,      -- Convert NULL to 0 for compatibility
    forecast_type AS model_source,                 -- Old forecast_type becomes model_source
    NULL AS model_version,                         -- No version info in old schema
    event_id,
    NULL AS target_date,                           -- Not tracked in old schema
    horizon_minutes,
    meta AS metadata,                              -- Rename meta → metadata
    created_at
FROM forecast_snapshots_old;

-- ═══════════════════════════════════════════════════════════════════════
-- Step 5: Create optimized indexes
-- ═══════════════════════════════════════════════════════════════════════

-- Timeline queries: Get forecast evolution for a symbol over date range
CREATE INDEX idx_forecast_snapshots_timeline
ON forecast_snapshots (symbol, forecast_type, snapshot_at DESC);

-- Compare models: Get all forecast sources at specific time (A/B testing)
CREATE INDEX idx_forecast_snapshots_compare
ON forecast_snapshots (symbol, snapshot_at DESC, model_source);

-- Event attribution: Find forecasts influenced by specific event
CREATE INDEX idx_forecast_snapshots_event
ON forecast_snapshots (event_id) WHERE event_id IS NOT NULL;

-- Recent snapshots: Dashboard queries across all symbols
CREATE INDEX idx_forecast_snapshots_recent
ON forecast_snapshots (snapshot_at DESC);

-- Target date: Forecasts for upcoming games/events
CREATE INDEX idx_forecast_snapshots_target
ON forecast_snapshots (target_date) WHERE target_date IS NOT NULL;

-- Model versioning: A/B testing and performance comparison
CREATE INDEX idx_forecast_snapshots_model
ON forecast_snapshots (model_source, model_version) WHERE model_version IS NOT NULL;

-- Metadata queries: Feature version and model configuration
CREATE INDEX idx_forecast_snapshots_metadata
ON forecast_snapshots USING GIN (metadata);

-- ═══════════════════════════════════════════════════════════════════════
-- Step 6: Verify migration
-- ═══════════════════════════════════════════════════════════════════════

DO $$
DECLARE
    old_count INTEGER;
    new_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO old_count FROM forecast_snapshots_old;
    SELECT COUNT(*) INTO new_count FROM forecast_snapshots;

    IF old_count = new_count THEN
        RAISE NOTICE 'Migration successful! Migrated % rows.', new_count;
        RAISE NOTICE 'Old table backup available as forecast_snapshots_old';
    ELSE
        RAISE WARNING 'Row count mismatch! Old: %, New: %', old_count, new_count;
        RAISE WARNING 'Review forecast_snapshots_old for missing data before dropping';
    END IF;
END $$;

-- ═══════════════════════════════════════════════════════════════════════
-- Migration Complete
-- ═══════════════════════════════════════════════════════════════════════

-- To clean up after verifying migration:
-- DROP TABLE IF EXISTS forecast_snapshots_old;

-- To rollback (CAUTION: Destroys new data added after migration):
-- DROP TABLE IF EXISTS forecast_snapshots CASCADE;
-- ALTER TABLE forecast_snapshots_old RENAME TO forecast_snapshots;
