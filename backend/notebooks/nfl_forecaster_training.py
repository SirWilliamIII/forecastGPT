# backend/notebooks/nfl_forecaster_training.py
"""
NFL Game Outcome Prediction - ML Training Pipeline

This pipeline trains a simple but robust model to predict NFL game outcomes
using structured historical data from the asset_returns table.

Architecture:
1. Load historical games from asset_returns (price_start=100, price_end=100+point_diff)
2. Engineer features: win%, points avg, point differential, recent form
3. Train LogisticRegression with strong regularization (small dataset: 15 games)
4. Evaluate with time-based split (no shuffle to prevent lookahead bias)
5. Serialize model + metadata for inference

Data Encoding:
- price_start: Always 100 (baseline)
- price_end: 100 + point_differential
- realized_return: 1.0 (win), -1.0 (loss), 0.0 (tie)

Success Criteria:
- Test accuracy > 50% (beat coin flip)
- Ideally > 55-60%
- Not severely overfit (train-test gap < 20%)
"""

import os
import sys
import pickle
import json
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Tuple, Optional
import warnings

import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    classification_report,
    confusion_matrix,
)

# Add parent directory to path for imports
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from db import get_conn
from config import NFL_BASELINE_SCORE

# Suppress warnings for cleaner output
warnings.filterwarnings("ignore")


def load_training_data(
    symbols: List[str] = None,
    min_games: int = 10,
) -> Tuple[pd.DataFrame, Dict]:
    """
    Load NFL game data from asset_returns table for multiple teams.

    Args:
        symbols: List of team symbols (e.g., ["NFL:DAL_COWBOYS", "NFL:NYG_GIANTS"])
        min_games: Minimum games required per team for training

    Returns:
        (dataframe, metadata) with columns:
            - game_date: Game timestamp
            - symbol: Team symbol
            - pts_for: Team's score
            - pts_against: Opponent's score
            - point_diff: pts_for - pts_against
            - is_win: Boolean outcome (1=win, 0=loss)
    """
    if symbols is None:
        symbols = [
            "NFL:DAL_COWBOYS",
            "NFL:NYG_GIANTS",
            "NFL:PHI_EAGLES",
            "NFL:WSH_COMMANDERS",
        ]

    print(f"Loading training data for {len(symbols)} teams...")
    print(f"Teams: {', '.join(symbols)}")

    # Load data for all teams
    all_data = []
    team_counts = {}

    with get_conn() as conn:
        with conn.cursor() as cur:
            for symbol in symbols:
                query = """
                SELECT
                    as_of as game_date,
                    symbol,
                    realized_return,
                    price_start,
                    price_end,
                    horizon_minutes
                FROM asset_returns
                WHERE symbol = %s
                ORDER BY as_of ASC
                """
                cur.execute(query, (symbol,))
                rows = cur.fetchall()

                # Convert psycopg3 Row objects to list of dicts
                for row in rows:
                    all_data.append({
                        "game_date": row["game_date"],
                        "symbol": row["symbol"],
                        "realized_return": float(row["realized_return"]),
                        "price_start": float(row["price_start"]),
                        "price_end": float(row["price_end"]),
                        "horizon_minutes": int(row["horizon_minutes"]),
                    })

                team_counts[symbol] = len(rows)
                print(f"  {symbol}: {len(rows)} games")

    df = pd.DataFrame(all_data)

    if len(df) == 0:
        raise ValueError(f"No games found for any team")

    # Check minimum games per team
    for symbol, count in team_counts.items():
        if count < min_games:
            print(f"  WARNING: {symbol} has only {count} games (< {min_games} required)")

    print(f"\nTotal games loaded: {len(df)}")

    # Decode the price encoding
    # price_start = NFL_BASELINE_SCORE (100)
    # price_end = NFL_BASELINE_SCORE + point_differential
    df["pts_against"] = NFL_BASELINE_SCORE  # Always 100
    df["pts_for"] = df["price_end"]
    df["point_diff"] = df["pts_for"] - df["pts_against"]

    # Extract target variable
    df["is_win"] = (df["realized_return"] > 0).astype(int)

    # Convert game_date to datetime if it's not already
    if not pd.api.types.is_datetime64_any_dtype(df["game_date"]):
        df["game_date"] = pd.to_datetime(df["game_date"])

    metadata = {
        "symbols": symbols,  # List of all team symbols
        "total_games": len(df),
        "date_range": (
            df["game_date"].min().isoformat(),
            df["game_date"].max().isoformat(),
        ),
        "wins": int(df["is_win"].sum()),
        "losses": int((df["is_win"] == 0).sum()),
        "win_rate": float(df["is_win"].mean()),
        "team_counts": team_counts,  # Games per team
    }

    print(f"  Found {len(df)} games")
    print(f"  Date range: {df['game_date'].min().date()} to {df['game_date'].max().date()}")
    print(f"  Record: {metadata['wins']}-{metadata['losses']} ({metadata['win_rate']:.1%} win rate)")

    return df, metadata


