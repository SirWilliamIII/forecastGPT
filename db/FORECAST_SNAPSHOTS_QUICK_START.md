# Forecast Snapshots - Quick Start Guide

## What is it?

The `forecast_snapshots` table stores historical forecast values over time to power timeline graphs showing how predictions evolve as events occur.

**Example:** Show how Cowboys win probability changed from 65% → 52% (after QB injury) → 61% (latest).

## Schema Overview

```
forecast_snapshots
├─ id (PK)
├─ symbol                 'NFL:DAL_COWBOYS', 'BTC-USD'
├─ forecast_type          'win_probability', 'price_return'
├─ snapshot_at            When forecast was made (UTC)
├─ forecast_value         0.65 (65% win prob), 0.035 (3.5% return)
├─ confidence             0.75 (75% confident)
├─ sample_size            42 (similar games used)
├─ model_source           'ml_model_v2', 'baker_api'
├─ model_version          'v2.0', 'v2.1'
├─ event_id (FK)          → events.id (what triggered this?)
├─ event_summary          'QB injury report'
├─ target_date            When predicted event occurs
├─ horizon_minutes        Minutes until target
├─ metadata (JSONB)       Model config, features used
└─ created_at             Row insert time
```

## Quick Examples

### Insert a Forecast Snapshot

```python
from datetime import datetime, timezone
from db import get_conn

def save_forecast_snapshot(
    symbol: str,
    forecast_type: str,
    forecast_value: float,
    model_source: str,
    model_version: str = None,
    confidence: float = None,
    sample_size: int = None,
    event_id: str = None,
    event_summary: str = None,
    target_date: datetime = None,
    horizon_minutes: int = None,
    metadata: dict = None
):
    """Save a forecast snapshot to the database."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO forecast_snapshots (
                    symbol, forecast_type, snapshot_at, forecast_value,
                    confidence, sample_size, model_source, model_version,
                    event_id, event_summary, target_date, horizon_minutes,
                    metadata
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol, forecast_type, model_source, snapshot_at)
                DO UPDATE SET
                    forecast_value = EXCLUDED.forecast_value,
                    confidence = EXCLUDED.confidence,
                    sample_size = EXCLUDED.sample_size
                RETURNING id;
            """, (
                symbol,
                forecast_type,
                datetime.now(tz=timezone.utc),  # snapshot_at
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
            ))
            return cur.fetchone()[0]

# Example usage
snapshot_id = save_forecast_snapshot(
    symbol='NFL:DAL_COWBOYS',
    forecast_type='win_probability',
    forecast_value=0.65,
    model_source='ml_model_v2',
    model_version='v2.0',
    confidence=0.75,
    sample_size=42,
    target_date=datetime(2025, 12, 15, 13, 0, tzinfo=timezone.utc),
    horizon_minutes=10080,  # 7 days
    metadata={'features': ['win_pct', 'point_diff'], 'rmse': 0.12}
)
```

### Get Forecast Timeline

```python
def get_forecast_timeline(
    symbol: str,
    forecast_type: str,
    days_back: int = 7,
    model_source: str = None
):
    """Get forecast evolution over time."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            query = """
                SELECT
                    snapshot_at,
                    forecast_value,
                    confidence,
                    sample_size,
                    model_source,
                    event_summary
                FROM forecast_snapshots
                WHERE symbol = %s
                  AND forecast_type = %s
                  AND snapshot_at >= NOW() - INTERVAL '%s days'
            """
            params = [symbol, forecast_type, days_back]

            if model_source:
                query += " AND model_source = %s"
                params.append(model_source)

            query += " ORDER BY snapshot_at"

            cur.execute(query, params)
            return cur.fetchall()

# Example usage
timeline = get_forecast_timeline(
    symbol='NFL:DAL_COWBOYS',
    forecast_type='win_probability',
    days_back=7,
    model_source='ml_model_v2'
)

for snapshot in timeline:
    print(f"{snapshot[0]}: {snapshot[1]:.1%} win prob (confidence: {snapshot[2]:.1%})")
```

### Compare Multiple Models

```python
def compare_models(symbol: str, forecast_type: str):
    """Get latest forecast from each model source."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT ON (model_source)
                    model_source,
                    model_version,
                    snapshot_at,
                    forecast_value,
                    confidence
                FROM forecast_snapshots
                WHERE symbol = %s AND forecast_type = %s
                ORDER BY model_source, snapshot_at DESC
            """, (symbol, forecast_type))
            return cur.fetchall()

# Example usage
models = compare_models('NFL:DAL_COWBOYS', 'win_probability')
for model in models:
    print(f"{model[0]} v{model[1]}: {model[3]:.1%} (confidence: {model[4]:.1%})")
```

### Event Impact Analysis

