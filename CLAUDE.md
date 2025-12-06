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
├── config.py                     # Centralized configuration (NEW)
├── db.py                         # PostgreSQL connection pool
├── embeddings.py                 # OpenAI embedding utilities
├── llm/                          # LLM provider abstractions
│   ├── __init__.py
│   └── providers.py              # Claude, OpenAI, Gemini
├── ingest/
│   ├── rss_ingest.py            # RSS → events table (batch optimized)
│   ├── backfill_crypto_returns.py # yfinance → asset_returns
│   └── status.py                 # Ingestion status tracking (NEW)
├── models/
│   ├── naive_asset_forecaster.py      # Baseline numeric forecaster
│   ├── event_return_forecaster.py     # Event-conditioned forecaster
│   ├── regime_classifier.py           # Market regime detection
│   └── trained/                       # Serialized ML models (.pkl, .json)
├── signals/
│   ├── price_context.py               # Price features (returns, vol)
│   ├── context_window.py              # Event features
│   └── feature_extractor.py           # Unified feature builder
├── numeric/
│   └── asset_returns.py               # Asset return helpers (validated)
├── cli/
│   └── forecast_cli.py                # Command-line forecasting
├── notebooks/
│   └── asset_forecaster_training.py   # ML training pipeline (fixed lookahead)
└── tests/
    └── test_api.py

frontend/
├── app/
│   ├── page.tsx                 # Main dashboard (dynamic updates)
│   └── events/
│       └── page.tsx             # Event feed
├── components/                  # React components (dynamic selectors)
│   ├── SymbolSelector.tsx       # Dynamic symbol selection
│   └── HorizonSelector.tsx      # Dynamic horizon selection
└── lib/
    └── api.ts                   # Typed API client (discovery endpoints)
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
# Health & Discovery
GET  /health                          # Health check (DB + pgvector)
GET  /symbols/available               # Get all available symbols (NEW)
GET  /horizons/available              # Get available forecast horizons (NEW)
GET  /sources/available               # Get RSS sources with counts (NEW)

# Events
POST /events                          # Insert event with embedding
GET  /events/recent                   # Recent events feed (with domain filter)
GET  /events/{event_id}/similar       # Semantic neighbors via pgvector

# Forecasts
GET  /forecast/asset                  # Baseline numeric forecast (validated)
GET  /forecast/event/{event_id}       # Event-conditioned forecast (validated)

# Projections
GET  /projections/latest              # External projections (e.g., NFL)
GET  /projections/teams               # Available projection teams

# Analysis
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

**Validation is enforced:** All datetime-accepting functions now validate `tzinfo is not None` and raise `ValueError` if naive.

### 2. No Future Data Leakage (CRITICAL)
Features and labels must only use data from **strictly before** `as_of`. This is critical for ML integrity.

```python
# CORRECT: Use < for strict temporal ordering
WHERE e.timestamp < %s  # Events before as_of

# WRONG: Using <= allows lookahead bias
WHERE e.timestamp <= %s  # DON'T DO THIS
```

**Recent Fix:** ML training pipeline now uses `< as_of` instead of `<= as_of` to prevent lookahead bias.

### 3. Embeddings
- Generate from `clean_text` (fallback to `raw_text`)
- Dimension: **3072** (text-embedding-3-large)
- pgvector literal format: `"[0.1,0.2,...]"`
- Always from `embeddings.embed_text()`

### 4. Database Access Pattern (SQL Injection Prevention)

```python
from db import get_conn
from psycopg import sql

with get_conn() as conn:
    with conn.cursor() as cur:
        # CORRECT: Parameterized queries
        cur.execute("SELECT * FROM events WHERE id = %s", (event_id,))

        # CORRECT: Dynamic table/column names with sql.Identifier
        query = sql.SQL("INSERT INTO events ({}) VALUES ({})").format(
            sql.SQL(", ").join(sql.Identifier(col) for col in cols),
            sql.SQL(", ").join(sql.Placeholder() * len(cols)),
        )
        cur.execute(query, values)

        # WRONG: String interpolation (SQL injection risk!)
        cur.execute(f"SELECT * FROM events WHERE id = '{event_id}'")  # DON'T DO THIS
```

