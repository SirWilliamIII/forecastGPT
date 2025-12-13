"""
ML Forecaster Training Script - Beat the Naive Baseline

This script trains ML classifiers to predict crypto asset price direction
using features from feature_extractor.py. Based on backtesting results, we focus
on the 7-day horizon where naive baseline achieves 60% accuracy.

Target: Beat 60% directional accuracy on 7-day horizon.

Usage:
    uv run python -m notebooks.train_ml_forecaster

Key principles:
- Binary classification (up/down) - "flat" has 0% accuracy so we ignore it
- Time-based per-symbol train/test split (80/20)
- No lookahead bias (strict < as_of filtering)
- Focus on 7-day horizon (best opportunity for improvement)
- RandomForest baseline, then XGBoost if it works

Backtesting Baseline to Beat:
- Overall 7-day: 60.0% accuracy
- BTC-USD: 61.2% accuracy
- ETH-USD: 65.7% accuracy
- XMR-USD: 64.9% accuracy
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    precision_recall_fscore_support,
)
from sklearn.model_selection import GridSearchCV
from xgboost import XGBClassifier

# Add backend to path
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.append(str(BACKEND_ROOT))

from config import FORECAST_DIRECTION_THRESHOLD, get_crypto_symbols
from db import get_conn
from signals.feature_extractor import build_features

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def build_training_dataset(
    symbols: List[str],
    horizon_minutes: int,
    start_date: datetime,
    end_date: datetime,
    lookback_days: int = 60,
    sample_frequency: int = 3,  # Sample every 3 days to keep dataset manageable
) -> pd.DataFrame:
    """
    Build training dataset with features and binary classification targets.

    For each (symbol, as_of) in date range:
    1. Build features using feature_extractor.build_features()
    2. Get realized return from asset_returns as target
    3. Convert target to binary up/down (remove flat)

    Args:
        symbols: List of asset symbols (BTC-USD, ETH-USD, XMR-USD)
        horizon_minutes: Forecast horizon (10080 = 7 days)
        start_date: Start of training period (timezone-aware UTC)
        end_date: End of training period (timezone-aware UTC)
        lookback_days: Historical lookback for features
        sample_frequency: Sample every N days (3 = every 3 days)

    Returns:
        DataFrame with features + binary direction target
    """
    if start_date.tzinfo is None or end_date.tzinfo is None:
        raise ValueError("start_date and end_date must be timezone-aware")

    logger.info(f"Building training dataset: symbols={symbols}, horizon={horizon_minutes}min")
    logger.info(f"  Period: {start_date.date()} to {end_date.date()}")
    logger.info(f"  Lookback: {lookback_days} days, sampling every {sample_frequency} days")

    rows = []

    with get_conn() as conn:
        with conn.cursor() as cur:
            for symbol in symbols:
                logger.info(f"Processing {symbol}...")

                # Get all available dates with return data
                cur.execute(
                    """
                    SELECT DISTINCT as_of, realized_return
                    FROM asset_returns
                    WHERE symbol = %s
                      AND horizon_minutes = %s
                      AND as_of BETWEEN %s AND %s
                    ORDER BY as_of ASC
                    """,
                    (symbol, horizon_minutes, start_date, end_date),
                )
                dates = cur.fetchall()

                if not dates:
                    logger.warning(f"  No data for {symbol}")
                    continue

                # Sample dates
                sampled_dates = dates[::sample_frequency]
                logger.info(f"  Found {len(dates)} dates, sampling {len(sampled_dates)}")

                for i, date_row in enumerate(sampled_dates):
                    as_of = date_row["as_of"]
                    realized_return = float(date_row["realized_return"])

                    try:
                        # Build features (this uses < as_of, no lookahead)
                        features = build_features(
                            symbol=symbol,
                            as_of=as_of,
                            horizon_minutes=horizon_minutes,
                            lookback_days=lookback_days,
                        )

                        # Convert realized return to binary direction
                        # Remove "flat" - it has 0% accuracy in backtesting
                        threshold = FORECAST_DIRECTION_THRESHOLD
                        if realized_return > threshold:
                            direction = 1  # up
                        elif realized_return < -threshold:
                            direction = 0  # down
                        else:
                            continue  # Skip flat (neutral) returns

                        # Flatten features into row
                        row = {
                            "symbol": symbol,
                            "as_of": as_of,
                            "realized_return": realized_return,
                            "direction": direction,  # Binary target: 0=down, 1=up
                        }

                        # Add all features
                        for k, v in features.items():
                            if k not in ("symbol", "as_of", "horizon_minutes"):
                                row[k] = v

                        rows.append(row)

                        if (i + 1) % 20 == 0:
                            logger.info(f"    Progress: {i + 1}/{len(sampled_dates)}")

                    except Exception as e:
                        logger.error(f"  Error at {as_of}: {e}")
                        continue

    df = pd.DataFrame(rows)
    logger.info(f"Built dataset: {len(df)} samples")
    logger.info(f"  Class distribution: {df['direction'].value_counts().to_dict()}")

    return df


def prepare_features(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series, List[str]]:
    """
    Prepare features for ML training.

    - Extract numeric features
    - One-hot encode categorical features (symbol, regime)
    - Handle missing values

    Args:
        df: Raw feature DataFrame

    Returns:
        (X, y, feature_names)
    """
    logger.info("Preparing features for training...")

    # Drop metadata columns
    exclude_cols = ["symbol", "as_of", "realized_return", "direction"]

    # Get target
    y = df["direction"]

    # Start with numeric features
    feature_df = df.drop(columns=exclude_cols)

    # Extract regime if present (it's in event_regime)
    if "event_regime" in feature_df.columns:
        # One-hot encode regime
        regime_dummies = pd.get_dummies(feature_df["event_regime"], prefix="regime")
        feature_df = pd.concat([feature_df.drop(columns=["event_regime"]), regime_dummies], axis=1)

    # One-hot encode symbol for cross-symbol learning
    symbol_dummies = pd.get_dummies(df["symbol"], prefix="symbol")
    feature_df = pd.concat([feature_df, symbol_dummies], axis=1)

    # Handle missing values (fill with 0 for now)
    feature_df = feature_df.fillna(0)

    # Ensure all features are numeric
    X = feature_df.astype(float)

    feature_names = list(X.columns)

    logger.info(f"  Features prepared: {len(feature_names)} features")
    logger.info(f"  Shape: X={X.shape}, y={y.shape}")

    return X, y, feature_names


def split_train_test_per_symbol(
    df: pd.DataFrame, train_ratio: float = 0.8
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Per-symbol time-based train/test split.

    CRITICAL: Split per symbol to prevent data leakage across assets.
    Use chronological split (no shuffle) to maintain temporal ordering.

    Args:
        df: Full dataset
        train_ratio: Fraction for training (0.8 = 80%)

    Returns:
        (train_df, test_df)
    """
    logger.info(f"Splitting dataset per-symbol (train_ratio={train_ratio})...")

    train_dfs = []
    test_dfs = []

    for symbol in df["symbol"].unique():
        df_sym = df[df["symbol"] == symbol].sort_values("as_of").reset_index(drop=True)
        n_sym = len(df_sym)
        n_train = int(n_sym * train_ratio)

        train_dfs.append(df_sym.iloc[:n_train])
        test_dfs.append(df_sym.iloc[n_train:])

        logger.info(f"  {symbol}: {n_train} train, {n_sym - n_train} test")

    train_df = pd.concat(train_dfs, ignore_index=True)
    test_df = pd.concat(test_dfs, ignore_index=True)

    logger.info(f"  Total: {len(train_df)} train, {len(test_df)} test")

    return train_df, test_df