```python
def analyze_event_impact(event_id: str, hours_window: int = 24):
    """Compare forecasts before/after an event."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                WITH event AS (
                    SELECT timestamp FROM events WHERE id = %s
                )
                SELECT
                    CASE WHEN fs.snapshot_at < e.timestamp THEN 'before'
                         ELSE 'after' END AS period,
                    fs.symbol,
                    AVG(fs.forecast_value) AS avg_forecast,
                    STDDEV(fs.forecast_value) AS volatility,
                    COUNT(*) AS snapshot_count
                FROM forecast_snapshots fs
                CROSS JOIN event e
                WHERE fs.snapshot_at BETWEEN
                      e.timestamp - INTERVAL '%s hours' AND
                      e.timestamp + INTERVAL '%s hours'
                GROUP BY period, fs.symbol
            """, (event_id, hours_window, hours_window))
            return cur.fetchall()

# Example usage
impact = analyze_event_impact('a7b8c9d0-1234-5678-9abc-def012345678')
for row in impact:
    print(f"{row[0]} event: {row[1]} forecast avg={row[2]:.1%}, volatility={row[3]:.3f}")
```

## Common Queries (SQL)

### Timeline for Next Game
```sql
SELECT
    snapshot_at,
    forecast_value,
    confidence,
    model_source,
    event_summary
FROM forecast_snapshots
WHERE symbol = 'NFL:DAL_COWBOYS'
  AND forecast_type = 'win_probability'
  AND target_date = '2025-12-15 13:00:00+00'
ORDER BY snapshot_at;
```

### Latest Snapshot Per Model
```sql
SELECT DISTINCT ON (model_source)
    model_source,
    forecast_value,
    confidence,
    snapshot_at
FROM forecast_snapshots
WHERE symbol = 'NFL:DAL_COWBOYS'
  AND forecast_type = 'win_probability'
ORDER BY model_source, snapshot_at DESC;
```

### Forecast Change Over Time
```sql
SELECT
    snapshot_at,
    forecast_value,
    forecast_value - LAG(forecast_value) OVER (ORDER BY snapshot_at) AS change,
    event_summary
FROM forecast_snapshots
WHERE symbol = 'NFL:DAL_COWBOYS'
  AND forecast_type = 'win_probability'
  AND model_source = 'ml_model_v2'
ORDER BY snapshot_at;
```

### High-Quality Forecasts Only
```sql
SELECT *
FROM forecast_snapshots
WHERE symbol = 'NFL:DAL_COWBOYS'
  AND forecast_type = 'win_probability'
  AND sample_size >= 20  -- At least 20 similar events
  AND confidence >= 0.6   -- At least 60% confident
ORDER BY snapshot_at DESC;
```

### Upcoming Games
```sql
SELECT
    symbol,
    target_date,
    forecast_value,
    model_source,
    snapshot_at
FROM forecast_snapshots
WHERE target_date BETWEEN NOW() AND NOW() + INTERVAL '7 days'
  AND forecast_type = 'win_probability'
ORDER BY target_date, symbol;
```

## Frontend Integration

### Timeline Graph Component

```typescript
// TypeScript types
interface ForecastSnapshot {
  snapshot_at: string;
  forecast_value: number;
  confidence?: number;
  model_source: string;
  event_summary?: string;
  sample_size?: number;
}

// Fetch timeline data
async function fetchForecastTimeline(
  symbol: string,
  forecastType: string,
  daysBack: number = 7
): Promise<ForecastSnapshot[]> {
  const response = await fetch(
    `/api/forecast-timeline?symbol=${symbol}&type=${forecastType}&days=${daysBack}`
  );
  return response.json();
}

// Recharts timeline visualization
import { LineChart, Line, XAxis, YAxis, Tooltip } from 'recharts';

function ForecastTimeline({ symbol }: { symbol: string }) {
  const [data, setData] = useState<ForecastSnapshot[]>([]);

  useEffect(() => {
    fetchForecastTimeline(symbol, 'win_probability').then(setData);
  }, [symbol]);

  return (
    <LineChart width={800} height={400} data={data}>
      <XAxis dataKey="snapshot_at" />
      <YAxis domain={[0, 1]} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
      <Tooltip
        formatter={(value: number) => `${(value * 100).toFixed(1)}%`}
        labelFormatter={(label) => new Date(label).toLocaleString()}
      />
      <Line
        type="monotone"
        dataKey="forecast_value"
        stroke="#8884d8"
        strokeWidth={2}
      />
    </LineChart>
  );
}
```

## API Endpoint Example

