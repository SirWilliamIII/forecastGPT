# BloombergGPT Semantic Markets — Development Roadmap

> Ship a crypto-focused MVP with a Next.js dashboard, deploy to managed PaaS, then iterate on ML and new domains.

---

## Current State ✅

**What's Built:**
- FastAPI backend with PostgreSQL + pgvector
- Event ingestion (Wired AI RSS → embeddings)
- Naive asset forecaster (baseline using historical returns)
- Event-conditioned forecaster (semantic similarity → weighted returns)
- Feature extraction (price + event context)
- Crypto returns for BTC-USD, ETH-USD, XMR-USD

**What's Planned:**
- Regime classifier
- More RSS sources
- ML models beyond baseline
- Frontend dashboard

---

## Phase 0: Backend Hardening (0.5–1.5 days)

### Schema Fix
Add missing `asset_returns` table to `db/init.sql`:

```sql
CREATE TABLE IF NOT EXISTS asset_returns (
    symbol TEXT NOT NULL,
    as_of TIMESTAMPTZ NOT NULL,
    horizon_minutes INT NOT NULL,
    realized_return DOUBLE PRECISION NOT NULL,
    price_start DOUBLE PRECISION NOT NULL,
    price_end DOUBLE PRECISION NOT NULL,
    CONSTRAINT asset_returns_unique UNIQUE (symbol, as_of, horizon_minutes)
);

CREATE INDEX idx_asset_returns ON asset_returns (symbol, as_of, horizon_minutes);
```

### API Polish
- [ ] Add CORS middleware for frontend origin
- [ ] Add `/health` endpoint (DB + extension check)
- [ ] Add `response_model` to `/forecast/asset`
- [ ] Add `GET /events/recent?limit=50` endpoint

### Minimal Tests
- [ ] Smoke test: insert event + return → hit forecasts → assert shape

---

## Phase 1: Scheduled Ingestion (1–2 days)

### Cron-based Ingestion (Keep Simple)
Use APScheduler or GitHub Actions cron (avoid Celery for now):

```python
# backend/ingest/scheduler.py
from apscheduler.schedulers.blocking import BlockingScheduler
from ingest.rss_ingest import main as ingest_rss
from ingest.backfill_crypto_returns import update_daily

scheduler = BlockingScheduler()

@scheduler.scheduled_job('interval', hours=1)
def hourly_rss():
    ingest_rss()

@scheduler.scheduled_job('cron', hour=0, minute=30)
def daily_prices():
    update_daily()

scheduler.start()
```

### Add More Sources
- [ ] CoinDesk RSS
- [ ] CryptoNews RSS
- [ ] SEC EDGAR filings (stretch)

---

## Phase 2: Frontend MVP (3–5 days) ⭐ Highest Payoff

### Tech Stack (Recommended)
```
Next.js 14+ (App Router) + TypeScript
Tailwind CSS + shadcn/ui
TanStack Query (data fetching)
Recharts (visualization)
Deploy to Vercel
```

### Directory Structure
```
frontend/
├── app/
│   ├── layout.tsx
│   ├── page.tsx                    # Main dashboard
│   └── events/
│       ├── page.tsx                # Event feed
│       └── [eventId]/
│           └── page.tsx            # Event detail + forecast
├── lib/
│   └── api.ts                      # Typed API client
└── components/
    ├── ForecastCard.tsx
    ├── EventList.tsx
    ├── SymbolSelector.tsx
    └── Chart.tsx
```

### Core Features

#### 1. Symbol Forecast Dashboard
- Symbol selector: BTC-USD / ETH-USD / XMR-USD
- Horizon selector: 1h, 4h, 24h
- Display:
  - Naive forecast (expected_return, direction, confidence)
  - Event-conditioned forecasts for recent events
  - Comparison: naive vs event-conditioned

#### 2. Event Feed + Similarity
- Paginated list of recent events
- Click event → show:
  - Semantic neighbors
  - Event-based forecast with p_up/p_down
  - Sample size (for confidence indication)

#### 3. Quick Win: Comparison Card
```
┌─────────────────────────────────────┐
│  BTC-USD 24h Forecast               │
├─────────────────────────────────────┤
│  Baseline:  +0.8%  ↗ (conf: 0.42)   │
│  Event-Adj: +1.2%  ↗ (conf: 0.67)   │
│  Based on 23 similar events         │
└─────────────────────────────────────┘
```

---

## Phase 3: Domain Focus (1–2 days)

### MVP Narrative
> "Crypto markets conditioned on AI/tech narratives"

### Tasks
- [ ] Add 1–2 crypto RSS sources
- [ ] Simple event tagging (AI, regulation, macro, security)
- [ ] Filter event feed by tag/source in UI
- [ ] Highlight AI vs non-AI events

