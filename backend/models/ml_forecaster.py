"""
ML-based Asset Forecaster

This module provides ML-based forecasting that wraps trained classifiers.
It uses the same unified feature extraction as the naive forecaster but
applies trained RandomForest/XGBoost models for predictions.

Key principles:
- Load trained model from disk (lazy loading)
- Use same feature_extractor.build_features() for consistency
- Return ForecastResult with same schema as naive forecaster
- Fallback gracefully to naive on errors
- Only use models that beat naive baseline in validation

Usage:
    from models.ml_forecaster import forecast_asset_ml

    result = forecast_asset_ml(
        symbol="BTC-USD",
        as_of=datetime.now(tz=timezone.utc),
        horizon_minutes=10080,  # 7 days
    )

    if result and result.confidence > 0.5:
        # ML model is confident
        direction = result.direction
    else:
        # Fall back to naive forecaster
        from models.naive_asset_forecaster import forecast_asset
        result = forecast_asset(symbol, as_of, horizon_minutes)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import joblib
import numpy as np

from models.naive_asset_forecaster import ForecastResult
from signals.feature_extractor import build_features

logger = logging.getLogger(__name__)

# Global model cache (lazy loaded)
_ML_MODELS: Dict[int, Dict] = {}


def _get_model_path(horizon_minutes: int) -> Optional[Path]:
    """
    Get path to trained model for given horizon.

    Args:
        horizon_minutes: Forecast horizon (10080 = 7 days)

    Returns:
        Path to model file or None if not available
    """
    models_dir = Path(__file__).resolve().parent / "trained"

    # Map horizons to model files
    horizon_to_model = {
        10080: "ml_forecaster_7d_rf.pkl",  # 7-day RandomForest
        # Add more as we train them:
        # 1440: "ml_forecaster_1d_rf.pkl",  # 1-day
        # 43200: "ml_forecaster_30d_rf.pkl",  # 30-day
    }

    model_file = horizon_to_model.get(horizon_minutes)
    if not model_file:
        return None

    model_path = models_dir / model_file
    if not model_path.exists():
        return None

    return model_path


def _load_model(horizon_minutes: int) -> Optional[Dict]:
    """
    Load trained model from disk (with caching).

    Args:
        horizon_minutes: Forecast horizon

    Returns:
        Dict with 'model', 'feature_names', 'horizon_minutes', 'symbols'
        or None if model not available
    """
    # Check cache
    if horizon_minutes in _ML_MODELS:
        return _ML_MODELS[horizon_minutes]

    # Load from disk
    model_path = _get_model_path(horizon_minutes)
    if not model_path:
        logger.debug(f"No ML model available for horizon {horizon_minutes}min")
        return None

    try:
        model_obj = joblib.load(model_path)

        # Validate structure
        required_keys = {"model", "feature_names", "horizon_minutes", "symbols"}
        if not all(k in model_obj for k in required_keys):
            logger.error(f"Invalid model file structure: {model_path}")
            return None

        # Cache for future use
        _ML_MODELS[horizon_minutes] = model_obj

        logger.info(f"Loaded ML model: {model_path.name}")
        logger.info(f"  Symbols: {model_obj['symbols']}")
        logger.info(f"  Features: {len(model_obj['feature_names'])}")

        return model_obj

    except Exception as e:
        logger.error(f"Failed to load model from {model_path}: {e}")
        return None


def _load_model_metadata(horizon_minutes: int) -> Optional[Dict]:
    """
    Load model metadata JSON.

    Args:
        horizon_minutes: Forecast horizon

    Returns:
        Metadata dict or None
    """
    model_path = _get_model_path(horizon_minutes)
    if not model_path:
        return None

    metadata_path = model_path.with_suffix(".json")
    if not metadata_path.exists():
        return None

    try:
        with open(metadata_path) as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load metadata from {metadata_path}: {e}")
        return None


def forecast_asset_ml(
    symbol: str,
    as_of: Optional[datetime] = None,
    horizon_minutes: int = 10080,  # Default 7-day
    lookback_days: int = 60,
) -> Optional[ForecastResult]:
    """
    ML-based asset forecasting using trained classifier.

    This is a drop-in replacement for naive_asset_forecaster.forecast_asset()
    that uses ML models when available.

    Args:
        symbol: Asset symbol to forecast
        as_of: Reference time (must be timezone-aware UTC)
        horizon_minutes: Forecast horizon
        lookback_days: Historical lookback window

    Returns:
        ForecastResult or None if ML model fails
        (caller should fallback to naive forecaster)
    """
    if as_of is None:
        as_of = datetime.now(tz=timezone.utc)
    elif as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware (use datetime.now(tz=timezone.utc))")

    # Load model
    model_obj = _load_model(horizon_minutes)
    if not model_obj:
        logger.debug(f"No ML model for {symbol} at {horizon_minutes}min - fallback to naive")
        return None

    model = model_obj["model"]
    feature_names = model_obj["feature_names"]
    model_symbols = model_obj["symbols"]

    # Check if symbol is supported
    if symbol not in model_symbols:
        logger.debug(f"Symbol {symbol} not in trained symbols {model_symbols}")
        return None

    try:
        # Build features (same as naive forecaster)
        features = build_features(
            symbol=symbol,
            as_of=as_of,
            horizon_minutes=horizon_minutes,
            lookback_days=lookback_days,
        )

        # Prepare feature vector
        feature_row = {}

        # Extract numeric features
        for k, v in features.items():
            if k not in ("symbol", "as_of", "horizon_minutes"):
                feature_row[k] = v

        # One-hot encode symbol (must match training)
        for sym in model_symbols:
            feature_row[f"symbol_{sym}"] = 1 if symbol == sym else 0

        # Create DataFrame row (model expects this structure)
        import pandas as pd

        X = pd.DataFrame([feature_row])

        # Ensure feature order matches training
        try:
            X = X[feature_names]
        except KeyError as e:
            logger.error(f"Feature mismatch: {e}")
            logger.error(f"  Expected: {feature_names}")
            logger.error(f"  Got: {list(X.columns)}")
            return None

        # Fill missing features with 0 (shouldn't happen but be defensive)
        X = X.fillna(0)

        # Predict direction (binary classification)
        direction_binary = model.predict(X)[0]  # 0=down, 1=up
        direction = "up" if direction_binary == 1 else "down"

        # Get prediction probability for confidence
        try:
            proba = model.predict_proba(X)[0]  # [prob_down, prob_up]
            max_proba = float(np.max(proba))
            confidence = max_proba  # Confidence = probability of predicted class
        except Exception:
            # Some models don't support predict_proba
            confidence = 0.5  # Default to medium confidence

        # Expected return: We don't have this from binary classifier
        # Use naive approach as fallback
        from models.naive_asset_forecaster import _fetch_recent_returns
        from statistics import mean

        rets = _fetch_recent_returns(symbol, as_of, horizon_minutes, lookback_days)
        n = len(rets)
        mu = mean(rets) if rets else 0.0

        # Adjust sign based on ML prediction
        if direction == "down" and mu > 0:
            expected_return = -abs(mu)  # Flip to negative
        elif direction == "up" and mu < 0:
            expected_return = abs(mu)  # Flip to positive
        else:
            expected_return = mu  # Keep as-is

        return ForecastResult(
            symbol=symbol,
            as_of=as_of,
            horizon_minutes=horizon_minutes,
            expected_return=expected_return,
            direction=direction,
            confidence=confidence,
            lookback_days=lookback_days,
            n_points=n,
            mean_return=mu,
            vol_return=None,  # Not used by ML model
            features=features,
        )

    except Exception as e:
        logger.error(f"ML forecast failed for {symbol}: {e}")
        return None


def get_available_ml_models() -> Dict[int, Dict]:
    """
    Get information about available ML models.

    Returns:
        Dict mapping horizon_minutes to model metadata
    """
    available = {}

    for horizon in [1440, 10080, 43200]:  # 1d, 7d, 30d
        metadata = _load_model_metadata(horizon)
        if metadata:
            available[horizon] = {
                "model_name": metadata.get("model_name"),
                "model_type": metadata.get("model_type"),
                "trained_at": metadata.get("trained_at"),
                "symbols": metadata.get("symbols"),
                "test_accuracy": metadata.get("metrics", {}).get("overall", {}).get("test_accuracy"),
                "baseline_comparison": metadata.get("baseline_comparison"),
            }

    return available


def is_ml_model_available(symbol: str, horizon_minutes: int) -> bool:
    """
    Check if ML model is available for given symbol and horizon.

    Args:
        symbol: Asset symbol
        horizon_minutes: Forecast horizon

    Returns:
        True if ML model is available and symbol is supported
    """
    model_obj = _load_model(horizon_minutes)
    if not model_obj:
        return False

    return symbol in model_obj["symbols"]