```python
from fastapi import APIRouter, Query
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from pydantic import BaseModel

router = APIRouter()

class ForecastSnapshotResponse(BaseModel):
    snapshot_at: datetime
    forecast_value: float
    confidence: Optional[float]
    sample_size: Optional[int]
    model_source: str
    model_version: Optional[str]
    event_summary: Optional[str]

@router.get("/forecast-timeline", response_model=List[ForecastSnapshotResponse])
def get_forecast_timeline(
    symbol: str = Query(..., min_length=1, max_length=50),
    forecast_type: str = Query('win_probability', max_length=50),
    days_back: int = Query(7, ge=1, le=90),
    model_source: Optional[str] = Query(None, max_length=50)
):
    """Get forecast timeline for a symbol."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            query = """
                SELECT
                    snapshot_at,
                    forecast_value,
                    confidence,
                    sample_size,
                    model_source,
                    model_version,
                    event_summary
                FROM forecast_snapshots
                WHERE symbol = %s
                  AND forecast_type = %s
                  AND snapshot_at >= %s
            """
            params = [
                symbol,
                forecast_type,
                datetime.now(tz=timezone.utc) - timedelta(days=days_back)
            ]

            if model_source:
                query += " AND model_source = %s"
                params.append(model_source)

            query += " ORDER BY snapshot_at"

            cur.execute(query, params)
            rows = cur.fetchall()

            return [
                ForecastSnapshotResponse(
                    snapshot_at=row[0],
                    forecast_value=row[1],
                    confidence=row[2],
                    sample_size=row[3],
                    model_source=row[4],
                    model_version=row[5],
                    event_summary=row[6]
                )
                for row in rows
            ]
```

## Best Practices

1. **Always use UTC timezone-aware datetimes:**
   ```python
   from datetime import datetime, timezone
   snapshot_at = datetime.now(tz=timezone.utc)  # CORRECT
   ```

2. **Use ON CONFLICT for idempotent inserts:**
   ```sql
   INSERT INTO forecast_snapshots (...)
   VALUES (...)
   ON CONFLICT (symbol, forecast_type, model_source, snapshot_at)
   DO UPDATE SET forecast_value = EXCLUDED.forecast_value;
   ```

3. **Include confidence and sample_size for UI filtering:**
   ```python
   # Frontend can warn users on low-quality forecasts
   if snapshot.sample_size < 20 or snapshot.confidence < 0.6:
       show_warning("Low confidence forecast")
   ```

4. **Denormalize event_summary for performance:**
   ```python
   # Store brief summary instead of JOINing events table
   event_summary = event.title[:100]  # First 100 chars
   ```

5. **Batch insert for backfills:**
   ```python
   # Much faster than individual inserts
   cur.executemany(
       "INSERT INTO forecast_snapshots (...) VALUES (%s, %s, ...)",
       snapshot_data_list
   )
   ```

6. **Version your models and features:**
   ```python
   metadata = {
       'model_version': 'v2.0',
       'feature_version': 'v1.0',
       'features_used': ['win_pct', 'point_diff'],
       'training_date': '2025-12-01',
       'rmse': 0.12
   }
   ```

## Testing

```python
import pytest
from datetime import datetime, timezone

def test_insert_snapshot():
    """Test basic snapshot insertion."""
    snapshot_id = save_forecast_snapshot(
        symbol='TEST_SYMBOL',
        forecast_type='test_type',
        forecast_value=0.5,
        model_source='test_model',
        confidence=0.8,
        sample_size=10
    )
    assert snapshot_id is not None

def test_duplicate_handling():
    """Test ON CONFLICT behavior."""
    snapshot_at = datetime.now(tz=timezone.utc)

    # First insert
    save_forecast_snapshot(
        symbol='TEST',
        forecast_type='test',
        forecast_value=0.5,
        model_source='test'
    )

    # Duplicate should update, not error
    save_forecast_snapshot(
        symbol='TEST',
        forecast_type='test',
        forecast_value=0.6,  # Updated value
        model_source='test'
    )

def test_timeline_query():
    """Test timeline query performance."""
    timeline = get_forecast_timeline(
        symbol='NFL:DAL_COWBOYS',
        forecast_type='win_probability',
        days_back=7
    )
    assert len(timeline) > 0
    assert timeline[0][1] >= 0 and timeline[0][1] <= 1  # Valid probability
```

## Troubleshooting

### Problem: Duplicate key violation
```
ERROR: duplicate key value violates unique constraint "forecast_snapshots_unique"
```
**Solution:** Use `ON CONFLICT DO UPDATE` or check for existing snapshot first.

### Problem: Slow timeline queries
**Solution:** Ensure `idx_forecast_snapshots_timeline` index exists:
```sql
CREATE INDEX IF NOT EXISTS idx_forecast_snapshots_timeline
ON forecast_snapshots (symbol, forecast_type, snapshot_at DESC);
```

### Problem: Naive datetime error
```
ValueError: Datetime must be timezone-aware
```
**Solution:** Always use `timezone.utc`:
```python
from datetime import timezone
dt = datetime.now(tz=timezone.utc)  # CORRECT
```

## Next Steps

1. **See full schema documentation:** `/db/FORECAST_SNAPSHOTS_SCHEMA.md`
2. **Apply migration:** `/db/migrations/002_forecast_snapshots.sql`
3. **Review example queries:** See "Common Queries" section above
4. **Build timeline API:** See "API Endpoint Example" section
5. **Create frontend component:** See "Frontend Integration" section

## Questions?

- Full schema: `/db/FORECAST_SNAPSHOTS_SCHEMA.md`
- Migration guide: `/db/migrations/README.md`
- Project docs: `/CLAUDE.md`