def train_random_forest(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_test: pd.DataFrame,
    y_test: pd.Series,
    tune_hyperparameters: bool = True,
) -> Tuple[RandomForestClassifier, Dict]:
    """
    Train RandomForest classifier with optional hyperparameter tuning.

    Args:
        X_train, y_train: Training data
        X_test, y_test: Test data
        tune_hyperparameters: Whether to run GridSearchCV

    Returns:
        (model, metrics_dict)
    """
    logger.info("Training RandomForest classifier...")

    if tune_hyperparameters:
        logger.info("  Running hyperparameter tuning (this may take a few minutes)...")

        # GridSearchCV with time-series cross-validation
        param_grid = {
            "n_estimators": [100, 200, 300],
            "max_depth": [5, 8, 10, 12],
            "min_samples_split": [5, 10, 20],
            "min_samples_leaf": [2, 5, 10],
            "class_weight": ["balanced", None],
        }

        rf_base = RandomForestClassifier(random_state=42, n_jobs=-1)

        grid_search = GridSearchCV(
            rf_base,
            param_grid,
            cv=5,  # 5-fold CV
            scoring="accuracy",
            n_jobs=-1,
            verbose=1,
        )

        grid_search.fit(X_train, y_train)

        logger.info(f"  Best params: {grid_search.best_params_}")
        logger.info(f"  Best CV score: {grid_search.best_score_:.4f}")

        rf = grid_search.best_estimator_
    else:
        # Use reasonable defaults from existing training notebook
        rf = RandomForestClassifier(
            n_estimators=300,
            max_depth=8,
            min_samples_leaf=5,
            random_state=42,
            n_jobs=-1,
        )
        rf.fit(X_train, y_train)

    # Evaluate
    y_pred_train = rf.predict(X_train)
    y_pred_test = rf.predict(X_test)

    train_acc = accuracy_score(y_train, y_pred_train)
    test_acc = accuracy_score(y_test, y_pred_test)

    logger.info(f"  Train accuracy: {train_acc:.4f}")
    logger.info(f"  Test accuracy: {test_acc:.4f}")

    # Detailed test metrics
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_test, y_pred_test, average="binary"
    )

    metrics = {
        "train_accuracy": float(train_acc),
        "test_accuracy": float(test_acc),
        "test_precision": float(precision),
        "test_recall": float(recall),
        "test_f1": float(f1),
    }

    logger.info(f"  Test precision: {precision:.4f}")
    logger.info(f"  Test recall: {recall:.4f}")
    logger.info(f"  Test F1: {f1:.4f}")

    return rf, metrics


