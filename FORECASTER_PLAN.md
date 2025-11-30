FORECASTER_MASTER_PLAN.md

✔ Fully self-contained
✔ No conversation references
✔ Clear architecture
✔ Exact file + function expectations
✔ Implements everything you’ve built
✔ Lays out the future roadmap cleanly

⸻

BloombergGPT Forecaster Pipeline — Master Plan

This document defines the architecture, phases, responsibilities, and file structure for the semantic + numeric forecasting system. It is written so that any future LLM (Codex, GPT, etc.) can reconstruct and continue development with zero reliance on conversation history.

⸻

Objectives 1. Collect real numeric market returns. 2. Build features from:
• price history
• event embeddings
• simple statistical signals 3. Train a return forecaster for assets (initially BTC, ETH, XMR). 4. Expose predictions via a FastAPI backend. 5. Integrate semantic events with numeric forecasting.

Everything below details how each objective should be implemented.

⸻

System Overview

The system has two independent data domains, merged only inside the forecaster.

⸻

1. Events (Semantic Text Domain)

Stored in the events table via RSS ingestion.

Each event row contains:
• id
• timestamp
• source
• url
• title
• summary
• raw_text
• clean_text
• categories
• tags
• pgvector embedding (embed)

Nearest neighbor semantic search using:

SELECT ... ORDER BY embed <-> anchor LIMIT k ;

API:

GET /events/{event_id}/similar

⸻

2. Numeric Returns (Market Data Domain)

Stored in the asset_returns table.

Inserted via Yahoo Finance:
• BTC-USD
• ETH-USD
• XMR-USD

Schema:

(symbol TEXT,
as_of TIMESTAMPTZ,
horizon_minutes INT,
realized_return DOUBLE PRECISION,
price_start DOUBLE PRECISION,
price_end DOUBLE PRECISION)

Primary uniqueness constraint:

UNIQUE (symbol, as_of, horizon_minutes)

These two domains merge during forecasting.

⸻

Forecasting Pipeline Phases

⸻

PHASE 1 — Backfill Numeric Returns (Complete)

📄 File: backend/ingest/backfill_crypto_returns.py

Responsibilities: 1. Download daily OHLC for 365+ days. 2. Convert timestamps → UTC. 3. For each consecutive (t0 → t1):
• realized_return = (p1/p0) − 1
• insert via insert_asset_return() 4. Store rows in asset_returns.

This phase populates the numeric “tape.”

Status: ✔ Complete

⸻

PHASE 2 — Feature Extraction

This phase builds model features from both numeric & semantic data.

There are three feature groups:

⸻

A. Price Features (Numeric)

📄 File: backend/signals/price_context.py

Function to implement:

def build_price_features(symbol: str, as_of: datetime) -> Dict[str, float]:

Features:
• previous 1-day return
• 3-day / 7-day / 14-day / 30-day cumulative returns
• rolling volatility
• rolling z-score
• momentum proxies
• max drawdown window

Inputs: asset_returns
Outputs: numeric dict

⸻

B. Event Embedding Features (Semantic)

📄 File: backend/signals/context_window.py

Function to implement:

def build_event_features(symbol: str, as_of: datetime) -> Dict[str, float]:

Features:
• count of events in last 1d / 3d / 7d
• share of AI-related events
• distinct sources
• hours since last event
• aggregate embedding statistics (Phase 3+)
• similarity to “trend up” and “trend down” centroids (future work)

These features connect semantic activity to the numeric world.

⸻

C. Regime Classification (Optional but Recommended)

📄 File: backend/models/regime_classifier.py

Goal: label market regime around as_of:
• uptrend
• downtrend
• chop / consolidation
• high-volatility

API:

def classify_regime(symbol: str, as_of: datetime) -> str:

Used as a categorical input to future ML models.

⸻

PHASE 3 — Forecasting Models

📂 Directory: backend/models/

Two forecasters are used in parallel:

⸻

1. Naive Baseline Forecaster

📄 models/naive_asset_forecaster.py

Purpose: sanity check.

pred_return = mean(last_N_realized_returns)

API:

def forecast_asset(symbol: str, as_of: datetime, horizon_minutes: int, lookback_days: int = 60) -> ForecastResult

If ML cannot beat this → model is wrong.

⸻

2. Event Return Forecaster (Semantic → Numeric Conditioning)

📄 models/event_return_forecaster.py

Steps: 1. Take given event_id 2. Find k nearest events via pgvector 3. For each neighbor, fetch the asset’s realized return after its timestamp 4. Weight each return by exp(−α \* distance) 5. Compute:
• expected_return
• std_return
• p_up / p_down
• neighbor count

API:

def forecast_event_return(event_id, symbol, horizon_minutes, ...)

This is the first “semantic markets” signal.

⸻

PHASE 4 — Forecast API Endpoint

📄 File: backend/app.py

Add:

1. Baseline Asset Endpoint

GET /forecast/asset?symbol=BTC-USD&horizon_minutes=1440

Output:

{
"symbol": "BTC-USD",
"horizon_minutes": 1440,
"mean_return": ...,
"std_return": ...,
"p_up": ...,
"p_down": ...,
"sample_size": ...
}

2. Event-Conditioned Endpoint

GET /forecast/event/{event_id}?symbol=BTC-USD

Output:

{
"event_id": "...",
"symbol": "BTC-USD",
"expected_return": ...,
"std_return": ...,
"p_up": ...,
"p_down": ...,
"sample_size": ...,
"neighbors_used": ...
}

This merges price action + semantic similarity.

⸻

PHASE 5 — Event + Price Fusion (Future Work)

The ultimate goal:
A hybrid model that conditions price forecasts on semantic meaning.

Work required: 1. PCA or pooling of event embeddings 2. Vectorized event context window 3. Combine with numeric features 4. Fit ML model (RandomForest, XGBoost) 5. Predict:
• expected_return
• confidence
• direction

This unlocks behavior such as:

“AI regulation headlines tend to depress ETH on next-day returns.”

This is the foundation of a true semantic markets engine.

⸻

File Structure Summary

backend/
│
├── app.py
├── db.py
├── embeddings.py
│
├── ingest/
│ ├── rss_ingest.py
│ └── backfill_crypto_returns.py
│
├── numeric/
│ └── asset_returns.py
│
├── signals/
│ ├── price_context.py
│ ├── context_window.py
│ ├── feature_extractor.py
│ ├── matchup_signals.py
│ ├── curry_signals.py
│ ├── fatigue_signals.py
│ └── team_news_signals.py
│
└── models/
├── naive_asset_forecaster.py
├── event_return_forecaster.py
└── regime_classifier.py

⸻

Key Implementation Rules 1. Use UTC everywhere. 2. Never use future information (strict timestamp discipline). 3. Event → price alignment always uses the event timestamp. 4. Embeddings must be generated from clean_text. 5. Numeric returns must maintain

UNIQUE(symbol, as_of, horizon_minutes)

    6.	Baseline numeric model first, ML model second.
    7.	Limit semantic features to past events only.
    8.	Avoid leaking future prices when building features.
    9.	Keep the system modular so new assets / event sources are trivial to add.

⸻

End of Document

This markdown file is self-contained, authoritative, and sufficient for a future LLM to fully reconstruct the forecaster system without needing historical chat context.

Let me know if you want a TRAINING_PLAN.md, API_SPEC.md, or ARCHITECTURE_DIAGRAM.md.
