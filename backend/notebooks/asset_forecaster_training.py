# %% [markdown]
# # Asset Return Forecaster — Training Notebook
#
# This notebook:
# - Loads historical returns from `asset_returns`
# - Adds simple numeric + event features
# - Trains a RandomForest baseline forecaster
# - Evaluates out-of-sample performance
# - Saves the model to `backend/models/trained/asset_return_rf.pkl`
#
# It uses:
# - Postgres (pgvector container) on localhost:5433
# - BTC-USD, ETH-USD, XMR-USD
# - horizon_minutes = 1440 (1-day)

# %%
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy import create_engine
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

# --- Path setup: assume this file lives in backend/notebooks/ ---
BACKEND_ROOT = os.path.abspath(os.path.join(os.getcwd(), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.append(BACKEND_ROOT)

# Optional: reuse db utilities if you want
# from db import get_conn

# %% [markdown]
# ## 1. Connect to Postgres
#
# Matches your docker-compose:
# - host: 127.0.0.1
# - port: 5433
# - db: semantic_markets
# - user/pass: semantic / semantic

# %%
engine = create_engine(
    "postgresql+psycopg://semantic:semantic@127.0.0.1:5433/semantic_markets",
    future=True,
)

# Quick sanity check
with engine.connect() as conn:
    ping = conn.exec_driver_sql("SELECT 1 AS ok").fetchone()
ping

# %% [markdown]
# ## 2. Load labeled examples
#
# Each training row is:
# - one row from `asset_returns`
# - with realized_return as the target
# - plus a simple event-count feature (how many events in last 24h)

# %%
symbols = ["BTC-USD", "ETH-USD", "XMR-USD"]
horizon_minutes = 1440

query = """
SELECT
    r.symbol,
    r.as_of,
    r.horizon_minutes,
    r.realized_return,
    r.price_start,
    r.price_end,
    -- IMPORTANT: Only count events BEFORE as_of to prevent lookahead bias
    -- Using < instead of <= to strictly enforce temporal ordering
    (
        SELECT COUNT(*)
        FROM events e
        WHERE e.timestamp >= r.as_of - INTERVAL '1 day'
          AND e.timestamp < r.as_of
    ) AS event_count_1d
FROM asset_returns r
WHERE r.horizon_minutes = %(horizon)s
  AND r.symbol = ANY(%(symbols)s)
ORDER BY r.symbol, r.as_of;
"""

with engine.connect() as conn:
    df = pd.read_sql(
        query,
        conn,
        params={"horizon": horizon_minutes, "symbols": symbols},
    )

df.head()

# %% [markdown]
# ## 3. Feature engineering
#
# For each symbol, we create:
# - Lagged returns: ret_lag1, ret_lag2, ret_lag3
# - Rolling mean & vol: ma_5, ma_10, vol_5, vol_10
# - Raw event_count_1d
#
# Target = realized_return (1-day, already computed in `asset_returns`).

# %%
def build_features(df_raw: pd.DataFrame) -> pd.DataFrame:
    df_all = []

    for sym in df_raw["symbol"].unique():
        d = df_raw[df_raw["symbol"] == sym].copy()
        d = d.sort_values("as_of")

        # target
        d["target_return"] = d["realized_return"]

        # lagged returns
        d["ret_lag1"] = d["target_return"].shift(1)
        d["ret_lag2"] = d["target_return"].shift(2)
        d["ret_lag3"] = d["target_return"].shift(3)

        # rolling stats on target
        d["ma_5"] = d["target_return"].rolling(5).mean()
        d["ma_10"] = d["target_return"].rolling(10).mean()
        d["vol_5"] = d["target_return"].rolling(5).std()
        d["vol_10"] = d["target_return"].rolling(10).std()

        # keep event_count_1d as-is
        d_all = d.copy()
        df_all.append(d_all)

    df_feat = pd.concat(df_all, ignore_index=True)

    # Drop rows with NaNs from rolling / lags
    df_feat = df_feat.dropna().reset_index(drop=True)
    return df_feat


df_feat = build_features(df)
df_feat.head()

# %%
len(df_feat), df_feat["symbol"].value_counts()

# %% [markdown]
# ## 4. One-hot encode symbol
#
# Model gets:
# - numeric features
# - one-hot symbol columns: symbol_BTC-USD, symbol_ETH-USD, symbol_XMR-USD

# %%
df_model = df_feat.copy()

symbol_dummies = pd.get_dummies(df_model["symbol"], prefix="symbol")
df_model = pd.concat([df_model, symbol_dummies], axis=1)

# Define feature cols & target
target_col = "target_return"
exclude_cols = [
    "target_return",
    "realized_return",
    "symbol",
    "as_of",
]

feature_cols = [
    c
    for c in df_model.columns
    if c not in exclude_cols
]

X = df_model[feature_cols].astype(float)
y = df_model[target_col].astype(float)

X.head(), y.head()

# %% [markdown]
# ## 5. Train / test split (time-based, per-symbol)
#
# CRITICAL: Split per symbol to prevent data leakage across assets.
# Use the earliest 80% of observations as train, last 20% as test, **per symbol**.
# This ensures we respect temporal ordering within each asset.

# %%
# Time-based split per symbol to prevent leakage
train_dfs = []
test_dfs = []

for symbol in df_model["symbol"].unique():
    df_sym = df_model[df_model["symbol"] == symbol].sort_values("as_of").reset_index(drop=True)
    n_sym = len(df_sym)
    n_train_sym = int(n_sym * 0.8)

    train_dfs.append(df_sym.iloc[:n_train_sym])
    test_dfs.append(df_sym.iloc[n_train_sym:])

df_train = pd.concat(train_dfs, ignore_index=True)
df_test = pd.concat(test_dfs, ignore_index=True)

X_train = df_train[feature_cols].astype(float)
y_train = df_train[target_col].astype(float)
X_test = df_test[feature_cols].astype(float)
y_test = df_test[target_col].astype(float)

len(df_train), len(df_test), df_train["symbol"].value_counts()

# %% [markdown]
# ## 6. Train RandomForestRegressor
#
# This is a simple baseline ML model.
# (You can tune n_estimators, depth, etc later.)

# %%
rf = RandomForestRegressor(
    n_estimators=300,
    max_depth=8,
    min_samples_leaf=5,
    random_state=42,
    n_jobs=-1,
)

rf.fit(X_train, y_train)

# %% [markdown]
# ## 7. Evaluate
#
# We’ll compute:
# - MAE
# - RMSE
# - Directional accuracy (sign of return)

# %%
y_pred = rf.predict(X_test)

mae = mean_absolute_error(y_test, y_pred)
rmse = mean_squared_error(y_test, y_pred, squared=False)

# directional accuracy: sign(y) vs sign(pred)
sign_true = np.sign(y_test.values)
sign_pred = np.sign(y_pred)
direction_acc = (sign_true == sign_pred).mean()

metrics = {
    "n_train": len(X_train),
    "n_test": len(X_test),
    "mae": mae,
    "rmse": rmse,
    "directional_accuracy": direction_acc,
}
metrics

# %% [markdown]
# ## 8. Inspect per-symbol performance (optional)

# %%
df_eval = df_test.copy()
df_eval["y_true"] = y_test.values
df_eval["y_pred"] = y_pred
df_eval["sign_true"] = np.sign(df_eval["y_true"])
df_eval["sign_pred"] = np.sign(df_eval["y_pred"])
df_eval["direction_correct"] = df_eval["sign_true"] == df_eval["sign_pred"]

print("Per-symbol directional accuracy:")
print(df_eval.groupby("symbol")["direction_correct"].mean())

print("\nPer-symbol MAE:")
df_eval_grouped = df_eval.groupby("symbol").apply(
    lambda g: mean_absolute_error(g["y_true"], g["y_pred"])
)
print(df_eval_grouped)

# %% [markdown]
# ## 9. Save the trained model
#
# We’ll save to:
# - `backend/models/trained/asset_return_rf.pkl`
#
# so the runtime forecaster can later load it.

# %%
import json
from pathlib import Path
import joblib

models_dir = Path(BACKEND_ROOT) / "models" / "trained"
models_dir.mkdir(parents=True, exist_ok=True)

model_path = models_dir / "asset_return_rf.pkl"
joblib.dump(
    {
        "model": rf,
        "feature_cols": feature_cols,
        "horizon_minutes": horizon_minutes,
        "symbols": symbols,
    },
    model_path,
)

# Save metadata JSON
metadata = {
    "model_name": "asset_return_rf",
    "model_type": "RandomForestRegressor",
    "description": "Baseline ML forecaster for asset returns using lagged returns, rolling stats, and event count features",
    "trained_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
    "feature_version": "v1",
    "symbols": symbols,
    "metrics": ["return"],
    "horizons_minutes": [horizon_minutes],
    "feature_cols": feature_cols,
    "hyperparameters": {
        "n_estimators": 300,
        "max_depth": 8,
        "min_samples_leaf": 5,
        "random_state": 42,
    },
    "train_test_split": {
        "method": "time_based_per_symbol",
        "train_ratio": 0.8,
        "shuffle": False,
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "train_date_range": [
            str(df_train["as_of"].min().date()),
            str(df_train["as_of"].max().date()),
        ],
        "test_date_range": [
            str(df_test["as_of"].min().date()),
            str(df_test["as_of"].max().date()),
        ],
    },
    "metrics_eval": {
        "mae": float(mae),
        "rmse": float(rmse),
        "directional_accuracy": float(direction_acc),
    },
    "notes": [
        "Model trained on 1-day horizon returns",
        "One-hot encoding used for symbol",
        "Features use strict lookahead prevention (lag >= 1)",
        "To retrain, run: uv run python -m notebooks.asset_forecaster_training",
    ],
}

metadata_path = models_dir / "asset_return_rf.json"
with open(metadata_path, "w") as f:
    json.dump(metadata, f, indent=2)

print(f"Model saved to: {model_path}")
print(f"Metadata saved to: {metadata_path}")
model_path

# %% [markdown]
# ## 10. How to wire this into the app (notes)
#
# Later, in `backend/models/naive_asset_forecaster.py` (or a new file), you can:
#
# ```python
# import joblib
# from pathlib import Path
#
# _MODEL_PATH = Path(__file__).resolve().parent / "trained" / "asset_return_rf.pkl"
# _MODEL_OBJ = joblib.load(_MODEL_PATH)
# _RF = _MODEL_OBJ["model"]
# _FEATURE_COLS = _MODEL_OBJ["feature_cols"]
#
# def ml_return_forecast(symbol: str, as_of: datetime, horizon_minutes: int) -> ForecastResult:
#     # 1) build feature row for (symbol, as_of)
#     # 2) fill into a DataFrame with _FEATURE_COLS
#     # 3) call _RF.predict(...)
#     # 4) wrap result into your ForecastResult dataclass
#     ...
# ```
#
# That would give you:
# - `/forecast/asset` using ML instead of purely numeric baseline
# - and later, you can expand features to include richer event signals.
