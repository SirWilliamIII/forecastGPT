# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**BloombergGPT Semantic Markets** is a semantic-driven asset forecasting engine that fuses:
1. **Semantic Events** (text → embeddings → similarity patterns)
2. **Numeric Market Data** (returns, volatility, price context)
3. **ML Forecasting** (baseline → event-conditioned models)
4. **Frontend Dashboard** (Next.js with forecasts + event insights)

The system answers: *"Given this event/news, what does it imply for BTC/ETH/XMR returns?"*

## Development Commands

### Full Stack Development

```bash
# Start everything (database, backend, frontend)
./run-dev.sh

# Services will be available at:
# - Frontend:  http://localhost:3000
# - Backend:   http://localhost:9000
# - Database:  postgresql://semantic:semantic@localhost:5433/semantic_markets
# - Adminer:   http://localhost:8080
```

### Backend Only

```bash
cd backend

# Install dependencies (uses uv package manager)
uv sync

# Run backend server
uv run uvicorn app:app --reload --host 127.0.0.1 --port 9000

# Run tests
uv run pytest

# Add dependencies
uv add some-package           # runtime dependency
uv add --group dev pytest     # dev dependency
```

### Frontend Only

```bash
cd frontend

# Install dependencies
npm install

# Development server
npm run dev

# Production build
npm run build
npm start
```

### Database Management

```bash
# Start database (PostgreSQL 16 with pgvector)
docker compose up -d db adminer

# Stop database
docker compose down

# Full reset (WARNING: drops all data)
docker compose down -v && docker compose up -d db

# Backfill crypto price data
cd backend && uv run python -m ingest.backfill_crypto_returns

# Run RSS ingestion manually
cd backend && uv run python -m ingest.rss_ingest

# Manual ingestion will do a full fetch (skip_recent=False)
# Scheduled ingestion uses skip_recent=True for efficiency
```

### Development Mode: Disable Startup Ingestion

To speed up development server restarts, create `backend/.env`:

```bash
# backend/.env
DISABLE_STARTUP_INGESTION=true
OPENAI_API_KEY=sk-...
```

This skips automatic ingestion on startup. Manually run ingestion when needed:

```bash
cd backend && uv run python -m ingest.rss_ingest
```

### CLI Tools

```bash
cd backend

# Asset forecast
uv run python -m cli.forecast_cli asset --symbol BTC-USD --horizon 1440

# Event forecast
uv run python -m cli.forecast_cli event --event-id <UUID> --symbol BTC-USD

# List recent events
uv run python -m cli.forecast_cli events --limit 20
```

## Architecture

### Tech Stack

**Backend:**
- FastAPI (Python 3.11+)
- PostgreSQL 16 + pgvector extension
- OpenAI embeddings (text-embedding-3-large, 3072 dimensions)
- APScheduler for background jobs
- uv for dependency management

**Frontend:**
- Next.js 16 (App Router)
- React 19
- TanStack Query
- Recharts
- Tailwind CSS

### Directory Structure

```
backend/
├── app.py                        # FastAPI endpoints + scheduler
├── db.py                         # PostgreSQL connection pool
├── embeddings.py                 # OpenAI embedding utilities
├── llm/                          # LLM provider abstractions
│   ├── __init__.py
│   └── providers.py              # Claude, OpenAI, Gemini
├── ingest/
│   ├── rss_ingest.py            # RSS → events table
│   └── backfill_crypto_returns.py # yfinance → asset_returns
├── models/
│   ├── naive_asset_forecaster.py      # Baseline numeric forecaster
│   ├── event_return_forecaster.py     # Event-conditioned forecaster
│   ├── regime_classifier.py           # Market regime detection
│   └── trained/                       # Serialized ML models (.pkl)
├── signals/
│   ├── price_context.py               # Price features (returns, vol)
│   ├── context_window.py              # Event features
│   └── feature_extractor.py           # Unified feature builder
├── numeric/
│   └── asset_returns.py               # Asset return helpers
├── cli/
│   └── forecast_cli.py                # Command-line forecasting
├── notebooks/
│   └── asset_forecaster_training.py   # ML training pipeline
└── tests/
    └── test_api.py

frontend/
├── app/
│   ├── page.tsx                 # Main dashboard
│   └── events/
│       └── page.tsx             # Event feed
├── components/                  # React components
└── lib/
    └── api.ts                   # Typed API client
```

