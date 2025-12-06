# **PLAN MAESTRO — ForecastGPT / Semantic Forecasting OS**

**If this document and the code disagree, this document wins.**

Audience: **coding LLMs** (Claude, GPT-X, Gemini, etc.).

---

## **0. Mission (Generalized)**

ForecastGPT is a semantic + numeric forecasting engine designed to answer:

> **“Given the context of an event, piece of news, or new data, what does it imply for a chosen target (asset, person, team, system, etc.) and metric across multiple forecast horizons (1h–24h, 1–2 weeks, 1–5+ years)?”**

Core ideas:

- **Events** → text, embeddings, narrative clusters
- **Targets** → anything with a time series (BTC, NVDA, a presidential candidate, an NFL team, a macro index, etc.)
- **Metrics** → whatever you track for that target (price, poll share, win probability, risk score…)
- **Horizon** → how far ahead you care about the metric changing

BTC/ETH/XMR are **current demo targets**, not the conceptual center of the system.

---

## **1. System Overview**

### **1.1 Backend Architecture (FastAPI)**

```other
backend/
  app.py                        # FastAPI + scheduler
  db.py                         # PostgreSQL connection pool
  embeddings.py                 # Embedding wrapper (OpenAI, etc.)
  llm/
    providers.py                # Claude / OpenAI / Gemini abstractions

  ingest/
    rss_ingest.py               # Events → events table
    backfill_crypto_returns.py  # Example numeric ingestor (BTC/ETH/XMR)

  models/
    naive_asset_forecaster.py   # Baseline metric-change forecaster
    event_return_forecaster.py  # Event-conditioned forecaster
    regime_classifier.py        # Regime labels for a target/metric
    trained/                    # Serialized ML models (.pkl + metadata)

  signals/
    price_context.py            # Numeric context features
    context_window.py           # Event context features
    feature_extractor.py        # Unified feature builder

  numeric/
    asset_returns.py            # Helpers for realized metric deltas

  cli/
    forecast_cli.py             # Command-line interface

  notebooks/
    asset_forecaster_training.py
```

### **1.2 Frontend Architecture (Next.js)**

```other
frontend/
  app/
    page.tsx                    # Main dashboard (target/metric/horizon)
    events/page.tsx             # Event feed
    events/[event]/page.tsx     # Event details
  components/
  lib/api.ts                    # Typed API client
```

### **1.3 Data Domains**

#### **Events (universal)**

events table stores **any semantic event**:

- id (UUID)
- timestamp (UTC)
- title, summary
- raw_text, clean_text
- embed (3072-dim pgvector)
- source, categories, tags

Events are **not** tied to BTC or any specific domain. They are generic “things that happen.”

#### **Numeric Targets & Metric Changes**

Currently stored in asset_returns (name is legacy; concept is general):

Each row represents **the realized change of some metric for some target over some horizon**:

- symbol – opaque ID for the target
    - examples: BTC-USD, NVDA, PRESIDENT:TRUMP, NFL:KC_CHIEFS
- as_of – reference time (UTC)
- horizon_minutes – horizon length (can stand in for longer horizons via convention)
- realized_return – realized *change* in the metric over the horizon
- price_start, price_end – current code assumes financial “price”; conceptually: metric_start / metric_end

In code and future docs, treat:

- “symbol” as **target_id**
- “return” as **metric_delta**

without changing the schema unless you explicitly run a migration.

---

## **2. Canonical Development Phases**

Phases must be followed in order by any coding LLM.

---

## **PHASE 0 — Backend Hardening (DONE)**

Guarantees:

- FastAPI app boots cleanly
- DB + pgvector reachable
- events and asset_returns schemas in place
- CORS configured
- /health endpoint working
- Scheduler running:
    - RSS ingestion (hourly)
    - numeric backfill (daily; currently BTC/ETH/XMR demo)
- Baseline forecaster operational
- Event-conditioned forecaster operational
- Regime classifier operational

Backend is **stable enough to extend**.

---

## **PHASE 1 — Ingestion Layer (Generalized)**

Goal: Reliable ingestion for **events** and **numeric series**, without assuming “crypto only.”

### **1.1 Event Ingestion**

ingest/rss_ingest.py:

- Pull from multiple sources (Hacker News, Wired AI, CoinDesk, etc.)
- Normalize:
    - clean_text, summary, source, categories, tags
- Deduplicate via canonical URL
- Store in events with UTC timestamps
- Generate embeddings from clean_text
- Use feed_metadata to avoid re-processing old items

Future LLMs may add domain-specific feeds:

- political news
- sports news
- macro/econ feeds
- company filings

All still land in the **same events table**.

### **1.2 Numeric Ingestion**

ingest/backfill_crypto_returns.py is the current example:

- fetch OHLC for BTC-USD, ETH-USD, XMR-USD
- compute returns → insert into asset_returns

Conceptually, this is the **template** for any numeric series:

- For stocks: OHLC → returns
- For candidates: polling series → poll_deltas
- For NFL teams: ELO or implied win prob → rating_deltas
- For custom metrics: risk scores, engagement, etc.

Rules:

- Always use timezone-aware UTC as_of
- Enforce uniqueness: (symbol, as_of, horizon_minutes)
- Make all writes idempotent (safe to rerun ingestion)

---

## **PHASE 2 — Feature Engineering Layer**

Everything runs through signals/feature_extractor.py.

### **2.1 Numeric Context Features**

From price_context.py:

- rolling returns / deltas over multiple windows
- volatility estimates (3 / 7 / 30 days, or equivalent)
- z-score vs recent history
- moving averages / trends
- max drawdown over window
- regime labels (from regime_classifier.py)

These features apply to **any** time series, not just prices.

### **2.2 Event Context Features**

From context_window.py:

- event density around a given time (1d / 3d / 7d, etc.)
- similarity to “uptrend” / “downtrend” / other narrative centroids
- PCA-reduced event embeddings
- tag/category frequencies

Events are **global**; they can influence any target depending on context and future domain-specific logic.

### **2.3 Regime Classifier**

regime_classifier.py produces regimes like:

- uptrend
- downtrend
- chop
- high_vol

Defined on numeric behavior of the metric for a given target.

The classifier itself is agnostic to whether the target is BTC, a stock, a candidate, or a team.

### **2.4 Feature Rules**

- All features are numeric scalars
- Feature sets are versioned (e.g. feature_version in metadata)
- No lookahead: features at time T use data strictly < T

---

## **PHASE 3 — ML Forecasting Engine (Target/Metric Agnostic)**

### **3.1 Training Workflow**

Notebook: backend/notebooks/asset_forecaster_training.py

LLM tasks:

1. Use feature_extractor to build a dataset for one or more (symbol, metric, horizon) combos.
2. Apply strict time-based split into train/test (no shuffle).
3. Train models:
    - RandomForestRegressor
    - GradientBoostingRegressor

        (Later: XGBoost, LightGBM, linear baselines)

1. Evaluate:
    - MAE
    - RMSE
    - directional accuracy (sign of delta)
1. Generate feature importance plots.
2. Serialize model + metadata.

### **3.2 Serialization Format**

Save under backend/models/trained/:

- asset_return_rf.pkl (or a more generic name later)
- asset_return_rf.json (metadata)

Metadata example:

```other
{
  "trained_at": "2025-12-02T00:00:00Z",
  "symbols": ["BTC-USD", "NVDA"],
  "metrics": ["return"],             // conceptually “metric_delta”
  "feature_version": "v1",
  "train_window": "2021-01-01/2025-01-01",
  "test_window": "2025-01-01/2025-06-01",
  "horizons_minutes": [60, 1440],
  "metrics_eval": {
    "BTC-USD:1440": {"mae": ..., "rmse": ..., "directional_accuracy": ...}
  }
}
```

### **3.3 Inference API**

GET /forecast/asset (legacy name) should:

1. Accept: symbol, horizon_minutes (and later, optional metric)
2. Build features for the requested (symbol, horizon) at “now” (UTC).
3. Try to load a trained ML model that supports those inputs.
4. If not found or model fails → fallback to naive baseline forecaster.

Response schema (stable):

```other
{
  "symbol": "BTC-USD",
  "horizon_minutes": 1440,
  "expected_return": -0.0057,
  "direction": "down",
  "confidence": 0.12,
  "sample_size": 58,
  "model_type": "ml|naive",
  "regime": "chop"
}
```

Treat expected_return as “expected metric_delta”; for price-like metrics this is return, for others it can be interpreted accordingly.

---

## **PHASE 4 — Event-Conditioned Forecasting**

This is the core semantic → numeric bridge.

### **4.1 Algorithm Overview**

For a given event and target:

1. Take the event embedding.
2. Search for historical events with similar embeddings.
3. For each neighbor, collect the realized metric_delta for the target over the chosen horizon around that neighbor’s timestamp.
4. Weight each neighbor’s delta by similarity (sim^p, or similar scheme).
5. Aggregate into:
    - expected_return (expected delta)
    - p_up, p_down
    - std of deltas
    - sample_size

This logic is independent of whether the target is BTC or something else; the only requirement is: we have historical metric_deltas for that target over that horizon.

### **4.2 Narrative Clusters**

LLM tasks:

- Maintain cluster centroids of embeddings for themes like:
    - regulation, AI, macro, elections, sports_injury, etc.
- Optionally store cluster label(s) on events.
- Allow per-domain centroids to be added over time.

### **4.3 Confidence & Flags**

- If sample_size < 8: mark forecast as low-confidence.
- Traffic light:
    - green: p_up > 0.6 (or domain-specific threshold)
    - yellow: 0.4 ≤ p_up ≤ 0.6
    - red: p_up < 0.4

API should include both raw numbers and a simple label (“green/yellow/red”) for frontend use.

---

## **PHASE 5 — Frontend (Dashboard for Any Target)**

