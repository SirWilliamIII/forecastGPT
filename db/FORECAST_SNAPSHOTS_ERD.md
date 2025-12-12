# Forecast Snapshots - Entity Relationship Diagram

## Table Relationships

```
┌─────────────────────────────────────────────────────────────────┐
│                          events                                  │
├─────────────────────────────────────────────────────────────────┤
│ PK  id (UUID)                                                   │
│     timestamp (TIMESTAMPTZ)                                     │
│     title (TEXT)                                                │
│     summary (TEXT)                                              │
│     source (TEXT)                                               │
│     url (TEXT) UNIQUE                                           │
│     embed (VECTOR 3072)                                         │
│     categories (TEXT[])                                         │
│     tags (TEXT[])                                               │
│     meta (JSONB)                                                │
└─────────────────────────────────────────────────────────────────┘
                            │
                            │ 1
                            │
                            │ referenced by (ON DELETE SET NULL)
                            │
                            │ 0..*
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    forecast_snapshots                            │
├─────────────────────────────────────────────────────────────────┤
│ PK  id (SERIAL)                                                 │
│                                                                  │
│     -- What is being forecasted                                 │
│     symbol (VARCHAR 50) NOT NULL                                │
│     forecast_type (VARCHAR 50) NOT NULL                         │
│                                                                  │
│     -- When                                                      │
│     snapshot_at (TIMESTAMPTZ) NOT NULL                          │
│     target_date (TIMESTAMPTZ)                                   │
│     horizon_minutes (INTEGER)                                   │
│                                                                  │
│     -- Forecast value                                            │
│     forecast_value (DOUBLE PRECISION) NOT NULL                  │
│     confidence (DOUBLE PRECISION)                               │
│     sample_size (INTEGER)                                       │
│                                                                  │
│     -- Model attribution                                         │
│     model_source (VARCHAR 50) NOT NULL                          │
│     model_version (VARCHAR 20)                                  │
│     metadata (JSONB)                                            │
│                                                                  │
│     -- Event attribution (optional)                             │
│ FK  event_id (UUID) → events.id                                 │
│     event_summary (TEXT)                                        │
│                                                                  │
│     created_at (TIMESTAMPTZ) NOT NULL DEFAULT NOW()             │
│                                                                  │
│ UK  UNIQUE(symbol, forecast_type, model_source, snapshot_at)   │
└─────────────────────────────────────────────────────────────────┘
                            │
                            │
                            │ compared with actual outcomes
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                      asset_returns                               │
├─────────────────────────────────────────────────────────────────┤
│ PK  (symbol, as_of, horizon_minutes)                            │
│     symbol (TEXT) NOT NULL                                      │
│     as_of (TIMESTAMPTZ) NOT NULL                                │
│     horizon_minutes (INT) NOT NULL                              │
│     realized_return (DOUBLE PRECISION) NOT NULL                 │
│     price_start (DOUBLE PRECISION) NOT NULL                     │
│     price_end (DOUBLE PRECISION) NOT NULL                       │
└─────────────────────────────────────────────────────────────────┘
                            │
                            │ (optional integration)
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                        projections                               │
├─────────────────────────────────────────────────────────────────┤
│ PK  (symbol, as_of, horizon_minutes, metric, model_source)     │
│     symbol (TEXT) NOT NULL                                      │
│     as_of (TIMESTAMPTZ) NOT NULL                                │
│     horizon_minutes (INT) NOT NULL                              │
│     metric (TEXT) NOT NULL                                      │
│     projected_value (DOUBLE PRECISION) NOT NULL                 │
│     model_source (TEXT) NOT NULL                                │
│     game_id (INT)                                               │
│     opponent (TEXT)                                             │
│     meta (JSONB)                                                │
└─────────────────────────────────────────────────────────────────┘
```

## Relationship Details

### forecast_snapshots → events (Many-to-One, Optional)

**Relationship Type:** Many-to-One (0..* to 1)

**Foreign Key:** `forecast_snapshots.event_id → events.id`

**Cascade Rule:** `ON DELETE SET NULL`

**Meaning:**
- Multiple forecast snapshots can be triggered by a single event
- Event attribution is optional (not all snapshots are event-driven)
- If event is deleted, snapshots remain but lose event link

