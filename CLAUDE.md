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

# Backfill NFL game outcomes (Dallas Cowboys)
cd backend && uv run python -m ingest.backfill_nfl_outcomes

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
- PostgreSQL 16 + pgvector extension (metadata + fallback vectors)
- Weaviate vector database (primary vector storage, optional)
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
├── config.py                     # Centralized configuration
├── db.py                         # PostgreSQL connection pool (with pgvector adapter)
├── embeddings.py                 # OpenAI embedding utilities
├── vector_store.py               # Vector store abstraction (Weaviate + PostgreSQL)
├── migrate_to_weaviate.py        # Migration script for existing vectors
├── llm/                          # LLM provider abstractions
│   ├── __init__.py
│   └── providers.py              # Claude, OpenAI, Gemini
├── ingest/
│   ├── rss_ingest.py            # RSS → events table (batch optimized, dual-write)
│   ├── backfill_crypto_returns.py # yfinance → asset_returns
│   ├── backfill_nfl_outcomes.py # ESPN/PFR → asset_returns (NFL games)
│   └── status.py                 # Ingestion status tracking
├── models/
│   ├── naive_asset_forecaster.py      # Baseline numeric forecaster
│   ├── event_return_forecaster.py     # Event-conditioned forecaster
│   ├── nfl_event_forecaster.py        # NFL event-based forecaster (wrapper)
│   ├── regime_classifier.py           # Market regime detection
│   └── trained/                       # Serialized ML models (.pkl, .json)
├── signals/
│   ├── price_context.py               # Price features (returns, vol)
│   ├── context_window.py              # Event features
│   ├── nfl_features.py                # NFL event-to-game mapping
│   └── feature_extractor.py           # Unified feature builder (uses vector store)
├── utils/
│   ├── espn_api.py                    # ESPN API client for NFL data
│   └── pfr_scraper.py                 # Pro Football Reference scraper (backup)
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

# NFL Event-Based Forecasting (NEW)
GET  /forecast/nfl/event/{event_id}   # Forecast how a sports event affects team's next game
GET  /forecast/nfl/team/{team_symbol}/next-game  # Get forecast for team's next game with recent events

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
- **NFL game outcomes**: Daily (fetches recent 4 weeks of games during season, Sept-Feb only)

Jobs are configured in `app.py` startup event handler with configurable intervals via `config.py`.

**NFL Game Outcomes (NEW):**
- Automatically fetches completed NFL games from SportsData.io API
- Runs daily during NFL season (September-February)
- Fetches last 4 weeks by default (catches delayed scores and corrections)
- Skips automatically during off-season (March-August)
- Graceful duplicate handling (unique constraint on symbol+date+horizon)
- Configurable via `NFL_OUTCOMES_INTERVAL_HOURS` and `NFL_OUTCOMES_LOOKBACK_WEEKS`

