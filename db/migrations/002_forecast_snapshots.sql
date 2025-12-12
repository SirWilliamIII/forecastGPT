-- Migration: Forecast Snapshots for Timeline Graphs
-- Created: 2025-12-11
-- Purpose: Store historical forecast snapshots to visualize prediction changes over time
--
-- This migration adds the forecast_snapshots table to track how forecasts evolve as:
-- - New events occur (news, injuries, roster changes)
-- - New data arrives (game results, team stats updates)
-- - Model versions change (ml_model_v2 -> ml_model_v3)
--
-- Use case: Timeline graphs showing "3 days ago we predicted 65% win prob,
-- after the QB injury event it dropped to 52%, now it's back to 58%"

-- ═══════════════════════════════════════════════════════════════════════
-- Table: forecast_snapshots
-- Purpose: Time-series storage of forecast values with event attribution
-- ═══════════════════════════════════════════════════════════════════════

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
    -- Note: We allow multiple snapshots at the same timestamp from different sources
    CONSTRAINT forecast_snapshots_unique UNIQUE(symbol, forecast_type, model_source, snapshot_at)
);

-- ═══════════════════════════════════════════════════════════════════════
-- Indexes: Optimized for timeline queries and event lookups
-- ═══════════════════════════════════════════════════════════════════════

-- Primary query pattern: Get forecast timeline for a symbol over a date range
-- Query: SELECT * FROM forecast_snapshots
--        WHERE symbol = 'NFL:DAL_COWBOYS'
--          AND forecast_type = 'win_probability'
--          AND snapshot_at BETWEEN '2025-12-01' AND '2025-12-11'
--        ORDER BY snapshot_at DESC;
CREATE INDEX idx_forecast_snapshots_timeline
ON forecast_snapshots (symbol, forecast_type, snapshot_at DESC);

-- Secondary pattern: Get all forecast sources for a symbol at a specific time
-- (Compare ml_model_v2 vs baker_api vs event_weighted predictions)
-- Query: SELECT * FROM forecast_snapshots
--        WHERE symbol = 'NFL:DAL_COWBOYS'
--          AND snapshot_at = '2025-12-10 14:00:00+00';
CREATE INDEX idx_forecast_snapshots_compare
ON forecast_snapshots (symbol, snapshot_at DESC, model_source);

-- Event-driven queries: Find all forecasts influenced by a specific event
-- Query: SELECT * FROM forecast_snapshots
--        WHERE event_id = '123e4567-e89b-12d3-a456-426614174000';
CREATE INDEX idx_forecast_snapshots_event
ON forecast_snapshots (event_id) WHERE event_id IS NOT NULL;

-- Recent snapshots across all symbols (dashboard queries)
-- Query: SELECT DISTINCT ON (symbol, forecast_type, model_source) *
--        FROM forecast_snapshots
--        ORDER BY symbol, forecast_type, model_source, snapshot_at DESC;
CREATE INDEX idx_forecast_snapshots_recent
ON forecast_snapshots (snapshot_at DESC);

-- Target date queries: Find forecasts for upcoming games/events
-- Query: SELECT * FROM forecast_snapshots
--        WHERE target_date BETWEEN NOW() AND NOW() + INTERVAL '7 days'
--        ORDER BY target_date;
CREATE INDEX idx_forecast_snapshots_target
ON forecast_snapshots (target_date) WHERE target_date IS NOT NULL;

-- Model source queries: Get all snapshots from a specific model version
-- (Useful for A/B testing and model performance comparison)
-- Query: SELECT * FROM forecast_snapshots
--        WHERE model_source = 'ml_model_v2'
--          AND model_version = 'v2.0'
--        ORDER BY snapshot_at DESC;
CREATE INDEX idx_forecast_snapshots_model
ON forecast_snapshots (model_source, model_version) WHERE model_version IS NOT NULL;

-- JSONB metadata index for feature version queries
-- Query: SELECT * FROM forecast_snapshots
--        WHERE metadata->>'feature_version' = 'v1.0';
CREATE INDEX idx_forecast_snapshots_metadata
ON forecast_snapshots USING GIN (metadata);

-- ═══════════════════════════════════════════════════════════════════════
-- Migration Notes & Design Decisions
-- ═══════════════════════════════════════════════════════════════════════

-- 1. PARTITIONING STRATEGY (Future optimization for scale):
--    - Table can be partitioned by snapshot_at (monthly/quarterly partitions)
--    - Example: forecast_snapshots_2025_q1, forecast_snapshots_2025_q2, etc.
--    - Threshold: Consider partitioning after 1M+ rows or 6+ months of data
--    - Command: ALTER TABLE forecast_snapshots PARTITION BY RANGE (snapshot_at);

-- 2. DATA RETENTION POLICY:
--    - Recommend keeping raw snapshots for 90 days
--    - After 90 days, aggregate to hourly/daily snapshots for storage efficiency
--    - Delete rule: DELETE FROM forecast_snapshots
--                   WHERE snapshot_at < NOW() - INTERVAL '90 days'
--                     AND model_source != 'ml_model_production';  -- Keep prod model history

-- 3. UNIQUE CONSTRAINT RATIONALE:
--    - (symbol, forecast_type, model_source, snapshot_at) ensures no duplicate snapshots
--    - Allows multiple model sources to coexist at the same timestamp
--    - Example: ml_model_v2, baker_api, and event_weighted can all run at 14:00:00
--    - Prevents accidental double-writes from background jobs