### Database Schema

**Key Tables:**
- `events` - Semantic events with pgvector embeddings (3072-dim)
- `asset_returns` - Realized returns (symbol, as_of, horizon_minutes)
- `prices` - OHLC price history
- `event_impacts` - Event impact analysis
- `feed_metadata` - Tracks last fetch time per RSS source (for optimization)

**Important:** No pgvector index on `events.embed` due to 3072 dimensions exceeding pgvector's 2000-dim limit. Uses exact search (acceptable for <100k events).

### API Endpoints

```
GET  /health                          # Health check (DB + pgvector)
POST /events                          # Insert event with embedding
GET  /events/recent                   # Recent events feed
GET  /events/{event_id}/similar       # Semantic neighbors via pgvector
GET  /forecast/asset                  # Baseline numeric forecast
GET  /forecast/event/{event_id}       # Event-conditioned forecast
GET  /analyze/event/{event_id}        # LLM analysis (sentiment, impact)
POST /analyze/sentiment               # Quick sentiment classification
```

## Critical Coding Rules

### 1. Time Handling (CRITICAL)
**All timestamps MUST be timezone-aware UTC datetimes.**

```python
from datetime import datetime, timezone

# CORRECT
as_of = datetime.now(tz=timezone.utc)

# WRONG - never use naive datetimes
as_of = datetime.now()
```

### 2. No Future Data Leakage
Features and labels must only use data from before `as_of`. This is critical for ML integrity.

```python
# When building features for time T, only use data from < T
features = build_features(symbol, as_of=T)  # looks backward only
```

### 3. Embeddings
- Generate from `clean_text` (fallback to `raw_text`)
- Dimension: **3072** (text-embedding-3-large)
- pgvector literal format: `"[0.1,0.2,...]"`
- Always from `embeddings.embed_text()`

### 4. Database Access Pattern

```python
from db import get_conn

with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT ...", (params,))
        rows = cur.fetchall()  # dict_row format
```

**Always use parameterized queries to prevent SQL injection.**

### 5. Unique Constraints
Respect `(symbol, as_of, horizon_minutes)` uniqueness in `asset_returns` table.

### 6. Modularity
- New data sources → `ingest/`
- Feature engineering → `signals/`
- Forecasting models → `models/`
- Keep `app.py` thin (routing only)

### 7. Baseline First
The naive forecaster is the baseline. ML models must beat it to be deployed.

## Background Jobs

The backend runs scheduled jobs via APScheduler (started on app startup):

- **RSS ingestion**: Hourly (sources: Wired AI, HackerNews, etc.)
- **Crypto price backfill**: Daily (symbols: BTC-USD, ETH-USD, XMR-USD)

Jobs are configured in `app.py` startup event handler.

### Performance Optimizations

The ingestion system is highly optimized to minimize API costs and runtime:

1. **Batch Duplicate Checking**: All URLs are checked against the database in a single query before processing
2. **Timestamp Filtering**: After the first run, only entries newer than the last fetch are processed
3. **Feed Metadata Tracking**: The `feed_metadata` table tracks when each source was last fetched
4. **Skip Startup Flag**: Set `DISABLE_STARTUP_INGESTION=true` in `.env` to skip ingestion during development

**Result:** First run processes all entries. Subsequent runs only check new entries and skip embedding calls for duplicates entirely.

## ML Training Pipeline

Location: `backend/notebooks/asset_forecaster_training.py`

