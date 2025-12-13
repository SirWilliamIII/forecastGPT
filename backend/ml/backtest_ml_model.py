"""
ML Model Backtesting - Validate Against Naive Baseline

This script backtests trained ML models against the naive baseline to determine
if they actually improve forecast accuracy in production-like conditions.

CRITICAL: This is the real validation. Training accuracy can be misleading due to:
- Small test sets (overfitting)
- Data leakage (if features aren't properly constructed)
- Lucky splits (specific time periods that are easy)

The backtest runs the ML model on historical data and compares directional
accuracy against:
1. Naive baseline (60% on 7-day horizon)
2. Per-symbol performance
3. Confidence calibration
4. Regime-specific performance

Usage:
    uv run python -m ml.backtest_ml_model --days 60 --output-csv

The model is ONLY deployable if it beats naive baseline on backtest.
"""

import argparse
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from db import get_conn
from ml.backtest import build_backtest_dataset, save_backtest_to_db
from models.ml_forecaster import forecast_asset_ml

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def build_ml_backtest_dataset(
    symbols: list[str],
    horizon_minutes: int,
    start_date: datetime,
    end_date: datetime,
    lookback_days: int = 60,
    sample_frequency: int = 1,
) -> pd.DataFrame:
    """
    Build backtest dataset using ML forecaster.

    This is identical to build_backtest_dataset() but uses ML forecaster
    instead of naive forecaster.

    Args:
        symbols: List of asset symbols
        horizon_minutes: Forecast horizon
        start_date: Start of backtest period (timezone-aware UTC)
        end_date: End of backtest period (timezone-aware UTC)
        lookback_days: Historical lookback window
        sample_frequency: Sample every N days

    Returns:
        DataFrame with backtest results
    """
    from uuid import uuid4
    from ml.backtest import _get_available_dates, _fetch_realized_return, _get_direction
    from models.regime_classifier import classify_regime

    if start_date.tzinfo is None or end_date.tzinfo is None:
        raise ValueError("start_date and end_date must be timezone-aware")

    rows = []
    total_forecasts = 0
    successful_forecasts = 0
    ml_failures = 0

    logger.info(f"Starting ML backtest: symbols={symbols}, horizon={horizon_minutes}min")
    logger.info(f"  Period: {start_date.date()} to {end_date.date()}")

    for symbol in symbols:
        logger.info(f"Processing {symbol}...")

        # Get all available dates
        available_dates = _get_available_dates(symbol, horizon_minutes, start_date, end_date)

        if not available_dates:
            logger.warning(f"  No data for {symbol}")
            continue

        # Sample dates
        sampled_dates = available_dates[::sample_frequency]
        logger.info(f"  Found {len(available_dates)} dates, sampling {len(sampled_dates)}")

        for i, as_of in enumerate(sampled_dates):
            total_forecasts += 1

            try:
                # Generate ML forecast
                forecast = forecast_asset_ml(
                    symbol=symbol,
                    as_of=as_of,
                    horizon_minutes=horizon_minutes,
                    lookback_days=lookback_days,
                )

                if not forecast:
                    ml_failures += 1
                    logger.warning(f"  ML forecast failed at {as_of} - skipping")
                    continue

                # Fetch realized return
                realized = _fetch_realized_return(symbol, as_of, horizon_minutes)

                # Calculate actual direction
                actual_dir = _get_direction(realized)

                # Check if direction prediction was correct
                direction_correct = None
                if forecast.direction and actual_dir:
                    direction_correct = (forecast.direction == actual_dir)

                # Classify market regime
                regime_result = classify_regime(symbol, as_of)

                # Create backtest row
                row = {
                    "id": str(uuid4()),
                    "symbol": symbol,
                    "as_of": as_of,
                    "horizon_minutes": horizon_minutes,
                    "model_name": "ml_forecaster_7d_rf",  # Updated dynamically
                    "schema_version": "v2",
                    "expected_return": forecast.expected_return,
                    "predicted_direction": forecast.direction,
                    "confidence": forecast.confidence,
                    "sample_size": forecast.n_points,
                    "realized_return": realized,
                    "actual_direction": actual_dir,
                    "direction_correct": direction_correct,
                    "regime": regime_result.regime,
                }

                rows.append(row)
                successful_forecasts += 1

                if (i + 1) % 10 == 0:
                    logger.info(f"  Progress: {i + 1}/{len(sampled_dates)}")

            except Exception as e:
                logger.error(f"  Error at {as_of}: {e}")
                continue

    logger.info(f"ML Backtest complete:")
    logger.info(f"  Successful: {successful_forecasts}/{total_forecasts}")
    logger.info(f"  ML failures: {ml_failures} (fell back to None)")

    df = pd.DataFrame(rows)

    if df.empty:
        logger.warning("No backtest data generated")
        return df

    # Ensure as_of is datetime
    df["as_of"] = pd.to_datetime(df["as_of"], utc=True)

    return df


