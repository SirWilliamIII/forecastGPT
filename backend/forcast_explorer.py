# %% [markdown]
# # Event & Forecast Explorer
#
# - Browse recent events from `events`
# - Inspect semantic neighbors (pgvector)
# - Run naive numeric forecasts (BTC, ETH, XMR)
# - Run event-conditioned forecast for a chosen event

# %%
import os
import sys
from datetime import datetime, timezone
from uuid import UUID

import pandas as pd
from sqlalchemy import create_engine

# --- Path setup: assume this notebook lives in backend/notebooks ---
# CWD = backend/notebooks → parent = backend (where db.py, models/, etc live)
BACKEND_ROOT = os.path.abspath(os.path.join(os.getcwd(), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.append(BACKEND_ROOT)

# Now we can import backend modules
from db import get_conn
from models.naive_asset_forecaster import forecast_asset
from models.event_return_forecaster import forecast_event_return

# %%
# --- SQLAlchemy engine for pandas (cleaner than DB-API warnings) ---

engine = create_engine(
    "postgresql+psycopg://semantic:semantic@127.0.0.1:5432/semantic_markets",
    future=True,
)

# Quick sanity check (should show a few rows if things are wired correctly)
with engine.connect() as conn:
    df_events_preview = pd.read_sql(
        """
        SELECT id, timestamp, source, url, title
        FROM events
        ORDER BY timestamp DESC
        LIMIT 5
        """,
        conn,
    )

df_events_preview

# %%
# --- 1. Load recent events into a DataFrame ---

with engine.connect() as conn:
    df_events = pd.read_sql(
        """
        SELECT
            id,
            timestamp,
            source,
            url,
            title,
            summary,
            categories,
            tags
        FROM events
        ORDER BY timestamp DESC
        LIMIT 50
        """,
        conn,
    )

df_events.head(10)

# %%
# --- 2. Pick an event to explore ---

# Option A: manually eyeball df_events above and paste a UUID
# event_id = UUID("paste-a-uuid-here")

# Option B: just take the most recent one:
event_id = UUID(str(df_events.iloc[0]["id"]))
event_id

# %%
# --- 3. Inspect the anchor event in detail ---

with engine.connect() as conn:
    df_anchor = pd.read_sql(
        """
        SELECT
            id,
            timestamp,
            source,
            url,
            title,
            summary,
            categories,
            tags
        FROM events
        WHERE id = %(event_id)s
        """,
        conn,
        params={"event_id": str(event_id)},
    )

df_anchor

# %%
# --- 4. Find semantic nearest neighbors for this event (pgvector <->) ---

with engine.connect() as conn:
    df_neighbors = pd.read_sql(
        """
        WITH anchor AS (
            SELECT embed
            FROM events
            WHERE id = %(event_id)s
        )
        SELECT
            e.id,
            e.timestamp,
            e.source,
            e.url,
            e.title,
            e.categories,
            e.tags,
            e.embed <-> (SELECT embed FROM anchor) AS distance
        FROM events e
        WHERE e.id <> %(event_id)s
        ORDER BY e.embed <-> (SELECT embed FROM anchor)
        LIMIT 25
        """,
        conn,
        params={"event_id": str(event_id)},
    )

df_neighbors

# %%
# --- 5. Naive numeric forecast for BTC, ETH, XMR ---

as_of = datetime.now(tz=timezone.utc)
symbols = ["BTC-USD", "ETH-USD", "XMR-USD"]

rows = []
for sym in symbols:
    res = forecast_asset(
        symbol=sym,
        as_of=as_of,
        horizon_minutes=1440,
        lookback_days=60,
    )
    d = res.to_dict()
    rows.append(
        {
            "symbol": d["symbol"],
            "expected_return": d["mean_return"],
            "vol_return": d["vol_return"],
            "direction": d.get("direction"),
            "confidence": d.get("confidence"),
            "lookback_days": d["lookback_days"],
            "n_points": d["n_points"],
        }
    )

df_naive = pd.DataFrame(rows)
df_naive

# %%
# --- 6. Event-conditioned forecast for BTC-USD based on this event ---

event_forecast = forecast_event_return(
    event_id=event_id,
    symbol="BTC-USD",
    horizon_minutes=1440,
    k_neighbors=25,
    lookback_days=365,
    price_window_minutes=60,
    alpha=0.5,
)

event_forecast.__dict__

# %%
# --- 7. Compare naive vs event-conditioned for BTC-USD ---

baseline = forecast_asset(
    symbol="BTC-USD",
    as_of=datetime.now(tz=timezone.utc),
    horizon_minutes=1440,
    lookback_days=60,
).to_dict()

comparison = {
    "baseline_expected_return": baseline["mean_return"],
    "baseline_vol": baseline["vol_return"],
    "event_expected_return": event_forecast.expected_return,
    "event_vol": event_forecast.std_return,
    "event_p_up": event_forecast.p_up,
    "event_p_down": event_forecast.p_down,
    "event_sample_size": event_forecast.sample_size,
    "event_neighbors_used": event_forecast.neighbors_used,
}

pd.DataFrame([comparison])

# %%
# --- 8. (Optional) Inspect realized returns around neighbor events for BTC-USD ---

with engine.connect() as conn:
    neighbor_ids = df_neighbors["id"].tolist()

    df_returns = pd.read_sql(
        """
        SELECT
            e.id AS event_id,
            e.timestamp AS event_ts,
            r.symbol,
            r.as_of,
            r.horizon_minutes,
            r.realized_return
        FROM events e
        JOIN asset_returns r
          ON r.symbol = 'BTC-USD'
         AND r.as_of >= e.timestamp
         AND r.as_of < e.timestamp + interval '1 day'
        WHERE e.id = ANY(%(ids)s)
        ORDER BY e.timestamp, r.as_of
        """,
        conn,
        params={"ids": neighbor_ids},
    )

df_returns.head(20)
