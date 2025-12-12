# Forecast Snapshots Table Schema

## Overview

The `forecast_snapshots` table stores time-series forecast data to enable visualization of how predictions evolve over time. This powers timeline graphs showing prediction changes as new events occur (injuries, roster moves, news) and new data arrives (game results, team stats updates).

**Use Case Example:**
```
Cowboys next game forecast timeline:
├─ 7 days ago:  65% win probability (baseline)
├─ 3 days ago:  52% win probability (after QB injury event)
├─ 1 day ago:   58% win probability (after backup QB practice report)
└─ Now:         61% win probability (updated with latest team stats)
```

## Table Definition

```sql
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
    CONSTRAINT forecast_snapshots_unique UNIQUE(symbol, forecast_type, model_source, snapshot_at)
);
```

## Column Descriptions

### Core Identification

| Column | Type | Nullable | Description | Example Values |
|--------|------|----------|-------------|----------------|
| `id` | SERIAL | No | Auto-increment primary key | 1, 2, 3, ... |
| `symbol` | VARCHAR(50) | No | Asset/team symbol being forecasted | 'NFL:DAL_COWBOYS', 'BTC-USD', 'NVDA' |
| `forecast_type` | VARCHAR(50) | No | Type of metric being predicted | 'win_probability', 'price_return', 'point_spread', 'total_points' |

### Temporal Fields

| Column | Type | Nullable | Description | Example Values |
|--------|------|----------|-------------|----------------|
| `snapshot_at` | TIMESTAMPTZ | No | When this forecast was generated (UTC) | '2025-12-11 14:00:00+00' |
| `target_date` | TIMESTAMPTZ | Yes | When the predicted event will occur | '2025-12-15 13:00:00+00' (game kickoff) |
| `horizon_minutes` | INTEGER | Yes | Minutes from snapshot_at to target_date | 1440 (1 day), 10080 (1 week) |
| `created_at` | TIMESTAMPTZ | No | When row was inserted into database | '2025-12-11 14:00:01+00' |

### Forecast Values

| Column | Type | Nullable | Description | Example Values |
|--------|------|----------|-------------|----------------|
| `forecast_value` | DOUBLE PRECISION | No | The predicted value | 0.65 (65% win prob), 0.035 (3.5% return), -3.5 (3.5 point underdog) |
| `confidence` | DOUBLE PRECISION | Yes | Model confidence score (0.0-1.0) | 0.75 (75% confident), 0.50 (uncertain) |
| `sample_size` | INTEGER | Yes | Number of samples used in prediction | 50 (similar games), 100 (similar events) |

### Model Attribution

| Column | Type | Nullable | Description | Example Values |
|--------|------|----------|-------------|----------------|
| `model_source` | VARCHAR(50) | No | Model category/name | 'ml_model_v2', 'baker_api', 'event_weighted', 'naive_baseline' |
| `model_version` | VARCHAR(20) | Yes | Specific model release version | 'v2.0', 'v2.1', 'v3.0-beta' |
| `metadata` | JSONB | Yes | Model configuration details | `{"features": ["win_pct", "point_diff"], "rmse": 0.12}` |

### Event Attribution

| Column | Type | Nullable | Description | Example Values |
|--------|------|----------|-------------|----------------|
| `event_id` | UUID | Yes | Foreign key to events table (what triggered snapshot) | 'a7b8c9d0-1234-5678-9abc-def012345678' |
| `event_summary` | TEXT | Yes | Denormalized event description for UI | 'Dak Prescott ankle injury - questionable for Sunday' |

## Indexes

### 1. Timeline Index (Primary Query Pattern)
```sql
CREATE INDEX idx_forecast_snapshots_timeline
ON forecast_snapshots (symbol, forecast_type, snapshot_at DESC);
```

**Purpose:** Retrieve forecast evolution for a symbol over time.

**Example Query:**
```sql
-- Get Cowboys win probability timeline for last 7 days
SELECT snapshot_at, forecast_value, confidence, model_source, event_summary
FROM forecast_snapshots
WHERE symbol = 'NFL:DAL_COWBOYS'
  AND forecast_type = 'win_probability'
  AND snapshot_at >= NOW() - INTERVAL '7 days'
ORDER BY snapshot_at DESC;
```

### 2. Comparison Index (A/B Testing)
```sql
CREATE INDEX idx_forecast_snapshots_compare
ON forecast_snapshots (symbol, snapshot_at DESC, model_source);
```