### Future Expansion (Phase 3b)
Add AI/tech equities basket: NVDA, MSFT, META, GOOGL, AMD, TSLA

---

## Phase 4: Regime Classifier (1–3 days)

### Rule-Based First (No ML Yet)
```python
# backend/models/regime_classifier.py
def classify_regime(symbol: str, as_of: datetime) -> str:
    feats = build_price_features(symbol, as_of)
    
    if feats.r_7d and feats.r_7d > 0.05 and feats.vol_7d < 0.03:
        return "uptrend"
    elif feats.r_7d and feats.r_7d < -0.05:
        return "downtrend"
    elif feats.vol_7d and feats.vol_7d > 0.05:
        return "high_vol"
    else:
        return "chop"
```

### Integration
- Add to `build_features()` output
- Show regime badge in dashboard
- Color-code forecasts by regime

---

## Phase 5: Production Deployment (2–3 days)

### Architecture
```
┌─────────────────────────────────────────────────────────┐
│                    Frontend (Vercel)                    │
│                 Next.js + TanStack Query                │
└─────────────────────────┬───────────────────────────────┘
                          │ HTTPS
                          ▼
┌─────────────────────────────────────────────────────────┐
│               API (Railway/Render)                      │
│            FastAPI Docker Container                     │
│         /events, /forecast/*, /health                   │
└─────────────────────────┬───────────────────────────────┘
                          │ psycopg
                          ▼
┌─────────────────────────────────────────────────────────┐
│           Postgres (Railway/Neon/Render)                │
│              pgvector + events + returns                │
└─────────────────────────┬───────────────────────────────┘
                          ▲
┌─────────────────────────┴───────────────────────────────┐
│               Workers (Cron/Separate Service)           │
│            RSS ingest + price updates                   │
└─────────────────────────────────────────────────────────┘
```

### CI/CD (GitHub Actions)
```yaml
# .github/workflows/deploy.yml
on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: cd backend && uv sync && uv run pytest

  deploy:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: railway up  # or render deploy
```

### Infrastructure Checklist
- [ ] Dockerfile for backend
- [ ] Environment variables (OPENAI_API_KEY, DATABASE_URL)
- [ ] Health check endpoint
- [ ] Sentry for error tracking
- [ ] Basic rate limiting

---

## Phase 6: Advanced ML (1–3 weeks, Future)

### Backtesting Framework
```python
# backend/ml/backtest.py
def build_dataset(symbols, start, end, horizon_minutes):
    """Generate train/test splits with strict time boundaries."""
    rows = []
    for symbol in symbols:
        for as_of in date_range(start, end):
            features = build_features(symbol, as_of, horizon_minutes)
            target = get_realized_return(symbol, as_of, horizon_minutes)
            rows.append({**features, "target": target})
    return pd.DataFrame(rows)
```

### Model Training
- XGBoost/LightGBM on combined features
- Compare to naive baseline (must beat it!)
- Walk-forward validation

### Model Registry
- Version pickles with metadata
- A/B test: route some calls to ML vs baseline
- Track performance over time

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Data leakage | Add assertions for timestamp ordering in tests |
| Sparse data | Show sample_size in UI; grey out low-confidence forecasts |
| OpenAI outages | Store embeddings permanently; add retry/backoff |
| Slow queries | Ensure indexes on (symbol, as_of); use LIMIT everywhere |
| Over-engineering | Start simple (PaaS, cron); scale only when needed |

---

## Quick Wins 🚀

These deliver visible value in <1 day each:

1. **Recent events endpoint** — `GET /events/recent?limit=50`
2. **Event detail page** — Show neighbors + forecast
3. **Naive vs event comparison card** — Side-by-side arrows
4. **Regime badge** — Simple 7-day return sign → visual label
5. **Demo dataset** — Curate 3–5 interesting events with annotations

---

## Effort Summary

| Phase | Effort | Priority |
|-------|--------|----------|
| Phase 0: Backend hardening | S–M (0.5–1.5 days) | 🔴 Critical |
| Phase 1: Scheduled ingestion | M (1–2 days) | 🟡 High |
| Phase 2: Frontend MVP | M–L (3–5 days) | 🔴 Critical |
| Phase 3: Domain polish | M (1–2 days) | 🟡 High |
| Phase 4: Regime classifier | M (1–3 days) | 🟢 Medium |
| Phase 5: Production deploy | M (2–3 days) | 🟡 High |
| Phase 6: Advanced ML | L–XL (1–3 weeks) | 🟢 Future |

**Target:** Phases 0–2 + thin Phase 3 = **demoable MVP in ~2 weeks**

---

## Next Steps

1. Run `docker compose down -v && docker compose up -d db` to reset DB
2. Add `asset_returns` table to `init.sql`
3. Run backfill script to populate returns
4. Create `frontend/` with Next.js scaffold
5. Build dashboard → deploy → iterate!
