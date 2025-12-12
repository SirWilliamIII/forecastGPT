# Forecast Snapshots System

## Overview

The forecast snapshots system enables time-series visualization of NFL game outcome predictions by storing historical forecast values at specific points in time. This allows you to see how predictions evolved as new events occurred.

**Key Features:**
- **Temporal Correctness**: All forecasts use only data available BEFORE the snapshot timestamp (no lookahead bias)
- **Event Attribution**: Track which news events triggered forecast changes
- **Model Comparison**: Compare different forecast models (event-weighted, ML, baseline) over time
- **Timeline Visualization**: See forecast evolution with event markers

## Architecture

### Database Schema

The `forecast_snapshots` table stores historical forecast values:

```sql
CREATE TABLE forecast_snapshots (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(50) NOT NULL,              -- 'NFL:DAL_COWBOYS', etc.
    forecast_type VARCHAR(50) NOT NULL,       -- 'win_probability', 'point_spread'
    snapshot_at TIMESTAMPTZ NOT NULL,         -- When forecast was made
    forecast_value DOUBLE PRECISION NOT NULL, -- Predicted value (0.0-1.0 for win prob)
    confidence DOUBLE PRECISION,              -- Confidence score
    sample_size INTEGER,                      -- Number of samples used
    model_source VARCHAR(50) NOT NULL,        -- 'event_weighted', 'ml_model_v2', etc.
    model_version VARCHAR(20),                -- Model version
    event_id UUID,                            -- Triggering event (nullable)
    event_summary TEXT,                       -- Event description for UI
    target_date TIMESTAMPTZ,                  -- Game date being predicted
    horizon_minutes INTEGER,                  -- Forecast horizon
    metadata JSONB,                           -- Model features, config, etc.
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT forecast_snapshots_unique UNIQUE(symbol, forecast_type, model_source, snapshot_at)
);
```

### Indexes

Optimized for common query patterns:

- **Timeline queries**: `(symbol, forecast_type, snapshot_at DESC)`
- **Model comparison**: `(symbol, snapshot_at DESC, model_source)`
- **Event attribution**: `(event_id)` where event_id IS NOT NULL
- **Recent snapshots**: `(snapshot_at DESC)`
- **Upcoming games**: `(target_date)` where target_date IS NOT NULL

## Usage

### 1. Database Migration

Add the table to an existing database:

```bash
cd backend
python -m migrate_forecast_snapshots
```

### 2. Backfill Historical Forecasts

Compute historical forecast snapshots for past events:

```bash
# Dry run (no database writes)
python -m ingest.backfill_forecasts --dry-run

# Backfill single team for testing
python -m ingest.backfill_forecasts --symbol NFL:DAL_COWBOYS --days 7

# Full backfill (all teams, 60 days)
python -m ingest.backfill_forecasts --days 60

# Specific forecast types only
python -m ingest.backfill_forecasts --types event_weighted,baseline --days 30
```

**Performance:**
- Processes ~50 events per team in backfill window
- Batch inserts (100 snapshots per batch)
- Typical runtime: 2-5 minutes per team for 60-day window
- Idempotent: safe to re-run (skips duplicates)

### 3. API Endpoints

#### Get Forecast Timeline

Retrieve time-series of forecast snapshots:

```bash
GET /nfl/teams/NFL:DAL_COWBOYS/forecast-timeline?days=30&forecast_type=win_probability
```

**Parameters:**
- `forecast_type`: Forecast metric (default: `win_probability`)
- `days`: Lookback window (1-365, default: 30)
- `model_source`: Filter by model (optional: `event_weighted`, `ml_model_v2`, `naive_baseline`)

**Response:**
```json
{
  "symbol": "NFL:DAL_COWBOYS",
  "forecast_type": "win_probability",
  "start_date": "2025-11-11T00:00:00Z",
  "end_date": "2025-12-11T00:00:00Z",
  "snapshots_count": 45,
  "snapshots": [
    {
      "timestamp": "2025-12-10T14:23:00Z",
      "forecast_value": 0.58,
      "confidence": 0.72,
      "model_source": "event_weighted",
      "model_version": "v1.0",
      "event_id": "123e4567-e89b-12d3-a456-426614174000",
      "event_summary": "Dak Prescott injury update...",
      "sample_size": 42,
      "target_date": "2025-12-15T18:00:00Z",
      "horizon_minutes": 7560
    }
  ]
}
```

#### Get Event Impact

Analyze how a specific event affected forecasts:

```bash
GET /nfl/events/{event_id}/impact?symbol=NFL:DAL_COWBOYS
```