**Purpose:** Compare multiple model predictions at the same timestamp.

**Example Query:**
```sql
-- Compare all models' latest predictions for Cowboys
SELECT DISTINCT ON (model_source)
       model_source, forecast_value, confidence, snapshot_at
FROM forecast_snapshots
WHERE symbol = 'NFL:DAL_COWBOYS'
  AND forecast_type = 'win_probability'
ORDER BY model_source, snapshot_at DESC;
```

### 3. Event Attribution Index
```sql
CREATE INDEX idx_forecast_snapshots_event
ON forecast_snapshots (event_id) WHERE event_id IS NOT NULL;
```

**Purpose:** Find all forecasts influenced by a specific event.

**Example Query:**
```sql
-- Get all forecasts triggered by QB injury event
SELECT symbol, forecast_type, snapshot_at, forecast_value
FROM forecast_snapshots
WHERE event_id = 'a7b8c9d0-1234-5678-9abc-def012345678'
ORDER BY snapshot_at;
```

### 4. Recent Snapshots Index (Dashboard)
```sql
CREATE INDEX idx_forecast_snapshots_recent
ON forecast_snapshots (snapshot_at DESC);
```

**Purpose:** Global recent activity across all symbols.

**Example Query:**
```sql
-- Get latest snapshot per symbol/model combination
SELECT DISTINCT ON (symbol, forecast_type, model_source)
       symbol, forecast_type, model_source, forecast_value, snapshot_at
FROM forecast_snapshots
ORDER BY symbol, forecast_type, model_source, snapshot_at DESC;
```

### 5. Target Date Index (Upcoming Events)
```sql
CREATE INDEX idx_forecast_snapshots_target
ON forecast_snapshots (target_date) WHERE target_date IS NOT NULL;
```

**Purpose:** Find forecasts for games/events happening soon.

**Example Query:**
```sql
-- Get all forecasts for games in next 7 days
SELECT symbol, forecast_type, target_date, forecast_value, snapshot_at
FROM forecast_snapshots
WHERE target_date BETWEEN NOW() AND NOW() + INTERVAL '7 days'
ORDER BY target_date;
```

### 6. Model Version Index (Performance Analysis)
```sql
CREATE INDEX idx_forecast_snapshots_model
ON forecast_snapshots (model_source, model_version) WHERE model_version IS NOT NULL;
```

**Purpose:** Analyze specific model version performance.

**Example Query:**
```sql
-- Get all predictions from ML model v2.0
SELECT symbol, forecast_type, snapshot_at, forecast_value
FROM forecast_snapshots
WHERE model_source = 'ml_model_v2'
  AND model_version = 'v2.0'
ORDER BY snapshot_at DESC;
```

### 7. Metadata Index (Feature Analysis)
```sql
CREATE INDEX idx_forecast_snapshots_metadata
ON forecast_snapshots USING GIN (metadata);
```

**Purpose:** Query on metadata JSON fields.

**Example Query:**
```sql
-- Find all forecasts using feature version v1.0
SELECT symbol, snapshot_at, forecast_value, metadata
FROM forecast_snapshots
WHERE metadata->>'feature_version' = 'v1.0';
```

## Unique Constraint

```sql
CONSTRAINT forecast_snapshots_unique
UNIQUE(symbol, forecast_type, model_source, snapshot_at)
```

**Prevents:** Duplicate snapshots from the same model at the same time.

**Allows:** Multiple models to generate forecasts at the same timestamp:
```
| symbol          | forecast_type  | model_source    | snapshot_at         | forecast_value |
|-----------------|----------------|-----------------|---------------------|----------------|
| NFL:DAL_COWBOYS | win_probability| ml_model_v2     | 2025-12-11 14:00:00 | 0.65           |
| NFL:DAL_COWBOYS | win_probability| baker_api       | 2025-12-11 14:00:00 | 0.62           |
| NFL:DAL_COWBOYS | win_probability| event_weighted  | 2025-12-11 14:00:00 | 0.68           |
```

## Foreign Key Relationship

```sql
event_id UUID REFERENCES events(id) ON DELETE SET NULL
```

**Relationship:** Many-to-one (many snapshots can reference one event).

**ON DELETE SET NULL:** If triggering event is deleted, preserve forecast history but remove attribution.