**Example:**
```
Event: "Dak Prescott injury report" (id: abc-123)
  ├─ Snapshot 1: Cowboys 52% (ml_model_v2)
  ├─ Snapshot 2: Cowboys 51% (baker_api)
  └─ Snapshot 3: Cowboys 50% (event_weighted)
```

### forecast_snapshots ↔ asset_returns (Comparison)

**Relationship Type:** Logical comparison (no foreign key)

**Join Pattern:** Symbol + temporal proximity

**Purpose:** Backtesting - compare predictions vs actual outcomes

**Example Query:**
```sql
-- Compare forecasts vs reality
SELECT
    fs.snapshot_at,
    fs.forecast_value AS predicted_win_prob,
    CASE WHEN ar.realized_return > 0 THEN 1.0 ELSE 0.0 END AS actual_win,
    ABS(fs.forecast_value -
        CASE WHEN ar.realized_return > 0 THEN 1.0 ELSE 0.0 END) AS error
FROM forecast_snapshots fs
JOIN asset_returns ar
  ON fs.symbol = ar.symbol
  AND fs.target_date = ar.as_of
WHERE fs.forecast_type = 'win_probability';
```

### forecast_snapshots ↔ projections (Data Migration)

**Relationship Type:** One-way import (projections → snapshots)

**Purpose:** Import external forecasts into snapshot history

**Example:**
```sql
-- Import Baker API projections as snapshots
INSERT INTO forecast_snapshots (
    symbol, forecast_type, snapshot_at, forecast_value,
    model_source, target_date, horizon_minutes
)
SELECT
    symbol,
    'win_probability',
    as_of,
    projected_value,
    model_source,
    as_of + (horizon_minutes || ' minutes')::INTERVAL,
    horizon_minutes
FROM projections
WHERE metric = 'win_prob';
```

## Data Flow Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                       Data Sources                                │
└──────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
    [RSS Feeds]        [SportsData.io]      [Game Results]
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│   events    │      │ projections │      │asset_returns│
│  (semantic) │      │  (external) │      │  (outcomes) │
└─────────────┘      └─────────────┘      └─────────────┘
         │                    │                    │
         │                    │                    │
         ▼                    ▼                    ▼
┌──────────────────────────────────────────────────────────────────┐
│                      ML Forecasting Models                        │
│                                                                   │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐    │
│  │  ml_model_v2   │  │   baker_api    │  │ event_weighted │    │
│  │   (internal)   │  │   (external)   │  │   (internal)   │    │
│  └────────────────┘  └────────────────┘  └────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
                            │
                            ▼
                  ┌──────────────────┐
                  │Save snapshot with│
                  │ - forecast_value │
                  │ - confidence     │
                  │ - model_source   │
                  │ - event_id (opt) │
                  └──────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│                    forecast_snapshots                             │
│                   (time-series storage)                           │
└──────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│                       API Endpoints                               │
│                                                                   │
│  GET /forecast-timeline?symbol=NFL:DAL_COWBOYS&days=7            │
│  GET /forecast-compare?symbol=NFL:DAL_COWBOYS                    │
│  GET /forecast-impact?event_id=<uuid>                            │
└──────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Frontend Dashboard                             │
│                                                                   │
│  [Timeline Graph] [Event Annotations] [Model Comparison]         │
└──────────────────────────────────────────────────────────────────┘
```

## Index Visualization

```
forecast_snapshots table
├─ PRIMARY KEY: id (auto-increment)
├─ UNIQUE: (symbol, forecast_type, model_source, snapshot_at)
│
└─ Indexes:
   │
   ├─ idx_forecast_snapshots_timeline
   │  ├─ Columns: (symbol, forecast_type, snapshot_at DESC)
   │  └─ Use case: Timeline graphs (most common query)
   │
   ├─ idx_forecast_snapshots_compare
   │  ├─ Columns: (symbol, snapshot_at DESC, model_source)
   │  └─ Use case: A/B testing, model comparison
   │
   ├─ idx_forecast_snapshots_event
   │  ├─ Columns: (event_id) WHERE event_id IS NOT NULL
   │  └─ Use case: Event impact analysis
   │
   ├─ idx_forecast_snapshots_recent
   │  ├─ Columns: (snapshot_at DESC)
   │  └─ Use case: Dashboard recent activity
   │
   ├─ idx_forecast_snapshots_target
   │  ├─ Columns: (target_date) WHERE target_date IS NOT NULL
   │  └─ Use case: Upcoming games/events
   │
   ├─ idx_forecast_snapshots_model
   │  ├─ Columns: (model_source, model_version) WHERE model_version IS NOT NULL
   │  └─ Use case: Model performance tracking
   │
   └─ idx_forecast_snapshots_metadata
      ├─ Type: GIN index on JSONB
      └─ Use case: Feature version queries
