Here you go — a clean, durable, context-window-friendly .md file you can drop directly into your repo as:

FORECASTER_PLAN.md

No fluff, no jokes, no ambiguity — just the system-level plan Codex/future-ChatGPT can reload instantly and continue from.

⸻

BloombergGPT Forecaster Pipeline — Master Plan

This document defines the architecture, phases, responsibilities, and file structure for the forecasting system built on top of the semantic events + numeric markets engine.

It is designed so a future LLM (Codex, GPT, etc.) can instantly reconstruct the system and continue development without depending on prior conversation context.

⸻

Objectives 1. Collect real numeric market returns. 2. Build features from:
• price history
• event embeddings
• simple statistical signals 3. Train a return forecaster for assets (BTC, ETH, XMR initially). 4. Expose predictions via FastAPI. 5. Integrate semantic events with numeric forecasting.

Everything below outlines how each objective is achieved.

⸻

System Overview

The system has two major data domains:

1. Events (Semantic Text)
   • Stored in events table via RSS ingestion.
   • Each event has:
   • id, timestamp, source, url
   • raw_text, clean_text
   • pgvector embed
   • /events/{id}/similar uses only pgvector cosine distance.

2. Numeric Returns (Market Data)
   • Stored in asset_returns
   • Inserted via Yahoo Finance:
   • BTC-USD
   • ETH-USD
   • XMR-USD
   • Structure:

(symbol, as_of, horizon_minutes, realized_return, price_start, price_end)

These two domains merge during forecasting.

⸻

Forecasting Pipeline Phases

———————––

PHASE 1 — Backfill Numeric Returns

📂 File: backend/ingest/backfill_crypto_returns.py 1. Download daily OHLC data for 365+ days. 2. Convert timestamps to UTC. 3. For each consecutive pair (t0 → t1):
• compute realized_return = (p1/p0) - 1
• insert a row into asset_returns 4. Use insert_asset_return() in numeric/asset_returns.py

Status: Complete.

⸻

———————––

PHASE 2 — Feature Extraction

This phase turns raw data into model inputs.

There are 3 feature groups:

⸻

A. Price Features

📂 File: backend/signals/price_context.py

Create:

def build_price_features(symbol: str, as_of: datetime) -> Dict[str, float]:

Features include:
• previous 1-day return
• 3-day cumulative return
• 7-day cumulative return
• 14-day cumulative return
• rolling volatility windows
• rolling z-score
• simple momentum signals

These operate only on the numeric asset_returns table.

⸻

B. Event Embedding Features

📂 File: backend/signals/context_window.py

Create:

def build_event_features(symbol: str, as_of: datetime) -> Dict[str, float]:

Use pgvector search to get:
• closest event before as_of
• average embedding of events from as_of - 24h
• cosine similarity vs:
• uptrend centroid
• downtrend centroid
(computed later)

These vectors are flattened into numeric features (e.g., PCA-reduced or top-k dims).

⸻

C. Regime Classification

📂 File: backend/models/regime_classifier.py

Micro-model that labels recent price regime:
• uptrend
• downtrend
• chop

Compute using moving average crosses, volatility features, z-score.

Expose:

def classify_regime(symbol: str, as_of: datetime) -> str:

Used as a categorical feature.

⸻

———————––

PHASE 3 — Forecaster Model

📂 backend/models/event_return_forecaster.py

Two models:

⸻

1. Baseline Model

A naive predictor used for sanity checks:

pred_return = average(last_N_returns)

If your ML model can’t beat this, something is wrong.

⸻

2. ML Model

Start simple:
• RandomForestRegressor
or
• XGBoost

Inputs = price features + event features + regime

Outputs:

{
"expected_return": float,
"confidence": float,
"direction": "up" | "down"
}

Model training is offline (Jupyter or script), then serialized.

⸻

———————––

PHASE 4 — Forecast API Endpoint

Add to app.py:

GET /forecast/{symbol}

Returns:

{
"symbol": "BTC-USD",
"prediction_horizon_minutes": 1440,
"expected_return": 0.0124,
"confidence": 0.71,
"regime": "uptrend",
"features": {...}
}

This endpoint: 1. Loads trained forecaster 2. Gathers all features for now() 3. Produces prediction

⸻

———————––

PHASE 5 — Event + Price Fusion

The final step: link semantic meaning and numeric performance.

We combine:
• embedding directionality
• event density
• sentiment-like effects
• similarity to past impactful events

Model learns relationships such as:
“Negative AI regulation events correlated with next-day ETH dips.”

This is where semantic markets become possible.

⸻

File Structure Summary

backend/
app.py
db.py
embeddings.py

ingest/
rss_ingest.py
backfill_crypto_returns.py

numeric/
asset_returns.py

signals/
price_context.py
context_window.py
feature_extractor.py
matchup_signals.py
curry_signals.py
fatigue_signals.py
team_news_signals.py

models/
naive_asset_forecaster.py
event_return_forecaster.py
regime_classifier.py

⸻

Key Implementation Rules 1. Use UTC everywhere. 2. Never predict from the future. 3. Events are always matched to prices by timestamp. 4. Embeddings must be generated from clean_text. 5. Numeric returns must have unique (symbol, as_of, horizon). 6. Baseline first, ML second.

⸻

End of Document

This MD file is self-contained and fully reconstructs the forecaster plan, independent of any conversation history.

Put this in your repo; future LLMs will pick up instantly.