**Example:**
```
events table:
├─ id: a7b8c9d0-... | title: "Dak Prescott injury report"

forecast_snapshots table:
├─ event_id: a7b8c9d0-... | forecast_value: 0.52 | event_summary: "QB injury"
├─ event_id: a7b8c9d0-... | forecast_value: 0.51 | event_summary: "QB injury"
└─ event_id: a7b8c9d0-... | forecast_value: 0.50 | event_summary: "QB injury"
```

If event is deleted: `event_id` → NULL, but rows preserved with `event_summary`.

## Common Query Patterns

### 1. Timeline Graph Data
```sql
-- Get forecast evolution for next Cowboys game
SELECT
    snapshot_at,
    forecast_value,
    confidence,
    model_source,
    event_summary,
    sample_size
FROM forecast_snapshots
WHERE symbol = 'NFL:DAL_COWBOYS'
  AND forecast_type = 'win_probability'
  AND target_date = '2025-12-15 13:00:00+00'  -- Specific game
ORDER BY snapshot_at;
```

### 2. Event Impact Analysis (Before/After)
```sql
-- Compare forecasts before/after QB injury
WITH event AS (
  SELECT id, timestamp FROM events
  WHERE title ILIKE '%dak prescott injury%'
  LIMIT 1
)
SELECT
  CASE WHEN fs.snapshot_at < e.timestamp THEN 'before' ELSE 'after' END AS period,
  AVG(fs.forecast_value) AS avg_win_prob,
  STDDEV(fs.forecast_value) AS volatility,
  COUNT(*) AS snapshot_count
FROM forecast_snapshots fs
CROSS JOIN event e
WHERE fs.symbol = 'NFL:DAL_COWBOYS'
  AND fs.forecast_type = 'win_probability'
  AND fs.snapshot_at BETWEEN e.timestamp - INTERVAL '24 hours'
                         AND e.timestamp + INTERVAL '24 hours'
GROUP BY period;
```

### 3. Model Performance Comparison (Backtest)
```sql
-- Compare model accuracy against actual outcomes
SELECT
  fs.model_source,
  fs.model_version,
  AVG(ABS(fs.forecast_value - (CASE WHEN ar.realized_return > 0 THEN 1.0 ELSE 0.0 END))) AS mae,
  COUNT(*) AS prediction_count
FROM forecast_snapshots fs
JOIN asset_returns ar
  ON fs.symbol = ar.symbol
  AND fs.snapshot_at <= ar.as_of  -- Only predictions made before outcome
  AND ABS(EXTRACT(EPOCH FROM (ar.as_of - fs.snapshot_at))/3600) <= 48  -- Within 48 hours
WHERE fs.forecast_type = 'win_probability'
  AND ar.horizon_minutes = 0  -- Actual game outcomes
GROUP BY fs.model_source, fs.model_version
ORDER BY mae;
```

### 4. Confidence-Weighted Ensemble
```sql
-- Create ensemble forecast weighted by model confidence
SELECT
  symbol,
  forecast_type,
  snapshot_at,
  SUM(forecast_value * confidence) / SUM(confidence) AS weighted_forecast,
  AVG(confidence) AS avg_confidence,
  COUNT(*) AS model_count
FROM forecast_snapshots
WHERE symbol = 'NFL:DAL_COWBOYS'
  AND forecast_type = 'win_probability'
  AND snapshot_at >= NOW() - INTERVAL '1 hour'
  AND confidence IS NOT NULL
GROUP BY symbol, forecast_type, snapshot_at
ORDER BY snapshot_at DESC;
```

### 5. Sample Size Quality Filter
```sql
-- Only show high-quality forecasts with sufficient data
SELECT
  snapshot_at,
  forecast_value,
  confidence,
  sample_size,
  model_source
FROM forecast_snapshots
WHERE symbol = 'NFL:DAL_COWBOYS'
  AND forecast_type = 'win_probability'
  AND sample_size >= 20  -- Minimum 20 similar events/games
ORDER BY snapshot_at DESC;
```

## Data Retention Strategy

### Short-term (0-90 days)
- **Policy:** Keep all raw snapshots (every prediction)
- **Purpose:** High-resolution timeline graphs, event impact analysis
- **Frequency:** Every forecast run (could be hourly or event-driven)