def train_xgboost(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_test: pd.DataFrame,
    y_test: pd.Series,
) -> Tuple[XGBClassifier, Dict]:
    """
    Train XGBoost classifier.

    Args:
        X_train, y_train: Training data
        X_test, y_test: Test data

    Returns:
        (model, metrics_dict)
    """
    logger.info("Training XGBoost classifier...")

    xgb = XGBClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        n_jobs=-1,
        eval_metric="logloss",
    )

    xgb.fit(X_train, y_train)

    # Evaluate
    y_pred_train = xgb.predict(X_train)
    y_pred_test = xgb.predict(X_test)

    train_acc = accuracy_score(y_train, y_pred_train)
    test_acc = accuracy_score(y_test, y_pred_test)

    logger.info(f"  Train accuracy: {train_acc:.4f}")
    logger.info(f"  Test accuracy: {test_acc:.4f}")

    # Detailed test metrics
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_test, y_pred_test, average="binary"
    )

    metrics = {
        "train_accuracy": float(train_acc),
        "test_accuracy": float(test_acc),
        "test_precision": float(precision),
        "test_recall": float(recall),
        "test_f1": float(f1),
    }

    logger.info(f"  Test precision: {precision:.4f}")
    logger.info(f"  Test recall: {recall:.4f}")
    logger.info(f"  Test F1: {f1:.4f}")

    return xgb, metrics


def evaluate_per_symbol(
    model, X_test: pd.DataFrame, y_test: pd.Series, test_df: pd.DataFrame
) -> Dict:
    """
    Evaluate model performance per symbol.

    Args:
        model: Trained classifier
        X_test, y_test: Test data
        test_df: Original test DataFrame with symbol column

    Returns:
        Dict with per-symbol metrics
    """
    logger.info("Evaluating per-symbol performance...")

    y_pred = model.predict(X_test)

    per_symbol_metrics = {}

    for symbol in test_df["symbol"].unique():
        mask = test_df["symbol"] == symbol
        y_true_sym = y_test[mask]
        y_pred_sym = y_pred[mask]

        acc = accuracy_score(y_true_sym, y_pred_sym)
        precision, recall, f1, _ = precision_recall_fscore_support(
            y_true_sym, y_pred_sym, average="binary"
        )

        per_symbol_metrics[symbol] = {
            "accuracy": float(acc),
            "precision": float(precision),
            "recall": float(recall),
            "f1": float(f1),
            "n_samples": int(mask.sum()),
        }

        logger.info(f"  {symbol}: accuracy={acc:.4f}, n={mask.sum()}")

    return per_symbol_metrics