**Always use parameterized queries to prevent SQL injection.**

### 5. Configuration Management
**All hardcoded values MUST go in `backend/config.py` with environment variable support.**

```python
# CORRECT: Use centralized config
from config import get_crypto_symbols, FORECAST_DIRECTION_THRESHOLD

symbols = get_crypto_symbols()
threshold = FORECAST_DIRECTION_THRESHOLD

# WRONG: Hardcoded values
symbols = {"BTC-USD": "BTC-USD", "ETH-USD": "ETH-USD"}  # DON'T DO THIS
```

**Adding new symbols:** Update `backend/.env` with `CRYPTO_SYMBOLS` env var. Frontend automatically discovers via `/symbols/available`.

### 6. Input Validation
**All API endpoints MUST validate inputs using FastAPI Query parameters.**

```python
# CORRECT: Validated inputs with constraints
@app.get("/forecast/asset")
def forecast_asset_endpoint(
    symbol: str = Query(..., min_length=1, max_length=50),
    horizon_minutes: int = Query(
        DEFAULT_HORIZON_MINUTES,
        ge=MIN_HORIZON_MINUTES,
        le=MAX_HORIZON_MINUTES
    ),
):
    # Inputs are guaranteed valid here
    pass
```

### 7. Unique Constraints
Respect `(symbol, as_of, horizon_minutes)` uniqueness in `asset_returns` table.

### 8. Modularity
- New data sources → `ingest/`
- Feature engineering → `signals/`
- Forecasting models → `models/`
- Configuration → `config.py`
- Keep `app.py` thin (routing only)

### 9. Baseline First
The naive forecaster is the baseline. ML models must beat it to be deployed.

### 10. Batch Operations
**Use batch operations for performance.**

```python
# CORRECT: Batch insert
events_data = [prepare_event_data(entry, ...) for entry in entries]
insert_events_batch(events_data)  # 10-100x faster

# WRONG: Individual inserts in loop
for entry in entries:
    insert_event(entry, ...)  # Slow!
```

## Background Jobs

The backend runs scheduled jobs via APScheduler (started on app startup):

- **RSS ingestion**: Hourly (12 curated market-relevant feeds: crypto, tech, sports)
- **Crypto price backfill**: Daily (configurable symbols via `CRYPTO_SYMBOLS`)
- **Equity price backfill**: Daily (configurable symbols via `EQUITY_SYMBOLS`)
- **Baker projections**: Hourly (NFL win probabilities)
- **NFL Elo**: Daily (disabled by default via `DISABLE_NFL_ELO_INGEST=true`)

Jobs are configured in `app.py` startup event handler with configurable intervals via `config.py`.

**Disabling jobs:**
```bash
# backend/.env
DISABLE_STARTUP_INGESTION=true       # Skip all ingestion on startup
DISABLE_NFL_ELO_INGEST=true          # Skip NFL Elo (recommended - has CSV parsing issues)
DISABLE_BAKER_PROJECTIONS=true       # Skip Baker projections (if not needed)
```

### Performance Optimizations

The ingestion system is highly optimized to minimize API costs and runtime:

1. **Batch Duplicate Checking**: All URLs are checked against the database in a single query before processing
2. **Batch Insert**: Uses `executemany()` for 10-100x faster database writes
3. **Timestamp Filtering**: After the first run, only entries newer than the last fetch are processed
4. **Feed Metadata Tracking**: The `feed_metadata` table tracks when each source was last fetched
5. **Skip Startup Flag**: Set `DISABLE_STARTUP_INGESTION=true` in `.env` to skip ingestion during development

**Result:** First run processes all entries. Subsequent runs only check new entries and skip embedding calls for duplicates entirely. Batch operations provide massive speedup.

## ML Training Pipeline

Location: `backend/notebooks/asset_forecaster_training.py`

**Training workflow:**
1. Build feature dataset with `signals/feature_extractor.py`
2. **Per-symbol** time-based train/test split (80/20, no shuffle!)
3. Train RandomForestRegressor (baseline ML model)
4. Evaluate: MAE, RMSE, directional accuracy (per-symbol metrics)
5. Serialize to `backend/models/trained/asset_return_rf.pkl` or `.json`