The current UI shows BTC/ETH/XMR, but design must be viewed as **generic target picker + horizon picker**.

### **5.1 Dashboard**

- Target selector (currently BTC/ETH/XMR, later arbitrary list).
- Horizon selector (1h, 4h, 24h, etc.; later 1w, 2w, multi-year).
- Main card:
    - expected_return (metric_delta)
    - horizon label
    - confidence bar
    - regime tag
    - numeric context snapshot (key features).

### **5.2 Events Panel**

- Shows recent events by default.
- Later, can filter to “events most relevant to selected target” using:
    - similarity of events to target-specific centroids, or
    - event-conditioned impact scoring.

### **5.3 Event Details Page**

For a single event:

- full text, summary, tags
- semantic neighbors
- event-conditioned forecasts for selected targets/horizons
- traffic-light confidence + sample size
- narrative cluster labels

### **5.4 Deployment**

- Next.js app deployed on Vercel.
- Env config: API base URL, etc.

---

## **PHASE 6 — Production Deployment**

### **6.1 Backend Containerization**

- Dockerfile for backend/
- Deploy to Render / Fly.io / similar PaaS.
- .env template including DB and LLM provider keys.

### **6.2 CI/CD**

- GitHub Actions (or equivalent):
    - run tests (uv run pytest)
    - optional: lint
    - build + deploy on main branch

### **6.3 Monitoring (Stretch)**

- API latency
- forecast error tracking by symbol/metric/horizon
- feature drift monitoring (EvidentlyAI style)
- ingestion health: counts of events/rows per day, dedup ratio, etc.

---

## **7. Invariant Rules (LLM MUST OBEY)**

1. **All timestamps** are timezone-aware UTC datetimes.
2. Embeddings are always computed from clean_text (fallback raw_text).
3. All DB writes are idempotent and respect uniqueness constraints.
4. Forecast endpoints always return:
    - expected_return (metric_delta)
    - direction
    - confidence
    - sample_size
1. API response schemas are stable; changes require versioning.
2. New features must be added behind version flags or clearly annotated feature versions.
3. No lookahead bias in any feature or label construction.
4. ML models must always have a naive baseline fallback path.

These rules apply regardless of domain (crypto, elections, sports, etc.).

---

## **8. Future Extensions (Do Not Implement Without Explicit Instruction)**

- Topic modeling / LDA over events
- RL-based event weighting
- Multimodal ingestion (charts, PDF filings, audio transcripts)
- Real-time websockets for streaming forecasts
- Backtesting framework (intraday + multi-horizon)
- Model registry + A/B testing between forecasters
- Dedicated domain modules:
    - Elections mode
    - NFL mode
    - Macro mode

---

## **9. Project Status (High-Level)**

- **Backend:** stable, extensible
- **Ingestion:** v1 events + crypto demo numeric series
- **Forecasting:** naive + event-conditioned + regimes working
- **ML:** training pipeline ready; models next
- **Frontend:** dashboard + events MVP
- **Deployment:** ready for containerization and CI wiring

Conceptually, this is now a **semantic-to-metric forecasting OS** where BTC is just the first dataset plugged in, not the center of gravity.

---

## **10. Recent Progress / Gaps / Next Steps**

- **Progress**
  - Added a dedicated `asset_projections` store and ingestion for Baker NFL win probabilities (KC/DAL configurable via `BAKER_TEAM_MAP`), including opponent, spread, and O/U metadata plus idempotent writes.
  - UI now surfaces NFL projections with opponent context, spread/total, home/away badge, delta vs prior, recency stamp, and a small trend sparkline.
  - Ingestion observability: `/ingest/health` endpoint + `ingest_status` table tracks last success/error/row counts; projections index on `(symbol, metric, as_of DESC)` added.
  - Header-based auth for Baker (no key in URLs); scheduler wired for hourly projections; Elo job can be disabled via `DISABLE_NFL_ELO_INGEST`.
- **Issues / Debt**
  - NFL Elo source (FiveThirtyEight CSV) currently fails; ingestion disabled via env when noisy. Needs a replacement source or advanced-query path.
  - Venv shebang drifted when paths moved; prefer `uv run` and avoid stale venvs.
  - RSS `feed_metadata` required a schema init; keep migrations explicit going forward.
- **Next Steps (to make forecasting sharper)**
  - Add Baker advanced-query fetch to reduce misses and ingest moneylines/spreads directly; merge with changelog flow and update `ingest_status`. (Advanced query currently returns 422; need valid request schema from SportsDataIO.)
  - Broaden projections targets via `BAKER_TEAM_MAP` and store opponent odds cleanly; expose a lightweight projections read endpoint per team/game with trends.
  - Extend `/ingest/health` with per-job errors/row counts (RSS, projections, numeric backfills) and surface a health badge in the UI.
  - Data depth: add opponent- and game-level features (e.g., implied win prob deltas, spread/total movements) and optional trendlines in the sports card.
  - Formalize migrations (SQL) for all future schema changes; keep indexes in migrations, not inline DDL.