### Medium-term (90-365 days)
- **Policy:** Aggregate to hourly snapshots, keep production model only
- **Purpose:** Historical trends, model performance tracking
- **SQL:**
```sql
-- Archive old snapshots (keep hourly aggregates)
DELETE FROM forecast_snapshots
WHERE snapshot_at < NOW() - INTERVAL '90 days'
  AND model_source != 'ml_model_production'
  AND EXTRACT(MINUTE FROM snapshot_at) != 0;  -- Keep hourly snapshots
```

### Long-term (365+ days)
- **Policy:** Aggregate to daily snapshots, archive to S3/external storage
- **Purpose:** Year-over-year comparisons, regulatory compliance
- **SQL:**
```sql
-- Create daily archive table
CREATE TABLE forecast_snapshots_archive AS
SELECT
  symbol,
  forecast_type,
  DATE_TRUNC('day', snapshot_at) AS snapshot_day,
  model_source,
  AVG(forecast_value) AS avg_forecast,
  AVG(confidence) AS avg_confidence,
  COUNT(*) AS snapshot_count
FROM forecast_snapshots
WHERE snapshot_at < NOW() - INTERVAL '365 days'
GROUP BY symbol, forecast_type, snapshot_day, model_source;
```

## Performance Considerations

### Write Volume
- **Expected:** 10-100 snapshots/hour per symbol
- **Peak:** 500-1000 snapshots/hour (during live games with event-driven updates)
- **Annual:** ~1M rows/year for 10 symbols with hourly snapshots

### Read Volume
- **Dashboard loads:** 1-10 queries/second
- **Timeline graphs:** 1 query per page load (cached in frontend)
- **Backtest analysis:** Batch queries (off-peak hours)

### Storage Estimates
- **Row size:** ~300 bytes average (including indexes)
- **1M rows:** ~300 MB
- **10M rows:** ~3 GB (with indexes: ~5 GB)
- **Partition threshold:** Consider monthly partitioning after 1M rows

### Partitioning Strategy (Future)
```sql
-- Partition by month for large datasets
ALTER TABLE forecast_snapshots PARTITION BY RANGE (snapshot_at);

CREATE TABLE forecast_snapshots_2025_12 PARTITION OF forecast_snapshots
FOR VALUES FROM ('2025-12-01') TO ('2026-01-01');

CREATE TABLE forecast_snapshots_2026_01 PARTITION OF forecast_snapshots
FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
```

## Example Data

```sql
-- Insert example snapshot
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
    event_summary,
    target_date,
    horizon_minutes,
    metadata
) VALUES (
    'NFL:DAL_COWBOYS',
    'win_probability',
    '2025-12-11 14:00:00+00',
    0.65,
    0.75,
    42,
    'ml_model_v2',
    'v2.0',
    'a7b8c9d0-1234-5678-9abc-def012345678',
    'Updated after QB injury report',
    '2025-12-15 13:00:00+00',
    5760,  -- 4 days
    '{"features_used": ["win_pct", "point_diff", "home_away"], "feature_version": "v1.0", "training_date": "2025-12-01", "rmse": 0.12}'::jsonb
);
```

## Integration with Existing Tables

### With `events` table
- **Relationship:** forecast_snapshots.event_id → events.id
- **Use case:** Annotate timeline graphs with events that triggered forecast changes
- **Join example:**
```sql
SELECT
    fs.snapshot_at,
    fs.forecast_value,
    e.title AS event_title,
    e.timestamp AS event_time
FROM forecast_snapshots fs
LEFT JOIN events e ON fs.event_id = e.id
WHERE fs.symbol = 'NFL:DAL_COWBOYS'
ORDER BY fs.snapshot_at;
```

### With `asset_returns` table
- **Relationship:** Compare predictions (forecast_snapshots) vs reality (asset_returns)
- **Use case:** Model evaluation, backtesting
- **Join example:**
```sql
SELECT
    fs.snapshot_at,
    fs.forecast_value AS predicted,
    CASE WHEN ar.realized_return > 0 THEN 1.0 ELSE 0.0 END AS actual,
    ABS(fs.forecast_value - (CASE WHEN ar.realized_return > 0 THEN 1.0 ELSE 0.0 END)) AS error
FROM forecast_snapshots fs
JOIN asset_returns ar
  ON fs.symbol = ar.symbol
  AND fs.target_date = ar.as_of
WHERE fs.forecast_type = 'win_probability'
  AND ar.horizon_minutes = 0;
```