```

## Timeline Example (Visual)

```
Cowboys next game: December 15, 2025 @ 1:00 PM EST
Forecast type: win_probability
Models tracking: ml_model_v2, baker_api, event_weighted

┌─────────────────────────────────────────────────────────────────┐
│                    Forecast Timeline                             │
└─────────────────────────────────────────────────────────────────┘

Dec 4, 10:00 AM                        Dec 15, 1:00 PM
    │                                        │ (Game Time)
    │                                        │
    │  Baseline: 65% win prob                │
    │  (no events yet)                       │
    │                                        │
    ├──────────────────────────────────────►│
    │                                        │
Dec 8, 2:00 PM                              │
    │  ⚠️ EVENT: QB injury                   │
    │  Forecast drops: 52% (-13%)           │
    │  (low confidence)                      │
    │                                        │
    ├──────────────────────────────────────►│
    │                                        │
Dec 10, 10:00 AM                            │
    │  ℹ️ EVENT: Backup QB practice          │
    │  Forecast recovers: 58% (+6%)         │
    │  (medium confidence)                   │
    │                                        │
    ├──────────────────────────────────────►│
    │                                        │
Dec 11, 8:00 AM                             │
    │  Updated stats: 61% (+3%)             │
    │  (high confidence)                     │
    │                                        │
    └──────────────────────────────────────►│
                                             │
                                        Game starts
                                        Actual outcome: WIN
                                        Realized return: +1.0

Database rows created:
├─ Row 1: Dec 4, 10:00 | 0.65 | ml_model_v2 | NULL event
├─ Row 2: Dec 8, 14:00 | 0.52 | ml_model_v2 | event_id: abc-123
├─ Row 3: Dec 10, 10:00 | 0.58 | ml_model_v2 | event_id: def-456
└─ Row 4: Dec 11, 08:00 | 0.61 | ml_model_v2 | NULL event
```

## Model Comparison Example

```
Timestamp: December 11, 2025 @ 8:00 AM
Symbol: NFL:DAL_COWBOYS
Forecast type: win_probability

┌────────────────┬─────────────┬────────────┬─────────────┬────────────┐
│ model_source   │ version     │ forecast   │ confidence  │ sample_size│
├────────────────┼─────────────┼────────────┼─────────────┼────────────┤
│ ml_model_v2    │ v2.0        │    0.61    │    0.78     │     50     │
│ baker_api      │ NULL        │    0.59    │    NULL     │    NULL    │
│ event_weighted │ v1.3        │    0.63    │    0.70     │     42     │
└────────────────┴─────────────┴────────────┴─────────────┴────────────┘

Ensemble forecast (confidence-weighted):
(0.61 × 0.78 + 0.63 × 0.70) / (0.78 + 0.70) = 0.619 = 62% win probability

Database rows:
├─ Row 1: snapshot_at=08:00 | model_source=ml_model_v2 | value=0.61
├─ Row 2: snapshot_at=08:00 | model_source=baker_api | value=0.59
└─ Row 3: snapshot_at=08:00 | model_source=event_weighted | value=0.63

UNIQUE constraint allows all three (different model_source):
(symbol='NFL:DAL_COWBOYS', forecast_type='win_probability',
 model_source=*, snapshot_at='2025-12-11 08:00:00+00')
```

## Event Attribution Example

```
┌─────────────────────────────────────────────────────────────────┐
│                         events table                             │
├─────────────────────────────────────────────────────────────────┤
│ id: abc-123-def-456                                             │
│ timestamp: 2025-12-08 14:00:00+00                               │
│ title: "Dak Prescott ankle injury - questionable for Sunday"   │
│ source: "ESPN Injury Report"                                    │
│ categories: ['sports', 'injury', 'nfl']                         │
└─────────────────────────────────────────────────────────────────┘
                            │
                            │ triggers multiple forecast updates
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
        ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│  ml_model_v2    │ │   baker_api     │ │ event_weighted  │