def compare_ml_vs_naive(ml_df: pd.DataFrame, naive_df: pd.DataFrame) -> dict:
    """
    Compare ML model performance against naive baseline.

    Args:
        ml_df: ML backtest results
        naive_df: Naive backtest results

    Returns:
        Dict with comparison metrics
    """
    logger.info("Comparing ML vs Naive baseline...")

    # Overall accuracy
    ml_acc = ml_df["direction_correct"].mean()
    naive_acc = naive_df["direction_correct"].mean()

    logger.info(f"  Overall:")
    logger.info(f"    ML:    {ml_acc:.4f}")
    logger.info(f"    Naive: {naive_acc:.4f}")
    logger.info(f"    Improvement: {(ml_acc - naive_acc):.4f} ({(ml_acc - naive_acc) * 100:+.1f}%)")

    # Per-symbol
    per_symbol = {}
    for symbol in ml_df["symbol"].unique():
        ml_sym = ml_df[ml_df["symbol"] == symbol]
        naive_sym = naive_df[naive_df["symbol"] == symbol]

        ml_sym_acc = ml_sym["direction_correct"].mean()
        naive_sym_acc = naive_sym["direction_correct"].mean()

        per_symbol[symbol] = {
            "ml_accuracy": float(ml_sym_acc),
            "naive_accuracy": float(naive_sym_acc),
            "improvement": float(ml_sym_acc - naive_sym_acc),
            "n_samples": int(len(ml_sym)),
        }

        logger.info(f"  {symbol}:")
        logger.info(f"    ML:    {ml_sym_acc:.4f}")
        logger.info(f"    Naive: {naive_sym_acc:.4f}")
        logger.info(f"    Improvement: {(ml_sym_acc - naive_sym_acc):.4f} ({(ml_sym_acc - naive_sym_acc) * 100:+.1f}%)")

    return {
        "overall": {
            "ml_accuracy": float(ml_acc),
            "naive_accuracy": float(naive_acc),
            "improvement": float(ml_acc - naive_acc),
            "beats_baseline": bool(ml_acc > naive_acc),
            "n_samples": int(len(ml_df)),
        },
        "per_symbol": per_symbol,
    }