**Training workflow:**
1. Build feature dataset with `signals/feature_extractor.py`
2. Time-based train/test split (no shuffle!)
3. Train RandomForestRegressor (baseline ML model)
4. Evaluate: MAE, RMSE, directional accuracy
5. Serialize to `backend/models/trained/asset_return_rf.pkl`

**Model metadata includes:**
- Training date
- Feature names + schema version
- Symbol list
- Train/test date ranges
- Evaluation metrics

## Environment Variables

Required in `backend/.env`:

```bash
# Required
OPENAI_API_KEY=sk-...              # Required for embeddings

# Optional - LLM providers
ANTHROPIC_API_KEY=sk-ant-...       # Optional (for LLM analysis)
GOOGLE_API_KEY=...                 # Optional (for Gemini)

# Optional - Performance
DISABLE_STARTUP_INGESTION=true     # Skip ingestion on startup (dev mode)

# Auto-configured
DATABASE_URL=postgresql://...       # Auto-set by docker-compose
```

See `backend/.env.example` for complete documentation.

## LLM Providers

The backend supports multiple LLM providers via `llm/providers.py`:

- **Claude** (default for analysis)
- **OpenAI** (GPT-4)
- **Gemini** (fast sentiment)

Provider abstraction ensures vendor-agnostic endpoints. If a provider fails, returns 503 with error message.

## Adding New Features

### New Data Source
1. Create ingestion script in `ingest/`
2. Normalize to `events` table schema
3. Add to scheduler in `app.py` if recurring

### New Forecasting Model
1. Create module in `models/`
2. Follow result schema: `{expected_return, direction, confidence, sample_size}`
3. Add endpoint in `app.py`
4. Must include fallback to baseline on errors

### New Features
1. Add stateless functions to `signals/`
2. Maintain feature schema versioning
3. Document in `signals/feature_extractor.py`
4. Ensure no lookahead bias

### Schema Changes
1. Update `db/init.sql`
2. Document in this file
3. Consider migration strategy for existing data

## Testing

```bash
cd backend && uv run pytest
```

**Test coverage:**
- API endpoint smoke tests
- Feature extraction validation
- Forecaster output schema validation

## Documentation References

For deeper understanding, consult:
- `docs/FORECASTGPT_MASTER_PLAN.md` - System architecture and phases
- `docs/ROADMAP.md` - Development roadmap and phases
- `docs/AGENTS.md` - Agent-specific coding guide

## Development Workflow

1. **Make changes** to backend/frontend code
2. **Run tests** to ensure nothing breaks
3. **Test locally** with `./run-dev.sh`
4. **Commit** with descriptive messages
5. **Push** to trigger CI/CD (when configured)

## Common Pitfalls

1. **Using naive datetimes** - Always use `datetime.now(tz=timezone.utc)`
2. **Future data leakage** - Ensure features only look backward
3. **Forgetting to sync dependencies** - Run `uv sync` after pulling changes
4. **Database schema drift** - Keep `db/init.sql` as source of truth
5. **Ignoring sample size** - Low-confidence forecasts need sample_size checks
6. **Breaking API contracts** - Never change endpoint paths or response schemas without versioning

## Project Status

**Current State:**
- ✅ Backend: FastAPI + PostgreSQL + pgvector
- ✅ Event ingestion: Wired AI RSS
- ✅ Asset returns: BTC-USD, ETH-USD, XMR-USD
- ✅ Naive forecaster: Baseline historical returns
- ✅ Event forecaster: Semantic similarity → weighted returns
- ✅ Regime classifier: Rule-based (uptrend/downtrend/chop/high_vol)
- ✅ Frontend: Next.js dashboard (MVP)
- ✅ LLM endpoints: Event analysis + sentiment
- ✅ Background scheduler: RSS hourly, crypto daily

**Next Steps:**
- ML forecaster beyond baseline (XGBoost/LightGBM)
- More RSS sources (CoinDesk, CryptoNews)
- Production deployment (Railway/Render + Vercel)
- Backtesting framework
- Model registry and A/B testing