### With `projections` table
- **Relationship:** External projections (Baker API) → forecast_snapshots
- **Use case:** Import external forecasts into snapshot history
- **Migration example:**
```sql
-- Import Baker API projections as snapshots
INSERT INTO forecast_snapshots (
    symbol, forecast_type, snapshot_at, forecast_value,
    model_source, target_date, horizon_minutes
)
SELECT
    symbol,
    'win_probability' AS forecast_type,
    as_of AS snapshot_at,
    projected_value AS forecast_value,
    model_source,
    as_of + (horizon_minutes || ' minutes')::INTERVAL AS target_date,
    horizon_minutes
FROM projections
WHERE metric = 'win_prob';
```

## Migration Guide

See `/db/migrations/002_enhance_forecast_snapshots.sql` for detailed migration script.

**Quick migration:**
```bash
# Apply migration to existing database
PGPASSWORD=semantic psql -h localhost -p 5433 -U semantic -d semantic_markets \
  -f db/migrations/002_enhance_forecast_snapshots.sql

# Verify migration
PGPASSWORD=semantic psql -h localhost -p 5433 -U semantic -d semantic_markets \
  -c "SELECT COUNT(*) FROM forecast_snapshots;"

# Clean up backup table (after verification)
PGPASSWORD=semantic psql -h localhost -p 5433 -U semantic -d semantic_markets \
  -c "DROP TABLE IF EXISTS forecast_snapshots_old;"
```

## Best Practices

1. **Always use timezone-aware datetimes (UTC):**
   ```python
   from datetime import datetime, timezone
   snapshot_at = datetime.now(tz=timezone.utc)  # CORRECT
   ```

2. **Denormalize event_summary for UI performance:**
   - Avoid JOIN on events table for every timeline query
   - Store brief summary (1-2 sentences max)

3. **Use batch inserts for backfills:**
   ```python
   cur.executemany(
       "INSERT INTO forecast_snapshots (...) VALUES (%s, %s, ...)",
       snapshot_data_list
   )
   ```

4. **Track model versions for reproducibility:**
   - Always set model_version for ML models
   - Update version when features change

5. **Include sample_size for quality filtering:**
   - Frontend can warn on low sample sizes
   - Filter out low-quality predictions

6. **Use metadata for retrospective analysis:**
   - Store feature lists, hyperparameters, training dates
   - Enables "what features were used in this prediction?" queries

## Troubleshooting

### Duplicate Key Violations
```
ERROR: duplicate key value violates unique constraint "forecast_snapshots_unique"
```

**Cause:** Trying to insert same (symbol, forecast_type, model_source, snapshot_at) twice.

**Solution:**
```sql
-- Use ON CONFLICT to update instead
INSERT INTO forecast_snapshots (...)
VALUES (...)
ON CONFLICT (symbol, forecast_type, model_source, snapshot_at)
DO UPDATE SET
    forecast_value = EXCLUDED.forecast_value,
    confidence = EXCLUDED.confidence,
    sample_size = EXCLUDED.sample_size;
```

### Slow Timeline Queries
**Symptom:** Queries taking >1 second for 7-day timelines.

**Diagnosis:**
```sql
EXPLAIN ANALYZE
SELECT * FROM forecast_snapshots
WHERE symbol = 'NFL:DAL_COWBOYS'
  AND forecast_type = 'win_probability'
  AND snapshot_at >= NOW() - INTERVAL '7 days';
```

**Solution:** Ensure `idx_forecast_snapshots_timeline` index exists and is being used.

### Missing Snapshots After Events
**Symptom:** Event occurred but no new snapshot created.

**Check:**
```sql
-- Verify event exists
SELECT id, timestamp, title FROM events
WHERE title ILIKE '%injury%'
ORDER BY timestamp DESC;

-- Check if forecast job ran
SELECT snapshot_at, event_id, forecast_value
FROM forecast_snapshots
WHERE event_id = '<event_uuid>'
OR snapshot_at >= '<event_timestamp>';
```

**Fix:** Ensure background job is running and event_id is correctly passed.

## Future Enhancements

1. **Real-time streaming:** WebSocket updates for live game forecasts
2. **Confidence bands:** Store upper/lower bounds for uncertainty visualization
3. **Multi-metric snapshots:** Single row with multiple forecast types
4. **Compression:** TimescaleDB hypertables for better compression
5. **Machine learning:** Auto-detect anomalous forecast changes