**Model metadata includes:**
- Training date
- Feature names + schema version
- Symbol list
- Train/test date ranges
- Evaluation metrics (per-symbol and aggregate)

**Critical Fix Applied:**
- Event counting now uses `< as_of` (strict before) instead of `<= as_of` to prevent lookahead bias
- Train/test split is **per-symbol** to prevent cross-asset leakage
- Ensures valid ML performance metrics

## Environment Variables

All configuration is centralized in `backend/config.py` with environment variable support.

**Required in `backend/.env`:**

```bash
# Required for embeddings
OPENAI_API_KEY=sk-...

# Optional - LLM providers
ANTHROPIC_API_KEY=sk-ant-...       # For LLM analysis
GOOGLE_API_KEY=...                 # For Gemini

# Feature flags (recommended for development)
DISABLE_STARTUP_INGESTION=true     # Skip ingestion on startup (faster restarts)
DISABLE_NFL_ELO_INGEST=true        # Skip NFL Elo (has CSV parsing issues)

# Symbol configuration (optional - has sensible defaults)
CRYPTO_SYMBOLS=BTC-USD:BTC-USD,ETH-USD:ETH-USD,XMR-USD:XMR-USD
EQUITY_SYMBOLS=NVDA:NVDA

# Scheduler intervals (hours, optional)
RSS_INGEST_INTERVAL_HOURS=1
CRYPTO_BACKFILL_INTERVAL_HOURS=24
BAKER_PROJECTIONS_INTERVAL_HOURS=1

# Forecasting thresholds (optional)
FORECAST_DIRECTION_THRESHOLD=0.0005
FORECAST_CONFIDENCE_SCALE=2.0

# API limits (optional)
API_MAX_EVENTS_LIMIT=200
API_MAX_NEIGHBORS_LIMIT=50

# Auto-configured
DATABASE_URL=postgresql://...       # Auto-set by docker-compose
```

**Frontend `.env.local`:**
```bash
NEXT_PUBLIC_API_URL=https://will-node.ngrok.dev  # Or http://localhost:9000
```

See `backend/.env.example` for complete documentation with all 30+ configuration options.

## LLM Providers

The backend supports multiple LLM providers via `llm/providers.py`:

- **Claude** (default for analysis)
- **OpenAI** (GPT-4)
- **Gemini** (fast sentiment)

Provider abstraction ensures vendor-agnostic endpoints. If a provider fails, returns 503 with error message.

## Adding New Features

### New Symbols (Crypto/Equity)
**No code changes required!** Just update configuration:

```bash
# backend/.env
CRYPTO_SYMBOLS=BTC-USD:BTC-USD,ETH-USD:ETH-USD,SOL-USD:SOL-USD,AVAX-USD:AVAX-USD
EQUITY_SYMBOLS=NVDA:NVDA,TSLA:TSLA,AAPL:AAPL
```

Frontend automatically discovers new symbols via `/symbols/available` endpoint.

### New Data Source
1. Create ingestion script in `ingest/`
2. Normalize to `events` table schema with `categories` for domain classification
3. Add configuration to `config.py` with env var support
4. Add to scheduler in `app.py` if recurring
5. Use batch operations for performance

### New Forecasting Model
1. Create module in `models/`
2. Follow result schema: `{expected_return, direction, confidence, sample_size}`
3. Import configuration from `config.py` (no hardcoded values!)
4. Add endpoint in `app.py` with input validation
5. Must include fallback to baseline on errors

### New Features (ML)
1. Add stateless functions to `signals/`
2. Maintain feature schema versioning
3. Document in `signals/feature_extractor.py`
4. **Ensure no lookahead bias** (use `< as_of`, never `<=`)
5. Validate timezone-aware datetimes

### Schema Changes
1. Update `db/init.sql`
2. Document in this file
3. Consider migration strategy for existing data
4. Update affected queries to use parameterized SQL

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

