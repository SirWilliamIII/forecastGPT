-- Migration 003: Forecast Metrics Table
-- Purpose: Store backtest results for model validation and performance tracking
--
-- This table enables:
-- 1. Historical forecast evaluation (predicted vs actual returns)
-- 2. Confidence calibration analysis
-- 3. Model performance comparison (naive vs event-conditioned)
-- 4. Regime-specific accuracy tracking
-- 5. Horizon degradation analysis
--
-- Run this migration manually with:
--   psql $DATABASE_URL < db/migrations/003_forecast_metrics.sql

CREATE TABLE IF NOT EXISTS forecast_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- What was forecasted
    symbol TEXT NOT NULL,
    as_of TIMESTAMPTZ NOT NULL,              -- When the forecast was made (timezone-aware UTC)
    horizon_minutes INT NOT NULL,             -- Forecast horizon (1440, 10080, 43200 for 1d/7d/30d)

    -- Model identification
    model_name TEXT NOT NULL,                 -- 'naive' or 'event_conditioned'
    schema_version TEXT NOT NULL,             -- Feature schema version ('v1', 'v2', etc.)

    -- Forecast values
    expected_return DOUBLE PRECISION,         -- Predicted return
    realized_return DOUBLE PRECISION,         -- Actual realized return (from asset_returns table)

    -- Direction prediction
    predicted_direction TEXT,                 -- 'up', 'down', 'flat'
    actual_direction TEXT,                    -- 'up', 'down', 'flat'
    direction_correct BOOLEAN,                -- TRUE if predicted_direction == actual_direction

    -- Confidence and sample metrics
    confidence DOUBLE PRECISION,              -- Horizon-normalized confidence score [0, 1]
    sample_size INT,                          -- Number of data points used in forecast

    -- Market context
    regime TEXT,                              -- 'uptrend', 'downtrend', 'chop', 'high_vol'

    -- Audit trail
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes for efficient queries

-- Primary lookup: filter by symbol and time range
CREATE INDEX IF NOT EXISTS forecast_metrics_symbol_time_idx
    ON forecast_metrics (symbol, as_of, horizon_minutes);

-- Model comparison: filter by model and horizon
CREATE INDEX IF NOT EXISTS forecast_metrics_model_idx
    ON forecast_metrics (model_name, horizon_minutes);

-- Regime analysis: filter by regime and correctness
CREATE INDEX IF NOT EXISTS forecast_metrics_regime_idx
    ON forecast_metrics (regime, direction_correct);

-- Confidence calibration: filter by confidence buckets
CREATE INDEX IF NOT EXISTS forecast_metrics_confidence_idx
    ON forecast_metrics (confidence, direction_correct)
    WHERE confidence IS NOT NULL;

-- Time-based queries (for recent performance)
CREATE INDEX IF NOT EXISTS forecast_metrics_created_at_idx
    ON forecast_metrics (created_at DESC);

-- Comments for documentation
COMMENT ON TABLE forecast_metrics IS 'Backtest results for forecast validation and performance tracking';
COMMENT ON COLUMN forecast_metrics.as_of IS 'Timestamp when forecast was generated (timezone-aware UTC)';
COMMENT ON COLUMN forecast_metrics.horizon_minutes IS 'Forecast horizon: 1440 (1d), 10080 (7d), 43200 (30d)';
COMMENT ON COLUMN forecast_metrics.direction_correct IS 'TRUE if forecast direction matched actual direction';
COMMENT ON COLUMN forecast_metrics.confidence IS 'Horizon-normalized confidence score from confidence_utils.py';
COMMENT ON COLUMN forecast_metrics.regime IS 'Market regime at as_of time: uptrend, downtrend, chop, high_vol';