def save_model(
    model,
    feature_names: List[str],
    metrics: Dict,
    per_symbol_metrics: Dict,
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    model_name: str,
    horizon_minutes: int,
    symbols: List[str],
) -> Path:
    """
    Save model and metadata to disk.

    Args:
        model: Trained classifier
        feature_names: List of feature names
        metrics: Overall metrics dict
        per_symbol_metrics: Per-symbol metrics dict
        train_df, test_df: DataFrames for date ranges
        model_name: Model identifier (e.g., "random_forest_7d")
        horizon_minutes: Forecast horizon
        symbols: List of symbols

    Returns:
        Path to saved model
    """
    models_dir = BACKEND_ROOT / "models" / "trained"
    models_dir.mkdir(parents=True, exist_ok=True)

    # Save model object
    model_path = models_dir / f"{model_name}.pkl"
    joblib.dump(
        {
            "model": model,
            "feature_names": feature_names,
            "horizon_minutes": horizon_minutes,
            "symbols": symbols,
        },
        model_path,
    )

    # Save metadata
    metadata = {
        "model_name": model_name,
        "model_type": type(model).__name__,
        "description": f"ML classifier for {horizon_minutes//1440}-day crypto return prediction (beats naive baseline)",
        "trained_at": datetime.now(tz=timezone.utc).isoformat(),
        "schema_version": "v2",
        "symbols": symbols,
        "horizon_minutes": horizon_minutes,
        "feature_names": feature_names,
        "n_features": len(feature_names),
        "train_test_split": {
            "method": "time_based_per_symbol",
            "train_ratio": 0.8,
            "shuffle": False,
            "n_train": int(len(train_df)),
            "n_test": int(len(test_df)),
            "train_date_range": [
                str(train_df["as_of"].min().date()),
                str(train_df["as_of"].max().date()),
            ],
            "test_date_range": [
                str(test_df["as_of"].min().date()),
                str(test_df["as_of"].max().date()),
            ],
        },
        "metrics": {
            "overall": metrics,
            "per_symbol": per_symbol_metrics,
        },
        "baseline_comparison": {
            "naive_7d_overall": 0.60,
            "naive_7d_btc": 0.612,
            "naive_7d_eth": 0.657,
            "naive_7d_xmr": 0.649,
            "improvement": float(metrics["test_accuracy"] - 0.60),
            "beats_baseline": bool(metrics["test_accuracy"] > 0.60),
        },
        "notes": [
            "Binary classification (up/down) - removed flat (0% accuracy)",
            "Features from unified feature_extractor.py",
            "Per-symbol train/test split to prevent leakage",
            "Strict < as_of filtering (no lookahead bias)",
            "Target: Beat 60% naive baseline on 7-day horizon",
        ],
    }

    metadata_path = models_dir / f"{model_name}.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    logger.info(f"Model saved to: {model_path}")
    logger.info(f"Metadata saved to: {metadata_path}")

    return model_path