**Response:**
```json
{
  "event_id": "123e4567-e89b-12d3-a456-426614174000",
  "event_title": "Dak Prescott injury update",
  "event_timestamp": "2025-12-10T14:23:00Z",
  "symbol": "NFL:DAL_COWBOYS",
  "forecast_before": 0.52,
  "forecast_after": 0.58,
  "forecast_change": 0.06,
  "similar_events_count": 42,
  "historical_impact_avg": 0.05,
  "next_game_date": "2025-12-15T18:00:00Z",
  "days_until_game": 5.3
}
```

## Configuration

All settings in `backend/config.py`:

```python
# Backfill time window (in days)
FORECAST_BACKFILL_DAYS = 60

# Daily baseline snapshots
FORECAST_DAILY_SNAPSHOT_ENABLED = True
FORECAST_DAILY_SNAPSHOT_HOUR = 12  # UTC hour

# Batch insert size
FORECAST_BACKFILL_BATCH_SIZE = 100

# Forecast types to compute
FORECAST_TYPES_ENABLED = ["ml_model_v2", "event_weighted", "baseline"]

# NFL-specific settings
NFL_FORECAST_BACKFILL_DAYS = 60
NFL_FORECAST_MIN_EVENT_AGE_HOURS = 1  # Skip very recent events
NFL_FORECAST_MAX_EVENTS_PER_DAY = 50  # Limit processing
```

Override via environment variables:

```bash
export FORECAST_BACKFILL_DAYS=90
export FORECAST_TYPES_ENABLED=event_weighted,baseline
```

## Forecast Types

### 1. Event-Weighted (`event_weighted`)

- **Source**: Semantic similarity to historical events
- **Triggered by**: News events mentioning team
- **Features**: Event embeddings, similar game outcomes
- **Accuracy**: 40-50% better than baseline with Weaviate vector search
- **Model Version**: v1.0

### 2. ML Model (`ml_model_v2`)

- **Source**: Trained logistic regression classifier
- **Features**: Win %, point differential, streaks, home/away, etc.
- **Accuracy**: 58.8% test accuracy (850 games, 4 NFC East teams)
- **Model Version**: v2.0
- **Training**: Per-symbol split, L2 regularization

### 3. Naive Baseline (`naive_baseline`)

- **Source**: Historical win rate (90-day lookback)
- **Features**: Simple moving average of outcomes
- **Purpose**: Baseline for model comparison
- **Model Version**: v1.0

## Temporal Correctness

**CRITICAL**: All forecast computations enforce strict temporal ordering to prevent lookahead bias.

### Enforcement Points

1. **Event Selection**: `WHERE e.timestamp < snapshot_at`
2. **Game Outcomes**: `WHERE g.game_date < snapshot_at`
3. **Feature Computation**: `as_of=snapshot_at` parameter
4. **ML Training**: Per-symbol time-based train/test split

### Validation

The backfill script validates timezone-aware datetimes:

```python
if reference_time.tzinfo is None:
    raise ValueError("reference_time must be timezone-aware UTC")
```

All timestamps are UTC with explicit timezone (`datetime.now(tz=timezone.utc)`).

## Frontend Visualization

### Timeline Chart

Display forecast evolution over time with event markers:

```typescript
interface ForecastSnapshot {
  timestamp: string;
  forecast_value: number;
  confidence: number;
  model_source: string;
  event_id?: string;
  event_summary?: string;
}

// Fetch timeline
const response = await fetch(
  `/nfl/teams/NFL:DAL_COWBOYS/forecast-timeline?days=30`
);
const timeline: ForecastTimelineOut = await response.json();

// Render chart with Recharts
<LineChart data={timeline.snapshots}>
  <Line dataKey="forecast_value" stroke="#8884d8" />
  <Scatter data={eventSnapshots} fill="#ff0000" />
</LineChart>
```

### Event Impact Cards

Show before/after forecast comparison:

```typescript
const impact = await fetch(
  `/nfl/events/${eventId}/impact?symbol=NFL:DAL_COWBOYS`
).then(r => r.json());

// Render impact
<div>
  <p>Before: {impact.forecast_before * 100}%</p>
  <p>After: {impact.forecast_after * 100}%</p>
  <p>Change: {impact.forecast_change > 0 ? '↑' : '↓'} {Math.abs(impact.forecast_change * 100)}%</p>
</div>
```

## Monitoring & Maintenance

### Health Checks

Verify snapshot generation:

```sql
-- Count snapshots by team (last 7 days)
SELECT
    symbol,
    COUNT(*) as snapshot_count,
    COUNT(DISTINCT event_id) as unique_events,
    MIN(snapshot_at) as first_snapshot,
    MAX(snapshot_at) as last_snapshot
FROM forecast_snapshots
WHERE snapshot_at > NOW() - INTERVAL '7 days'
GROUP BY symbol
ORDER BY symbol;

-- Check model source distribution
SELECT
    model_source,
    COUNT(*) as count,
    AVG(forecast_value) as avg_value,
    AVG(confidence) as avg_confidence
FROM forecast_snapshots
WHERE snapshot_at > NOW() - INTERVAL '7 days'
GROUP BY model_source;
```

### Performance

Query optimization with indexes:

```sql
-- Timeline query (uses idx_forecast_snapshots_timeline)
EXPLAIN ANALYZE
SELECT *
FROM forecast_snapshots
WHERE symbol = 'NFL:DAL_COWBOYS'
  AND forecast_type = 'win_probability'
  AND snapshot_at BETWEEN '2025-11-11' AND '2025-12-11'
ORDER BY snapshot_at DESC;
```

### Backfill Statistics

The backfill script outputs detailed stats:

```
[backfill_forecasts] Starting backfill for NFL:DAL_COWBOYS
[backfill_forecasts] Window: 2025-10-12 to 2025-12-11
[backfill_forecasts] Forecast types: ['event_weighted', 'baseline']
[backfill_forecasts] Found 127 relevant events
[backfill_forecasts] Computed 42 event snapshots
[backfill_forecasts] Computed 60 daily snapshots
[backfill_forecasts] Total snapshots computed: 102
[backfill_forecasts] Batch 1: 100 inserted, 0 skipped
[backfill_forecasts] Batch 2: 2 inserted, 0 skipped
[backfill_forecasts] ✓ Completed backfill for NFL:DAL_COWBOYS
```

## Troubleshooting

### Issue: No snapshots generated

**Cause**: No events found in backfill window or no games scheduled

**Solution**:
1. Check events table: `SELECT COUNT(*) FROM events WHERE 'sports' = ANY(categories)`
2. Check team pattern: `SELECT * FROM events WHERE title ~* '(Cowboys|Dallas|DAL)' LIMIT 5`
3. Verify games exist: `SELECT * FROM asset_returns WHERE symbol = 'NFL:DAL_COWBOYS' ORDER BY as_of DESC LIMIT 5`

### Issue: Timezone errors

**Cause**: Naive datetimes passed to forecast functions

**Solution**: Always use timezone-aware UTC datetimes:

```python
from datetime import datetime, timezone

# CORRECT
as_of = datetime.now(tz=timezone.utc)

# WRONG
as_of = datetime.now()  # Raises ValueError
```

### Issue: Duplicate key violations

**Cause**: Re-running backfill with same parameters

**Solution**: Duplicates are automatically skipped via `ON CONFLICT DO NOTHING`. Check `snapshots_skipped` count in output.

### Issue: Slow backfill performance

**Optimization**:
1. Reduce `NFL_FORECAST_MAX_EVENTS_PER_DAY` config
2. Use `--days 7` for smaller window
3. Specify `--symbol` for single team testing
4. Enable embedding cache (auto-enabled, check `backend/.cache/`)

## Future Enhancements

### Planned Features

1. **ML Model Snapshots**: Store `ml_model_v2` predictions in snapshots
2. **Automated Backfill**: Daily cron job to keep snapshots current
3. **Snapshot Cleanup**: Archive old snapshots (>365 days)
4. **Confidence Intervals**: Store prediction intervals in metadata
5. **Multi-Metric**: Support point spread, total points forecasts
6. **Frontend Dashboard**: Timeline chart with event annotations

### Schema Extensions

Future columns (backward-compatible):

```sql
ALTER TABLE forecast_snapshots ADD COLUMN IF NOT EXISTS
    prediction_interval_lower DOUBLE PRECISION;
ALTER TABLE forecast_snapshots ADD COLUMN IF NOT EXISTS
    prediction_interval_upper DOUBLE PRECISION;
ALTER TABLE forecast_snapshots ADD COLUMN IF NOT EXISTS
    actual_outcome DOUBLE PRECISION;  -- For backtesting
```

## Related Documentation

- **Main README**: `/backend/CLAUDE.md` - Project overview
- **NFL Setup**: `/backend/NFL_DATA_SETUP.md` - NFL data pipeline
- **Database Schema**: `/db/init.sql` - Full schema
- **API Docs**: Interactive at `http://localhost:9000/docs` when server running

## Support

For issues or questions:
1. Check this documentation first
2. Review `backend/CLAUDE.md` for coding rules
3. Run with `--dry-run` flag for testing
4. Enable debug logging: `print()` statements throughout backfill script