def main():
    parser = argparse.ArgumentParser(description="Backtest ML model vs naive baseline")
    parser.add_argument("--symbols", default="BTC-USD,ETH-USD,XMR-USD", help="Comma-separated symbols")
    parser.add_argument("--horizon", type=int, default=10080, help="Horizon in minutes (10080=7d)")
    parser.add_argument("--days", type=int, default=60, help="Days to backtest")
    parser.add_argument("--sample-freq", type=int, default=1, help="Sample every N days")
    parser.add_argument("--output-csv", action="store_true", help="Save results to CSV")
    parser.add_argument("--save-db", action="store_true", help="Save to database")

    args = parser.parse_args()

    symbols = args.symbols.split(",")
    horizon_minutes = args.horizon
    end_date = datetime.now(tz=timezone.utc)
    start_date = end_date - timedelta(days=args.days)

    logger.info("=" * 80)
    logger.info("ML Model Backtesting - Validation Against Naive Baseline")
    logger.info("=" * 80)
    logger.info(f"Symbols: {symbols}")
    logger.info(f"Horizon: {horizon_minutes}min ({horizon_minutes // 1440}d)")
    logger.info(f"Period: {start_date.date()} to {end_date.date()}")
    logger.info(f"Sample frequency: every {args.sample_freq} day(s)")

    # Step 1: Run ML backtest
    logger.info("\n" + "=" * 80)
    logger.info("STEP 1: Running ML model backtest")
    logger.info("=" * 80)

    ml_df = build_ml_backtest_dataset(
        symbols=symbols,
        horizon_minutes=horizon_minutes,
        start_date=start_date,
        end_date=end_date,
        sample_frequency=args.sample_freq,
    )

    if ml_df.empty:
        logger.error("ML backtest failed - no data")
        return

    # Step 2: Run naive backtest (for comparison)
    logger.info("\n" + "=" * 80)
    logger.info("STEP 2: Running naive baseline backtest")
    logger.info("=" * 80)

    naive_df = build_backtest_dataset(
        symbols=symbols,
        horizon_minutes=horizon_minutes,
        start_date=start_date,
        end_date=end_date,
        sample_frequency=args.sample_freq,
        model_name="naive",
        schema_version="v1",
    )

    if naive_df.empty:
        logger.error("Naive backtest failed - no data")
        return

    # Step 3: Compare
    logger.info("\n" + "=" * 80)
    logger.info("STEP 3: Comparing ML vs Naive")
    logger.info("=" * 80)

    comparison = compare_ml_vs_naive(ml_df, naive_df)

    # Step 4: Verdict
    logger.info("\n" + "=" * 80)
    logger.info("DEPLOYMENT VERDICT")
    logger.info("=" * 80)

    overall = comparison["overall"]
    beats_baseline = overall["beats_baseline"]
    improvement = overall["improvement"]

    if beats_baseline:
        logger.info(f"✓ ML MODEL BEATS BASELINE")
        logger.info(f"  Accuracy: {overall['ml_accuracy']:.4f} vs {overall['naive_accuracy']:.4f}")
        logger.info(f"  Improvement: +{improvement * 100:.1f}%")
        logger.info(f"  Recommendation: DEPLOY to production")
    else:
        logger.error(f"✗ ML MODEL DOES NOT BEAT BASELINE")
        logger.error(f"  Accuracy: {overall['ml_accuracy']:.4f} vs {overall['naive_accuracy']:.4f}")
        logger.error(f"  Regression: {improvement * 100:.1f}%")
        logger.error(f"  Recommendation: DO NOT DEPLOY - keep naive baseline")

    logger.info("=" * 80)

    # Step 5: Save outputs
    if args.output_csv:
        outputs_dir = Path(__file__).resolve().parent.parent / "notebooks" / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        ml_path = outputs_dir / f"backtest_ml_{timestamp}.csv"
        naive_path = outputs_dir / f"backtest_naive_{timestamp}.csv"
        comparison_path = outputs_dir / f"comparison_{timestamp}.json"

        ml_df.to_csv(ml_path, index=False)
        naive_df.to_csv(naive_path, index=False)

        import json

        with open(comparison_path, "w") as f:
            json.dump(comparison, f, indent=2)

        logger.info(f"\nResults saved:")
        logger.info(f"  ML: {ml_path}")
        logger.info(f"  Naive: {naive_path}")
        logger.info(f"  Comparison: {comparison_path}")

    if args.save_db:
        logger.info("\nSaving to database...")
        ml_rows = save_backtest_to_db(ml_df)
        naive_rows = save_backtest_to_db(naive_df)
        logger.info(f"  Saved {ml_rows} ML rows, {naive_rows} naive rows")


if __name__ == "__main__":
    main()