def engineer_features(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    """
    Engineer predictive features from historical game data.

    Features (computed per-team):
    - Rolling statistics (cumulative to avoid lookahead bias)
    - Win percentage (historical up to this game)
    - Points scored average
    - Points allowed average
    - Point differential average
    - Recent form (last 3 games win %)
    - Game count (experience proxy)

    Args:
        df: Game dataframe with symbol, game_date, pts_for, pts_against, is_win

    Returns:
        (feature_df, feature_names) - Features aligned with games
    """
    print("\nEngineering features...")

    # Check if we have multiple teams
    has_symbol = 'symbol' in df.columns
    if has_symbol:
        print(f"  Computing features for {df['symbol'].nunique()} teams")
        # Sort by team and date to ensure temporal ordering within each team
        df = df.sort_values(["symbol", "game_date"]).reset_index(drop=True)
    else:
        # Single team - sort by date only
        df = df.sort_values("game_date").reset_index(drop=True)

    # Initialize feature dataframe
    features = pd.DataFrame(index=df.index)

    # Compute features per-team if we have multiple teams
    if has_symbol:
        # Group by team and compute features separately
        for feature_name, compute_fn in [
            ("win_pct", lambda g: g["is_win"].expanding().mean().shift(1).fillna(0.5)),
            ("pts_for_avg", lambda g: g["pts_for"].expanding().mean().shift(1).fillna(g["pts_for"].mean())),
            ("pts_against_avg", lambda g: g["pts_against"].expanding().mean().shift(1).fillna(NFL_BASELINE_SCORE)),
            ("point_diff_avg", lambda g: g["point_diff"].expanding().mean().shift(1).fillna(0)),
            ("pts_for_std", lambda g: g["pts_for"].expanding().std().shift(1).fillna(0)),
            ("pts_against_std", lambda g: g["pts_against"].expanding().std().shift(1).fillna(0)),
        ]:
            features[feature_name] = df.groupby("symbol", group_keys=False).apply(compute_fn).values

        # Feature 5: Recent form (last 3 games win %) - per team
        def rolling_win_pct_last3(g):
            result = []
            series = g["is_win"].values
            for i in range(len(series)):
                if i == 0:
                    result.append(0.5)
                else:
                    window = series[max(0, i-3):i]
                    result.append(window.mean())
            return pd.Series(result, index=g.index)

        features["last3_win_pct"] = df.groupby("symbol", group_keys=False).apply(rolling_win_pct_last3).values

        # Feature 6: Games played (per team)
        features["games_played"] = df.groupby("symbol", group_keys=False).cumcount()

        # Feature 9: Win streak (per team)
        def calculate_win_streak(g):
            streaks = []
            current_streak = 0
            series = g["is_win"].values
            for i, val in enumerate(series):
                if i == 0:
                    streaks.append(0)
                else:
                    prev_win = series[i-1]
                    if prev_win == 1:
                        current_streak = max(0, current_streak) + 1
                    else:
                        current_streak = min(0, current_streak) - 1
                    streaks.append(current_streak)
            return pd.Series(streaks, index=g.index)

        features["win_streak"] = df.groupby("symbol", group_keys=False).apply(calculate_win_streak).values

    else:
        # Single team - use original logic
        features["win_pct"] = df["is_win"].expanding().mean().shift(1).fillna(0.5)
        features["pts_for_avg"] = df["pts_for"].expanding().mean().shift(1).fillna(df["pts_for"].mean())
        features["pts_against_avg"] = df["pts_against"].expanding().mean().shift(1).fillna(NFL_BASELINE_SCORE)
        features["point_diff_avg"] = df["point_diff"].expanding().mean().shift(1).fillna(0)
        features["pts_for_std"] = df["pts_for"].expanding().std().shift(1).fillna(0)
        features["pts_against_std"] = df["pts_against"].expanding().std().shift(1).fillna(0)

        def rolling_win_pct_last3(series):
            result = []
            for i in range(len(series)):
                if i == 0:
                    result.append(0.5)
                else:
                    window = series[max(0, i-3):i]
                    result.append(window.mean())
            return pd.Series(result, index=series.index)

        features["last3_win_pct"] = rolling_win_pct_last3(df["is_win"])
        features["games_played"] = range(len(df))

        def calculate_win_streak(series):
            streaks = []
            current_streak = 0
            for i, val in enumerate(series):
                if i == 0:
                    streaks.append(0)
                else:
                    prev_win = series.iloc[i-1]
                    if prev_win == 1:
                        current_streak = max(0, current_streak) + 1
                    else:
                        current_streak = min(0, current_streak) - 1
                    streaks.append(current_streak)
            return pd.Series(streaks, index=series.index)

        features["win_streak"] = calculate_win_streak(df["is_win"])

    # Handle any remaining NaN values
    features = features.fillna(0)

    feature_names = features.columns.tolist()

    print(f"  Created {len(feature_names)} features:")
    for i, name in enumerate(feature_names, 1):
        print(f"    {i}. {name}")

    # Validation: Check for lookahead bias by ensuring features are based on past data only
    # First game should have neutral/default features
    first_game_features = features.iloc[0]
    print(f"\n  First game features (should be neutral):")
    print(f"    {first_game_features.to_dict()}")

    return features, feature_names


def split_data(
    X: pd.DataFrame,
    y: pd.Series,
    game_dates: pd.Series,
    test_size: float = 0.2,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    Time-based train/test split (NO SHUFFLE).

    With 15 games and test_size=0.2:
    - Train: First 12 games (80%)
    - Test: Last 3 games (20%)

    Args:
        X: Feature matrix
        y: Target labels
        game_dates: Game dates for metadata
        test_size: Fraction for test set

    Returns:
        X_train, X_test, y_train, y_test, dates_train, dates_test
    """
    print(f"\nSplitting data (test_size={test_size})...")

    n = len(X)
    split_idx = int(n * (1 - test_size))

    X_train = X.iloc[:split_idx]
    X_test = X.iloc[split_idx:]
    y_train = y.iloc[:split_idx]
    y_test = y.iloc[split_idx:]
    dates_train = game_dates.iloc[:split_idx]
    dates_test = game_dates.iloc[split_idx:]

    print(f"  Train: {len(X_train)} games ({dates_train.min().date()} to {dates_train.max().date()})")
    print(f"  Test:  {len(X_test)} games ({dates_test.min().date()} to {dates_test.max().date()})")
    print(f"  Train win rate: {y_train.mean():.1%}")
    print(f"  Test win rate:  {y_test.mean():.1%}")

    return X_train, X_test, y_train, y_test, dates_train, dates_test


def train_model(
    X_train: pd.DataFrame,
    y_train: pd.Series,
) -> Tuple[LogisticRegression, StandardScaler]:
    """
    Train a simple but robust Logistic Regression model.

    Why LogisticRegression?
    - Simple and interpretable
    - Works well with small datasets (12-15 samples)
    - Strong regularization prevents overfitting
    - Provides feature importance via coefficients
    - Probabilistic outputs (win probability)

    Regularization:
    - L2 penalty (ridge)
    - C=0.1 (strong regularization for small data)

    Args:
        X_train: Training features
        y_train: Training labels

    Returns:
        (trained_model, fitted_scaler)
    """
    print("\nTraining Logistic Regression...")

    # Scale features (important for regularized models)
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)

    # Train model with strong regularization
    model = LogisticRegression(
        penalty="l2",
        C=0.1,  # Strong regularization (1/lambda)
        solver="lbfgs",
        max_iter=1000,
        random_state=42,
    )

    model.fit(X_train_scaled, y_train)

    print(f"  Model: LogisticRegression(C=0.1, penalty='l2')")
    print(f"  Training samples: {len(X_train)}")
    print(f"  Features: {len(X_train.columns)}")

    return model, scaler


def evaluate_model(
    model: LogisticRegression,
    scaler: StandardScaler,
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_test: pd.DataFrame,
    y_test: pd.Series,
    feature_names: List[str],
) -> Dict:
    """
    Comprehensive model evaluation.

    Metrics:
    - Accuracy (train and test)
    - Precision, Recall, F1
    - Confusion matrix
    - Feature importance

    Success criteria:
    - Test accuracy > 50% (beat coin flip)
    - Ideally > 55-60%
    - Not severely overfit (train vs test gap < 20%)

    Args:
        model: Trained model
        scaler: Fitted scaler
        X_train, y_train: Training data
        X_test, y_test: Test data
        feature_names: Feature names for importance

    Returns:
        Metrics dictionary
    """
    print("\n" + "="*60)
    print("MODEL EVALUATION")
    print("="*60)

    # Scale data
    X_train_scaled = scaler.transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    # Predictions
    y_pred_train = model.predict(X_train_scaled)
    y_pred_test = model.predict(X_test_scaled)

    # Training metrics
    train_acc = accuracy_score(y_train, y_pred_train)
    print(f"\nTraining Accuracy: {train_acc:.1%} ({int(train_acc * len(y_train))}/{len(y_train)} correct)")

    # Test metrics
    test_acc = accuracy_score(y_test, y_pred_test)
    print(f"Test Accuracy:     {test_acc:.1%} ({int(test_acc * len(y_test))}/{len(y_test)} correct)")

    # Overfitting check
    overfit_gap = train_acc - test_acc
    print(f"Overfit Gap:       {overfit_gap:+.1%}")
    if abs(overfit_gap) > 0.20:
        print("  ⚠️  WARNING: Significant overfitting detected (>20% gap)")
    else:
        print("  ✓ Acceptable generalization")

    # Detailed test set metrics
    print("\n" + "-"*60)
    print("Test Set Classification Report:")
    print("-"*60)
    print(classification_report(
        y_test,
        y_pred_test,
        target_names=["Loss", "Win"],
        zero_division=0,
    ))

    # Confusion matrix
    cm = confusion_matrix(y_test, y_pred_test)
    print("Confusion Matrix:")
    print("                 Predicted")
    print("                Loss  Win")
    print(f"Actual   Loss    {cm[0,0]:3d}   {cm[0,1]:3d}")
    print(f"         Win     {cm[1,0]:3d}   {cm[1,1]:3d}")

    # Feature importance
    print("\n" + "-"*60)
    print("Feature Importance (Logistic Regression Coefficients):")
    print("-"*60)

    # Get coefficients
    coefs = model.coef_[0]
    importance = list(zip(feature_names, coefs))
    importance.sort(key=lambda x: abs(x[1]), reverse=True)

    print("\nTop features (by absolute coefficient):")
    for i, (name, coef) in enumerate(importance[:10], 1):
        direction = "↑ WIN" if coef > 0 else "↓ LOSS"
        print(f"  {i:2d}. {name:20s}: {coef:+.3f} {direction}")

    # Compile metrics dictionary
    metrics = {
        "train_accuracy": float(train_acc),
        "test_accuracy": float(test_acc),
        "overfit_gap": float(overfit_gap),
        "test_precision": float(precision_score(y_test, y_pred_test, zero_division=0)),
        "test_recall": float(recall_score(y_test, y_pred_test, zero_division=0)),
        "test_f1": float(f1_score(y_test, y_pred_test, zero_division=0)),
        "confusion_matrix": cm.tolist(),
        "feature_importance": [
            {"feature": name, "coefficient": float(coef)}
            for name, coef in importance
        ],
    }

    # Success criteria check
    print("\n" + "="*60)
    print("SUCCESS CRITERIA CHECK:")
    print("="*60)

    criteria = [
        ("Beat coin flip", test_acc > 0.50, f"Test accuracy: {test_acc:.1%}"),
        ("Good performance", test_acc > 0.55, f"Test accuracy: {test_acc:.1%}"),
        ("Not overfit", abs(overfit_gap) < 0.20, f"Gap: {overfit_gap:+.1%}"),
    ]

    for criterion, passed, detail in criteria:
        status = "✓" if passed else "✗"
        print(f"  {status} {criterion:20s}: {detail}")

    return metrics


def save_model(
    model: LogisticRegression,
    scaler: StandardScaler,
    feature_names: List[str],
    metadata: Dict,
    metrics: Dict,
    version: str = "v1.0",
) -> Tuple[str, str]:
    """
    Save model + metadata for inference.

    Files:
    - backend/models/trained/nfl_logreg_{version}.pkl
    - backend/models/trained/nfl_logreg_{version}_metadata.json

    Args:
        model: Trained model
        scaler: Fitted scaler
        feature_names: Feature names
        metadata: Training data metadata
        metrics: Evaluation metrics
        version: Model version

    Returns:
        (model_path, metadata_path)
    """
    print("\n" + "="*60)
    print("SAVING MODEL")
    print("="*60)

    # Create output directory
    output_dir = os.path.join(PARENT_DIR, "models", "trained")
    os.makedirs(output_dir, exist_ok=True)

    # Model filename
    model_filename = f"nfl_logreg_{version}.pkl"
    metadata_filename = f"nfl_logreg_{version}_metadata.json"

    model_path = os.path.join(output_dir, model_filename)
    metadata_path = os.path.join(output_dir, metadata_filename)

    # Save model + scaler together
    print(f"\nSaving model to: {model_path}")
    with open(model_path, "wb") as f:
        pickle.dump({
            "model": model,
            "scaler": scaler,
            "feature_names": feature_names,
            "version": version,
        }, f)

    # Build comprehensive metadata
    model_metadata = {
        "model_type": "LogisticRegression",
        "version": version,
        "trained_at": datetime.now(tz=timezone.utc).isoformat(),
        "training_data": {
            "symbols": metadata["symbols"],  # List of team symbols
            "team_counts": metadata["team_counts"],  # Games per team
            "total_games": metadata["total_games"],
            "date_range": metadata["date_range"],
            "wins": metadata["wins"],
            "losses": metadata["losses"],
            "win_rate": metadata["win_rate"],
        },
        "features": {
            "names": feature_names,
            "count": len(feature_names),
            "version": "v1.0",
        },
        "hyperparameters": {
            "penalty": "l2",
            "C": 0.1,
            "solver": "lbfgs",
            "random_state": 42,
        },
        "metrics": metrics,
        "usage": {
            "load_example": f"with open('{model_path}', 'rb') as f: model_data = pickle.load(f)",
            "predict_example": "model_data['model'].predict(model_data['scaler'].transform(X))",
        },
    }

    # Save metadata
    print(f"Saving metadata to: {metadata_path}")
    with open(metadata_path, "w") as f:
        json.dump(model_metadata, f, indent=2)

    print("\n✓ Model saved successfully!")
    print(f"\nFiles:")
    print(f"  - {model_path}")
    print(f"  - {metadata_path}")

    return model_path, metadata_path


def main():
    """Main training pipeline"""
    print("="*60)
    print("NFL GAME OUTCOME PREDICTION - ML TRAINING PIPELINE")
    print("="*60)
    print(f"Started at: {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n")

    # Configuration
    SYMBOLS = [
        "NFL:DAL_COWBOYS",
        "NFL:NYG_GIANTS",
        "NFL:PHI_EAGLES",
        "NFL:WSH_COMMANDERS",
    ]
    TEST_SIZE = 0.2
    MODEL_VERSION = "v2.0"  # v2.0: Trained on all NFC East teams

    # Step 1: Load data
    df, metadata = load_training_data(symbols=SYMBOLS)

    # Step 2: Engineer features
    X, feature_names = engineer_features(df)
    y = df["is_win"]

    # Validation: Check for NaN/inf
    if X.isnull().any().any():
        print("\n⚠️  WARNING: NaN values detected in features!")
        print(X.isnull().sum())
        raise ValueError("Feature matrix contains NaN values")

    if np.isinf(X.values).any():
        print("\n⚠️  WARNING: Inf values detected in features!")
        raise ValueError("Feature matrix contains Inf values")

    # Step 3: Split data
    X_train, X_test, y_train, y_test, dates_train, dates_test = split_data(
        X, y, df["game_date"], test_size=TEST_SIZE
    )

    # Step 4: Train model
    model, scaler = train_model(X_train, y_train)

    # Step 5: Evaluate
    metrics = evaluate_model(
        model, scaler, X_train, y_train, X_test, y_test, feature_names
    )

    # Step 6: Save model
    model_path, metadata_path = save_model(
        model, scaler, feature_names, metadata, metrics, version=MODEL_VERSION
    )

    # Final summary
    print("\n" + "="*60)
    print("TRAINING COMPLETE")
    print("="*60)
    print(f"\nModel: {MODEL_VERSION}")
    print(f"Teams: {', '.join(SYMBOLS)}")
    print(f"Training games: {len(X_train)}")
    print(f"Test games: {len(X_test)}")
    print(f"Test accuracy: {metrics['test_accuracy']:.1%}")
    print(f"\nModel ready for inference!")
    print(f"Load with: pickle.load(open('{model_path}', 'rb'))")
    print("\n" + "="*60)


if __name__ == "__main__":
    main()