-- 4. EVENT ATTRIBUTION:
--    - event_id is nullable because not all snapshots are event-driven
--    - Examples of non-event snapshots: scheduled daily backfills, manual recalculations
--    - ON DELETE SET NULL preserves forecast history even if triggering event is deleted
--    - event_summary denormalized for UI performance (avoid JOIN on every timeline query)

-- 5. TIMEZONE HANDLING:
--    - All TIMESTAMPTZ columns store UTC (per project standards)
--    - Application layer must validate timezone-aware datetimes before INSERT
--    - Frontend converts to user's local timezone for display

-- 6. MODEL VERSIONING:
--    - model_source is broad category (ml_model, baker_api, naive_baseline)
--    - model_version tracks specific release (v2.0, v2.1, v3.0-beta)
--    - Allows A/B testing: compare ml_model_v2 vs ml_model_v3 predictions side-by-side
--    - External APIs (baker_api) may not have version tracking (nullable)

-- 7. METADATA FLEXIBILITY:
--    - JSONB metadata stores model-specific context without schema changes
--    - Examples: {features_used: [win_pct, point_diff], training_samples: 850, rmse: 0.12}
--    - Enables retrospective analysis: "which features were used in this prediction?"
--    - GIN index supports fast queries on nested JSON fields

-- 8. SAMPLE SIZE AND CONFIDENCE:
--    - sample_size tracks statistical rigor (e.g., 50 similar games vs 5 similar games)
--    - confidence represents model uncertainty (0.0 = no confidence, 1.0 = very confident)
--    - UI can display confidence bands and warn on low sample sizes
--    - Both nullable because not all models provide these metrics

-- 9. INTEGRATION WITH EXISTING SYSTEM:
--    - Complements (not replaces) asset_returns table
--    - asset_returns: Realized outcomes (what actually happened)
--    - forecast_snapshots: Predicted outcomes at various points in time
--    - Join pattern: Compare predictions vs reality for model evaluation

-- 10. PERFORMANCE CHARACTERISTICS:
--     - Expected write volume: 10-100 snapshots/hour (per symbol)
--     - Expected read volume: Timeline queries on page load (1-10/sec peak)
--     - Index strategy optimized for read-heavy workload
--     - B-tree indexes for time-based queries (most common access pattern)
--     - GIN index for flexible JSON queries (less frequent, more complex)

-- ═══════════════════════════════════════════════════════════════════════
-- Example Usage Queries
-- ═══════════════════════════════════════════════════════════════════════

-- Example 1: Get Cowboys forecast timeline for next game
-- SELECT snapshot_at, forecast_value, confidence, model_source, event_summary
-- FROM forecast_snapshots
-- WHERE symbol = 'NFL:DAL_COWBOYS'
--   AND forecast_type = 'win_probability'
--   AND snapshot_at >= NOW() - INTERVAL '7 days'
-- ORDER BY snapshot_at DESC;

-- Example 2: Compare all model sources at latest snapshot time
-- SELECT DISTINCT ON (model_source)
--        model_source, forecast_value, confidence, snapshot_at
-- FROM forecast_snapshots
-- WHERE symbol = 'NFL:DAL_COWBOYS'
--   AND forecast_type = 'win_probability'
-- ORDER BY model_source, snapshot_at DESC;

-- Example 3: Event impact analysis (before/after QB injury)
-- WITH event AS (
--   SELECT id, timestamp FROM events WHERE title ILIKE '%dak prescott injury%' LIMIT 1
-- )
-- SELECT
--   CASE WHEN fs.snapshot_at < e.timestamp THEN 'before' ELSE 'after' END AS period,
--   AVG(fs.forecast_value) AS avg_win_prob,
--   COUNT(*) AS snapshot_count
-- FROM forecast_snapshots fs
-- CROSS JOIN event e
-- WHERE fs.symbol = 'NFL:DAL_COWBOYS'
--   AND fs.forecast_type = 'win_probability'
--   AND fs.snapshot_at BETWEEN e.timestamp - INTERVAL '24 hours'
--                          AND e.timestamp + INTERVAL '24 hours'
-- GROUP BY period;

-- Example 4: Model performance comparison (backtest)
-- SELECT
--   fs.model_source,
--   fs.model_version,
--   AVG(ABS(fs.forecast_value - (CASE WHEN ar.realized_return > 0 THEN 1.0 ELSE 0.0 END))) AS mae,
--   COUNT(*) AS prediction_count
-- FROM forecast_snapshots fs
-- JOIN asset_returns ar
--   ON fs.symbol = ar.symbol
--   AND fs.snapshot_at <= ar.as_of  -- Only count predictions made before outcome
--   AND ABS(EXTRACT(EPOCH FROM (ar.as_of - fs.snapshot_at))/3600) <= 48  -- Within 48 hours
-- WHERE fs.forecast_type = 'win_probability'
--   AND ar.horizon_minutes = 0  -- Actual game outcomes
-- GROUP BY fs.model_source, fs.model_version
-- ORDER BY mae;

-- ═══════════════════════════════════════════════════════════════════════
-- Rollback Procedure
-- ═══════════════════════════════════════════════════════════════════════

-- To roll back this migration (CAUTION: Destroys all forecast history):
-- DROP TABLE IF EXISTS forecast_snapshots CASCADE;

-- To archive before rollback (recommended):
-- CREATE TABLE forecast_snapshots_archive AS SELECT * FROM forecast_snapshots;
-- DROP TABLE IF EXISTS forecast_snapshots CASCADE;