│  generates      │ │   generates     │ │  generates      │
│  forecast       │ │   forecast      │ │  forecast       │
└─────────────────┘ └─────────────────┘ └─────────────────┘
        │                   │                   │
        │                   │                   │
        ▼                   ▼                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                    forecast_snapshots table                      │
├─────────────────────────────────────────────────────────────────┤
│ Row 1: event_id=abc-123 | model=ml_model_v2 | value=0.52       │
│ Row 2: event_id=abc-123 | model=baker_api | value=0.50         │
│ Row 3: event_id=abc-123 | model=event_weighted | value=0.48    │
└─────────────────────────────────────────────────────────────────┘

Query: "Find all forecasts triggered by this event"
SELECT * FROM forecast_snapshots WHERE event_id = 'abc-123-def-456'

Result: 3 snapshots, avg forecast drop of -14% from baseline
```

## Cardinality Summary

```
events (1) ──────────► (0..*) forecast_snapshots

One event can trigger:
- 0 forecasts (event not yet processed)
- 1 forecast (single model update)
- N forecasts (all models update simultaneously)

Typical: 3-5 forecasts per event (one per active model)
```

```
forecast_snapshots (*..) ──────────► (1) events

Many snapshots can reference:
- 0 events (scheduled/manual forecasts)
- 1 event (event-driven forecasts)

Typical: 60% event-driven, 40% scheduled
```

## Query Path Visualization

### Timeline Query
```
User: "Show me Cowboys win probability over last 7 days"
  │
  ▼
Frontend: GET /forecast-timeline?symbol=NFL:DAL_COWBOYS&days=7
  │
  ▼
Backend: SELECT * FROM forecast_snapshots
         WHERE symbol = 'NFL:DAL_COWBOYS'
           AND forecast_type = 'win_probability'
           AND snapshot_at >= NOW() - INTERVAL '7 days'
         ORDER BY snapshot_at
  │
  ▼
Index: idx_forecast_snapshots_timeline
       (symbol, forecast_type, snapshot_at DESC)
       ✓ Index scan (12ms)
  │
  ▼
Result: [
  {snapshot_at: Dec 4, value: 0.65},
  {snapshot_at: Dec 8, value: 0.52, event: "QB injury"},
  {snapshot_at: Dec 10, value: 0.58, event: "Practice"},
  {snapshot_at: Dec 11, value: 0.61}
]
  │
  ▼
Frontend: Render LineChart with event annotations
```

### Event Impact Query
```
User: "How did QB injury affect forecasts?"
  │
  ▼
Frontend: GET /forecast-impact?event_id=abc-123
  │
  ▼
Backend: SELECT
           CASE WHEN snapshot_at < event.timestamp THEN 'before'
                ELSE 'after' END AS period,
           AVG(forecast_value),
           COUNT(*)
         FROM forecast_snapshots
         WHERE snapshot_at BETWEEN event.timestamp - 24h
                               AND event.timestamp + 24h
         GROUP BY period
  │
  ▼
Index: idx_forecast_snapshots_event (event_id)
       + idx_forecast_snapshots_recent (snapshot_at)
       ✓ Index scan (8ms)
  │
  ▼
Result: {
  before: {avg: 0.65, count: 5},
  after: {avg: 0.51, count: 8},
  impact: -14%
}
  │
  ▼
Frontend: Render before/after comparison chart
```

## Storage Growth Projection

```
Assumptions:
- 10 symbols (NFL teams)
- 3 models per symbol (ml_model_v2, baker_api, event_weighted)
- Hourly snapshots (24/day) + event-driven (avg 10/day)
- Total: 10 symbols × 3 models × 34 snapshots/day = 1,020 snapshots/day

Year 1:
├─ Daily: 1,020 rows × 300 bytes = 306 KB/day
├─ Monthly: 306 KB × 30 = 9.18 MB/month
├─ Quarterly: 9.18 MB × 3 = 27.54 MB/quarter
└─ Annually: 9.18 MB × 12 = 110 MB/year (raw data)
   With indexes: ~200 MB/year

Year 2:
├─ 20 symbols, 5 models: 3,400 snapshots/day
└─ Storage: ~650 MB/year

Partitioning threshold: 1M rows (~300 MB)
Recommendation: Start partitioning after Month 30
```

---

**Legend:**
- PK = Primary Key
- FK = Foreign Key
- UK = Unique Constraint
- → = One-to-Many relationship
- ↔ = Many-to-Many or comparison relationship
- ▼ = Data flow direction