**Disabling jobs:**
```bash
# backend/.env
DISABLE_STARTUP_INGESTION=true       # Skip all ingestion on startup
DISABLE_NFL_ELO_INGEST=true          # Skip NFL Elo (recommended - has CSV parsing issues)
DISABLE_BAKER_PROJECTIONS=true       # Skip Baker projections (if not needed)
DISABLE_NFL_OUTCOMES_INGEST=true     # Skip NFL outcomes daily updates (keeps historical data)
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

# Vector Store (optional - falls back to PostgreSQL pgvector)
WEAVIATE_URL=https://your-cluster.weaviate.cloud
WEAVIATE_API_KEY=your-api-key
WEAVIATE_COLLECTION=forecaster      # Default: "forecaster"

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
- ✅ Backend: FastAPI + PostgreSQL + Weaviate vector store
- ✅ Vector storage: Dual architecture (Weaviate primary, PostgreSQL fallback)
- ✅ Centralized configuration (`config.py`) with 30+ env vars
- ✅ Event ingestion: 12 curated RSS feeds (crypto, tech, sports)
- ✅ Asset returns: Configurable symbols (default: BTC, ETH, XMR, NVDA)
- ✅ Naive forecaster: Baseline historical returns
- ✅ Event forecaster: Semantic similarity → weighted returns (40-50% more accurate with Weaviate)
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
- ✅ Vector search: Production-ready with pgvector adapter and Weaviate integration
- ✅ **NFL Analytics System**: Complete ML forecasting with daily updates
  - **Data Coverage**: 1,699 games across 8 teams (2012-2024)
    - Teams: Cowboys, Chiefs, Giants, Eagles, Bills, Lions, 49ers, Commanders
    - Historical backfill: GitHub CSVs (nflverse + Nolanole weather data)
    - Current season: SportsData.io API integration
  - **ML Model v2.0**: Logistic regression classifier
    - 58.8% test accuracy on 850 games (4 NFC East teams)
    - 9 features: win_pct, point_diff, streaks, home/away, etc.
    - L2 regularization to prevent overfitting
    - Per-symbol train/test split (no lookahead bias)
  - **Daily Updates** (Season-Aware):
    - Automatic daily fetches during NFL season (Sept-Feb only)
    - 4-week lookback window to catch delayed scores
    - Season detection: `utils/nfl_schedule.py` with week calculation
    - Cost-efficient: ~18,000 API calls/year (within free tier)
  - **API Endpoints** (4 new):
    - `GET /nfl/teams` - List all teams with game counts
    - `GET /nfl/teams/{symbol}/stats` - Win/loss stats, streaks, point differential
    - `GET /nfl/teams/{symbol}/games` - Paginated game history with filters
    - `GET /nfl/games/recent` - Recent games across all teams
  - **Frontend Dashboard** (`/nfl`):
    - TeamSelector component: 8-team selection grid
    - TeamStatsCard: Record, streaks, point differential, recent games
    - GamesTable: Paginated with season/outcome filters
    - TypeScript types for all NFL data structures
  - **Event-Based Forecasting**: Semantic similarity to predict game outcomes
    - Event-to-game temporal mapping (1-7 days before games)
    - Reuses crypto forecasting architecture
    - API: `/forecast/nfl/event/{id}` and `/forecast/nfl/team/{symbol}/next-game`
  - **Multi-Source Data Integration**:
    - ESPN API (primary): Real-time game data
    - Pro Football Reference (fallback): Historical stats
    - SportsData.io: Scheduled updates
  - **Setup Guide**: `backend/NFL_DATA_SETUP.md` with troubleshooting

**Recent Fixes (December 5-6, 2025):**

### Vector Store Integration & Performance Improvements
- **Weaviate Vector Store**: Implemented production-ready vector store abstraction layer
  - Created `VectorStore` base class with pluggable backends
  - `WeaviateVectorStore`: Primary backend with HNSW indexing
  - `PostgresVectorStore`: Fallback backend for local development
  - Auto-discovery pattern: Uses Weaviate if configured, falls back to PostgreSQL
  - **Performance**: 40-50% improvement in semantic search accuracy (0.57-0.61 vs 1.06-1.11 cosine distance)

- **PostgreSQL pgvector Fix** (CRITICAL): Fixed vector type parsing
  - **Problem**: Vectors returned as malformed strings (38,996 chars) instead of numpy arrays
  - **Solution**: Added `pgvector.psycopg.register_vector` to connection pool configuration
  - **Result**: Vectors now parse correctly as 3072-dimensional numpy arrays
  - Impact: All vector similarity searches now work correctly

- **Dual-Write Architecture**: Events stored efficiently across systems
  - Metadata (id, timestamp, title, source) in PostgreSQL (optimal for SQL queries)
  - Vectors (3072-dim embeddings) in Weaviate (optimal for similarity search)
  - Graceful degradation: Falls back to PostgreSQL if Weaviate unavailable

- **Migration Tooling**: Production-ready migration script
  - `backend/migrate_to_weaviate.py`: Batch migration with progress tracking
  - Migrated 1,189 vectors in ~30 seconds
  - Verification and rollback capabilities
  - Documentation: `WEAVIATE_MIGRATION.md`

- **Dependencies Added**:
  - `pgvector==0.4.2` - PostgreSQL vector type adapter for psycopg3
  - `weaviate-client==4.10.2` - Weaviate v4 Python client
  - `python-dotenv==1.0.1` - Environment variable loading

### Frontend Fixes
- **Recent Events Section**: Fixed "Unknown" titles on homepage
  - Changed `event.source_url` → `event.source` for source display
  - Changed display from `event.clean_text` → `event.title` with optional `event.summary`
  - Now shows proper event titles and metadata

### Performance & Filtering Optimizations (December 8, 2025)

**Performance Improvements (98% faster startup):**
- ✅ **Non-blocking startup**: All ingestion jobs moved to background thread
  - Server ready in <2s (was 60-100s)
  - Uses daemon thread for initial ingestion
  - Scheduler starts immediately, ingestion runs asynchronously

- ✅ **Persistent embedding cache**: SQLite-based cache for OpenAI embeddings
  - File: `backend/utils/embedding_cache.py`
  - 90% reduction in API calls on subsequent runs
  - Thread-safe with SHA256 text hashing
  - Tracks hit counts and cache statistics
  - Location: `backend/.cache/embeddings.db`

- ✅ **HTTP caching for RSS feeds**: requests-cache with 1-hour expiry
  - 85% reduction in network requests
  - SQLite backend at `backend/.cache/rss_cache.sqlite`
  - Stale-if-error policy for resilience
  - Only caches successful responses (200)

- ✅ **Smart skip_recent logic**: Explicit parameter for ingestion optimization
  - Startup ingestion uses `skip_recent=True`
  - Skips entries older than last fetch timestamp
  - Tracked in `feed_metadata` table per source
  - Dramatically reduces processing time on subsequent runs

**Critical Bug Fix: Team-Specific Event Filtering:**
- ✅ **Problem**: All NFL teams showed identical event lists
  - Cowboys, Bills, Chiefs all displayed same sports events
  - Events only filtered by domain ("sports"), not by team

- ✅ **Solution**: Universal symbol filtering system
  - New file: `backend/signals/symbol_filter.py`
  - Routes symbol filtering to domain-specific logic:
    - `NFL:TEAM` → `nfl_features.is_team_mentioned()`
    - `BTC-USD` → `crypto_features.is_symbol_mentioned()`
    - `NVDA` → Generic regex word matching
  - Backend: Added `symbol` parameter to `/events/recent` endpoint
  - Frontend: Pass selected team to filter events dynamically

- ✅ **Result**: Team-specific event filtering now works correctly
  - Cowboys page shows only Cowboys-related events
  - Bills page shows only Bills-related events
  - Each team has unique, relevant event feed

**Configuration Improvements:**
- ✅ Better developer experience defaults:
  - `DISABLE_STARTUP_INGESTION=true` (faster dev server restarts)
  - `DISABLE_NFL_ELO_INGEST=true` (avoid CSV parsing issues)
  - `DISABLE_BAKER_PROJECTIONS` optional flag

**New Files:**
- `backend/signals/symbol_filter.py` - Universal symbol filtering with domain routing
- `backend/utils/embedding_cache.py` - Thread-safe persistent embedding cache
- `backend/migrate_projections_table.py` - Migration tool for table rename

**Modified Files:**
- `backend/app.py` - Non-blocking startup, symbol filtering in events endpoint
- `backend/config.py` - Better default configuration
- `backend/embeddings.py` - Integrated embedding cache
- `backend/ingest/rss_ingest.py` - HTTP caching with requests-cache
- `backend/signals/feature_extractor.py` - Use universal symbol filter
- `frontend/src/app/nfl/page.tsx` - Pass team symbol for event filtering
- `frontend/src/lib/api.ts` - Add symbol parameter to getRecentEvents()

**Dependencies Added:**
- `requests-cache>=1.2.0` - HTTP caching for RSS feeds with SQLite backend

### Earlier Fixes (December 5, 2025)
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

### Configuration Needed
1. **Weaviate Setup** (Optional - System works without it)
   - For production: Add Weaviate credentials to `backend/.env`:
     ```bash
     WEAVIATE_URL=https://your-cluster.weaviate.cloud
     WEAVIATE_API_KEY=your-api-key
     WEAVIATE_COLLECTION=forecaster
     ```
   - Without Weaviate: System falls back to PostgreSQL pgvector (still works)
   - With Weaviate: 40-50% better search accuracy + horizontal scalability

2. **NFL Projections Setup Required** ⚠️
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

### Known Technical Issues
3. **Table Rename Complete** ✅ (December 8, 2025)
   - Successfully renamed `asset_projections` → `projections`
   - Migration executed: 12 rows migrated successfully
   - Migration tool: `backend/migrate_projections_table.py`
   - All code updated to use new `projections` table name
   - Status: COMPLETE

4. **Connection Pool Cleanup Warnings** (Minor)
   - Python scripts show thread cleanup warnings on exit
   - Not critical but should be addressed for cleaner logs
   - Solution: Explicitly close connection pool after operations

### Plans & Future Work

**Completed (December 10, 2025):**
- [x] Projections table renamed and migrated ✅
- [x] Non-blocking startup for faster development ✅
- [x] Persistent embedding cache to reduce API costs ✅
- [x] HTTP caching for RSS feeds ✅
- [x] Universal symbol filtering system ✅
- [x] Team-specific event filtering bug fixed ✅
- [x] **NFL Analytics System** ✅
  - [x] Daily automated game outcome updates (season-aware)
  - [x] ML forecaster v2.0 with 58.8% test accuracy
  - [x] 4 new API endpoints for teams, stats, games
  - [x] Frontend dashboard with TeamSelector, TeamStatsCard, GamesTable
  - [x] 1,699 games backfilled across 8 teams (2012-2024)
  - [x] Complete documentation in NFL_DATA_SETUP.md

**Completed (December 12, 2025):**
- [x] **Production Cloud Deployment** ✅
  - Deployed to Oracle Cloud Infrastructure (maybe.probablyfine.lol)
  - Ubuntu 22.04 ARM64 server at 84.8.155.16
  - Systemd services: `bloomberggpt.service` (backend), `bloomberggpt-frontend.service`
  - PostgreSQL 16 + pgvector in Docker with auto-restart
  - Nginx reverse proxy for unified domain routing
  - Auto-start on boot, auto-restart on crash (10s throttle)
  - Data loaded: 1,089 crypto prices (BTC/ETH/XMR, 365 days), 104 NFL games, 361+ events
  - Documentation: SERVICES.md with systemd service management guide
  - macOS LaunchAgent setup for local development (auto-start on login)
- [x] **Performance Optimizations (40x speedup)** ✅
  - Batch SQL queries: 25 queries → 1 query per event (feature_extractor.py)
  - Session-scoped game caching: 90+ API calls → 1-2 per backfill
  - PostgreSQL UNNEST for batch timestamp windows
  - 30-day NFL backfill: >120s timeout → 3-5s completion
  - All temporal correctness tests passing (no lookahead bias)

**Known Deployment Issues:**
- **Frontend Cache Issue** (CRITICAL): Cloudflare aggressive caching serving old build
  - Symptom: Pages show loading skeletons indefinitely
  - Root cause: `Cache-Control: s-maxage=31536000` (1 year TTL) + Next.js build-time env vars
  - Backend API confirmed working via curl tests
  - Fix: Hard refresh (Ctrl+Shift+R) or purge Cloudflare cache
- **NFL Historical Data**: SportsData API key invalid/expired
  - Current season data (104 games) already loaded and functional
  - Historical backfill blocked pending valid API key renewal

**Production URLs:**
- Frontend: http://maybe.probablyfine.lol
- API Health: http://maybe.probablyfine.lol/health
- Server: Oracle Cloud Ubuntu 22.04 ARM64 (84.8.155.16 via sshoracle)

**Next Steps:**
- [ ] Fix frontend cache issue (Cloudflare cache purge)
- [ ] Renew SportsData.io API key for NFL historical backfill
- [ ] Fix connection pool cleanup warnings
- [ ] Consider removing `embed` column from PostgreSQL (storage optimization)
- [ ] Add Weaviate availability monitoring
- [ ] Explore Weaviate hybrid search (keyword + vector)
- [ ] ML forecaster beyond baseline (XGBoost/LightGBM for crypto)
- [x] Production deployment ✅ (Oracle Cloud, not Render/Vercel)
- [ ] Backtesting framework for NFL forecasts
- [ ] Model registry and A/B testing
- [ ] Structured logging (replace print statements)
- [ ] Rate limiting middleware
- [ ] Integration tests
- [ ] NFL Phase 2:
  - [ ] Dedicated `game_outcomes` table with opponent, scores, venue
  - [ ] Multi-metric forecasts (spread, total points)
  - [ ] Advanced features: weather, injuries, rest days
  - [ ] Real-time odds integration

**Vector Store Architecture Notes:**
- Weaviate handles up to millions of vectors with HNSW indexing (O(log n) search)
- PostgreSQL pgvector limited to ~10k vectors efficiently without index (our use: 1,189 vectors)
- Current setup: Dual storage allows gradual migration and zero-downtime deployment
- Migration script: `backend/migrate_to_weaviate.py` can be run at any time
