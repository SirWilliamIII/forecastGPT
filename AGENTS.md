# AGENTS.md

Internal guide for future AI agents working on the **BloombergGPT Semantic Markets Backend**.

This document is authoritative for:
- How the system is structured
- Where to put new code
- How to run / test things
- Key invariants you must not break

If anything here conflicts with code or other docs, favor this file and `FORECASTER_PLAN.md` as the conceptual source of truth, then reconcile the implementation.

---

## 1. Project Overview & Architecture

### 1.1 High-level goal

This backend powers a **semantic markets forecasting system** that fuses:

- **Events (text / RSS / news)** → stored with embeddings in PostgreSQL + pgvector
- **Numeric price data (crypto markets, etc.)**
- **Forecasters** that:
  - Predict asset returns from past numeric behavior (baseline)
  - Predict returns *conditioned on specific events* using semantic similarity

The FastAPI app exposes endpoints for event ingestion, similarity search, and forecasting.

### 1.2 Main components

| Component | Location | Purpose |
|-----------|----------|---------|
| FastAPI app | `backend/app.py` | HTTP API for events, similarity search, forecasting |
| Database | `backend/db.py`, `docker-compose.yml`, `db/init.sql` | PostgreSQL 16 with pgvector |
| Embeddings | `backend/embeddings.py` | OpenAI API → 1536-dim vectors |
| Models | `backend/models/` | Forecasters (naive baseline, event-conditioned) |
| Signals | `backend/signals/` | Feature extraction (price, semantic) |
| Ingestion | `backend/ingest/` | RSS feeds, crypto returns backfill |
| Numeric utils | `backend/numeric/` | Asset return helpers |

---

## 2. Essential Commands

### 2.1 Environment & dependencies (uv)

```bash
# Install all dependencies
cd backend && uv sync

# Add a runtime dependency
uv add some-package

# Add a dev dependency
uv add --group dev pytest
```

### 2.2 Running the backend

```bash
# Option A: Full dev mode with ngrok tunnel
cd backend && ./start.sh

# Option B: Manual uvicorn
cd backend && uv run uvicorn app:app --reload --host 127.0.0.1 --port 9000
```

### 2.3 Database (Docker Compose)

```bash
# Start Postgres + Adminer
docker compose up -d db adminer

# Stop services
docker compose down

# Full reset (drops data)
docker compose down -v && docker compose up -d db
```

- **DB URL:** `postgresql://semantic:semantic@localhost:5433/semantic_markets`
- **Adminer UI:** http://localhost:8080

### 2.4 Tests

```bash
cd backend && uv run pytest
```

### 2.5 Type checking (recommended)

```bash
# If pyright/mypy is added:
cd backend && uv run pyright
```

---

## 3. Code Conventions

### 3.1 General style

- **Python 3.11+**
- Type hints everywhere
- Pydantic models for request/response payloads
- Small, focused modules per concern
- Use `fastapi.HTTPException` for API errors

### 3.2 Database access

```python
from db import get_conn

with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT ...", (params,))
        rows = cur.fetchall()
```

- Rows are `dict_row` format
- Always use parameterized queries

### 3.3 Time handling (CRITICAL)

**All times are UTC.**

```python
from datetime import datetime, timezone
as_of = datetime.now(tz=timezone.utc)
```

### 3.4 Embeddings

- Generate from `clean_text` (fallback to `raw_text`)
- Dimension: **1536**
- pgvector literal format: `"[0.1,0.2,...]"`

### 3.5 Import patterns

```python
# In app.py, import public APIs only
from models.naive_asset_forecaster import forecast_asset, ForecastResult
from models.event_return_forecaster import forecast_event_return
```

---

## 4. Database Schema

### 4.1 Tables

```sql
-- Events (semantic)
CREATE TABLE events (
    id UUID PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    source TEXT NOT NULL,
    url TEXT,
    raw_text TEXT NOT NULL,
    clean_text TEXT,
    embed VECTOR(1536),
    categories TEXT[],
    tags TEXT[]
);

-- Price history
CREATE TABLE prices (
    asset TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open NUMERIC, high NUMERIC, low NUMERIC, close NUMERIC, volume NUMERIC,
    PRIMARY KEY (asset, timestamp)
);

-- Event impacts
CREATE TABLE event_impacts (
    event_id UUID REFERENCES events(id) ON DELETE CASCADE,
    asset TEXT NOT NULL,
    delta_1d NUMERIC, delta_7d NUMERIC, delta_30d NUMERIC,
    max_drawdown NUMERIC, vol_change NUMERIC,
    PRIMARY KEY (event_id, asset)
);
```

---

## 5. Key Implementation Rules

1. **UTC everywhere** — never use naive datetimes
2. **No future data leakage** — features/labels must only use past data
3. **Embeddings from clean_text** — always 1536 dimensions
4. **Unique constraints** — respect `(symbol, as_of, horizon_minutes)` for returns
5. **Modularity** — new sources → `ingest/`, signals → `signals/`, models → `models/`
6. **Baseline first** — naive forecaster must exist; ML must beat it
7. **pgvector search** — `ORDER BY embed <-> anchor_vector`

---

## 6. Directory Structure

```
backend/
├── app.py                 # FastAPI endpoints (keep thin)
├── db.py                  # Postgres connection helper
├── embeddings.py          # OpenAI embedding utilities
├── ingest/
│   ├── rss_ingest.py      # RSS → events table
│   └── backfill_crypto_returns.py
├── numeric/
│   └── asset_returns.py   # Asset return helpers
├── signals/
│   ├── price_context.py   # Numeric price features
│   ├── context_window.py  # Event/semantic features
│   └── ...
└── models/
    ├── naive_asset_forecaster.py
    ├── event_return_forecaster.py
    └── regime_classifier.py
```

---

## 7. API Endpoints

### `POST /events`
Insert a semantic event with auto-generated embedding.

### `GET /events/{event_id}/similar?limit=10`
Find nearest neighbor events via pgvector.

### `GET /forecast/asset?symbol=BTC-USD&horizon_minutes=1440`
Baseline numeric forecaster.

### `GET /forecast/event/{event_id}?symbol=BTC-USD`
Event-conditioned forecaster using semantic similarity.

---

## 8. Environment Variables

```env
OPENAI_API_KEY=sk-...
DATABASE_URL=postgresql://semantic:semantic@localhost:5433/semantic_markets
```

---

## 9. Extending the System

| Task | Where |
|------|-------|
| New forecasting model | `models/` → new module → wire to `app.py` |
| New data source | `ingest/` → normalize to `events` schema |
| New features | `signals/` → stateless functions |
| Schema changes | `db/init.sql` + update this doc |

Consult `FORECASTER_PLAN.md` for the full architecture roadmap.