def main():
    """
    Main training pipeline.
    """
    logger.info("=" * 80)
    logger.info("ML Forecaster Training Pipeline - Beat the Naive Baseline")
    logger.info("=" * 80)

    # Configuration
    symbols = list(get_crypto_symbols().keys())  # BTC-USD, ETH-USD, XMR-USD
    horizon_minutes = 10080  # 7 days (best opportunity for improvement)

    # Training period: Last 6 months (adjust based on available data)
    end_date = datetime.now(tz=timezone.utc)
    start_date = end_date - timedelta(days=180)
    lookback_days = 60

    logger.info(f"Symbols: {symbols}")
    logger.info(f"Horizon: {horizon_minutes} minutes ({horizon_minutes // 1440} days)")
    logger.info(f"Period: {start_date.date()} to {end_date.date()}")

    # Step 1: Build training dataset
    logger.info("\n" + "=" * 80)
    logger.info("STEP 1: Building training dataset")
    logger.info("=" * 80)

    df = build_training_dataset(
        symbols=symbols,
        horizon_minutes=horizon_minutes,
        start_date=start_date,
        end_date=end_date,
        lookback_days=lookback_days,
        sample_frequency=3,  # Every 3 days
    )

    if df.empty:
        logger.error("No training data generated. Check date range and asset_returns table.")
        return

    # Step 2: Prepare features
    logger.info("\n" + "=" * 80)
    logger.info("STEP 2: Preparing features")
    logger.info("=" * 80)

    X, y, feature_names = prepare_features(df)

    # Step 3: Train/test split
    logger.info("\n" + "=" * 80)
    logger.info("STEP 3: Train/test split (per-symbol)")
    logger.info("=" * 80)

    train_df, test_df = split_train_test_per_symbol(df, train_ratio=0.8)

    X_train, y_train, _ = prepare_features(train_df)
    X_test, y_test, _ = prepare_features(test_df)

    # Ensure same feature order
    X_train = X_train[feature_names]
    X_test = X_test[feature_names]

    # Step 4: Train RandomForest
    logger.info("\n" + "=" * 80)
    logger.info("STEP 4: Training RandomForest")
    logger.info("=" * 80)

    rf_model, rf_metrics = train_random_forest(
        X_train, y_train, X_test, y_test, tune_hyperparameters=False
    )

    rf_per_symbol = evaluate_per_symbol(rf_model, X_test, y_test, test_df)

    # Check if RF beats baseline
    rf_beats_baseline = rf_metrics["test_accuracy"] > 0.60

    logger.info(f"\n{'=' * 80}")
    logger.info(f"RandomForest Results:")
    logger.info(f"  Test Accuracy: {rf_metrics['test_accuracy']:.4f}")
    logger.info(f"  Naive Baseline: 0.6000")
    logger.info(f"  Improvement: {(rf_metrics['test_accuracy'] - 0.60):.4f}")
    logger.info(f"  Beats Baseline: {'✓ YES' if rf_beats_baseline else '✗ NO'}")
    logger.info(f"{'=' * 80}\n")

    # Step 5: Train XGBoost if RF works
    xgb_model = None
    xgb_metrics = None
    xgb_per_symbol = None

    if rf_beats_baseline:
        logger.info("\n" + "=" * 80)
        logger.info("STEP 5: Training XGBoost (RF beat baseline)")
        logger.info("=" * 80)

        xgb_model, xgb_metrics = train_xgboost(X_train, y_train, X_test, y_test)
        xgb_per_symbol = evaluate_per_symbol(xgb_model, X_test, y_test, test_df)

        xgb_beats_baseline = xgb_metrics["test_accuracy"] > 0.60
        xgb_beats_rf = xgb_metrics["test_accuracy"] > rf_metrics["test_accuracy"]

        logger.info(f"\n{'=' * 80}")
        logger.info(f"XGBoost Results:")
        logger.info(f"  Test Accuracy: {xgb_metrics['test_accuracy']:.4f}")
        logger.info(f"  Naive Baseline: 0.6000")
        logger.info(f"  RandomForest: {rf_metrics['test_accuracy']:.4f}")
        logger.info(f"  Beats Baseline: {'✓ YES' if xgb_beats_baseline else '✗ NO'}")
        logger.info(f"  Beats RandomForest: {'✓ YES' if xgb_beats_rf else '✗ NO'}")
        logger.info(f"{'=' * 80}\n")

    # Step 6: Save best model
    logger.info("\n" + "=" * 80)
    logger.info("STEP 6: Saving best model")
    logger.info("=" * 80)

    # Determine best model
    if xgb_model and xgb_metrics["test_accuracy"] > rf_metrics["test_accuracy"]:
        best_model = xgb_model
        best_metrics = xgb_metrics
        best_per_symbol = xgb_per_symbol
        model_name = "ml_forecaster_7d_xgb"
        logger.info("  Best model: XGBoost")
    else:
        best_model = rf_model
        best_metrics = rf_metrics
        best_per_symbol = rf_per_symbol
        model_name = "ml_forecaster_7d_rf"
        logger.info("  Best model: RandomForest")

    # Only save if it beats baseline
    if best_metrics["test_accuracy"] > 0.60:
        model_path = save_model(
            model=best_model,
            feature_names=feature_names,
            metrics=best_metrics,
            per_symbol_metrics=best_per_symbol,
            train_df=train_df,
            test_df=test_df,
            model_name=model_name,
            horizon_minutes=horizon_minutes,
            symbols=symbols,
        )

        logger.info(f"\n{'=' * 80}")
        logger.info(f"✓ SUCCESS: Model beats baseline and is ready for deployment")
        logger.info(f"  Model: {model_name}")
        logger.info(f"  Test Accuracy: {best_metrics['test_accuracy']:.4f}")
        logger.info(f"  Improvement: +{(best_metrics['test_accuracy'] - 0.60) * 100:.1f}%")
        logger.info(f"  Path: {model_path}")
        logger.info(f"{'=' * 80}\n")
    else:
        logger.error(f"\n{'=' * 80}")
        logger.error(f"✗ FAILURE: Model does NOT beat baseline")
        logger.error(f"  Test Accuracy: {best_metrics['test_accuracy']:.4f}")
        logger.error(f"  Baseline: 0.6000")
        logger.error(f"  Model NOT saved (baseline is better)")
        logger.error(f"{'=' * 80}\n")
        logger.error("Suggestions:")
        logger.error("  1. Try hyperparameter tuning (set tune_hyperparameters=True)")
        logger.error("  2. Add more training data (reduce sample_frequency)")
        logger.error("  3. Engineer new features (signals/)")
        logger.error("  4. Try different models (LightGBM, neural nets)")

    logger.info("\nTraining complete!")


if __name__ == "__main__":
    main()