1. **Using naive datetimes** - Always use `datetime.now(tz=timezone.utc)`. Validation will raise `ValueError` if you forget.
2. **Future data leakage** - Use `< as_of` (strict before), never `<= as_of`. Critical for ML integrity.
3. **SQL injection** - Use `psycopg.sql.SQL()` and `sql.Identifier()`, never f-strings for SQL
4. **Hardcoded values** - Everything goes in `config.py` with env var support
5. **Forgetting to sync dependencies** - Run `uv sync` after pulling changes
6. **Database schema drift** - Keep `db/init.sql` as source of truth
7. **Ignoring sample size** - Low-confidence forecasts need sample_size checks
8. **Breaking API contracts** - Never change endpoint paths or response schemas without versioning
9. **Missing input validation** - All API endpoints need FastAPI Query validation
10. **Individual inserts in loops** - Use batch operations with `executemany()` for 10-100x speedup

## Project Status

**Current State (December 2025):**
- ✅ Backend: FastAPI + PostgreSQL + pgvector
- ✅ Centralized configuration (`config.py`) with 30+ env vars
- ✅ Event ingestion: 12 curated RSS feeds (crypto, tech, sports)
- ✅ Asset returns: Configurable symbols (default: BTC, ETH, XMR, NVDA)
- ✅ Naive forecaster: Baseline historical returns
- ✅ Event forecaster: Semantic similarity → weighted returns
- ✅ Regime classifier: Rule-based (uptrend/downtrend/chop/high_vol)
- ✅ Frontend: Separated pages - `/` (landing), `/crypto`, `/nfl`, `/events`
- ✅ Domain-filtered events: Crypto events on crypto page, sports events on NFL page
- ✅ LLM endpoints: Event analysis + sentiment
- ✅ Background scheduler: Configurable intervals, conditional scheduling
- ✅ Security: SQL injection fixed, timezone validation, input validation
- ✅ Performance: Batch operations, 10-100x faster ingestion
- ✅ ML integrity: Lookahead bias fixed, per-symbol train/test splits
- ✅ Dynamic discovery: `/symbols/available`, `/horizons/available`, `/sources/available`
- ✅ Developer experience: Zero-config `./run-dev.sh`, clean shutdown
- ✅ Database schema: Added `projections` table for external NFL projections

**Recent Fixes (December 5, 2025):**
- **Frontend Reorganization**: Separated single confusing dashboard into dedicated domain pages
  - `/` - Clean landing page with navigation cards
  - `/crypto` - Crypto forecasts with crypto-specific events
  - `/nfl` - NFL projections with sports-specific events
  - `/events` - Full event feed with filtering
  - Updated navigation: Home, Crypto, NFL, Events
- **Database Schema**: Added missing `projections` table to `db/init.sql`
  - Stores external projection data (NFL win probabilities, etc.)
  - Includes game_id, opponent info, and metadata
  - Indexed for efficient symbol/metric queries
- **UI Improvements**: Better help messages for missing data (API key setup instructions)

**Known Issues & TODOs:**

1. **NFL Projections Setup Required** ⚠️
   - The `projections` table exists but is empty
   - Requires `BAKER_API_KEY` environment variable (from sportsdata.io)
   - Setup instructions:
     ```bash
     # Add to backend/.env
     BAKER_API_KEY=your-key-here

     # Run ingestion
     cd backend && uv run python -m ingest.baker_projections
     ```
   - UI now displays helpful setup message when projections are unavailable

2. **Table Name Inconsistency** ⚠️
   - Code uses both `projections` and `asset_projections` tables
   - `asset_projections.py` creates and uses `asset_projections` table
   - `db/init.sql` defines `projections` table
   - Need to standardize on one table name (recommend `projections`)
   - May need to migrate `asset_projections` → `projections` or update code

3. **Connection Pool Cleanup Warnings**
   - Python scripts show thread cleanup warnings on exit
   - Not critical but should be addressed for cleaner logs
   - Solution: Explicitly close connection pool after operations

**Next Steps:**
- [ ] Resolve projections table naming inconsistency
- [ ] Add BAKER_API_KEY to documentation and .env.example
- [ ] Fix connection pool cleanup warnings
- [ ] ML forecaster beyond baseline (XGBoost/LightGBM)
- [ ] Production deployment (Render/Fly.io + Vercel)
- [ ] Backtesting framework
- [ ] Model registry and A/B testing
- [ ] Structured logging (replace print statements)
- [ ] Rate limiting middleware
- [ ] Integration tests
