#!/usr/bin/env python3
"""
Forecast performance evaluation and reporting.

This script analyzes backtest results to answer critical questions:
1. Are forecasts better than random? (>50% directional accuracy?)
2. Is confidence calibrated? (high confidence = high accuracy?)
3. Which horizon works best? (1d vs 7d vs 30d)
4. Which regime is hardest? (uptrend vs chop vs high_vol)
5. Are we overconfident anywhere? (claiming high confidence with low accuracy)

Usage:
    # Run full backtest and evaluate
    python -m ml.evaluate_model_performance

    # Custom configuration
    python -m ml.evaluate_model_performance \\
        --symbols BTC-USD,ETH-USD \\
        --horizons 1440,10080 \\
        --days 60 \\
        --output-csv \\
        --insert-db

    # Test on small dataset first
    python -m ml.evaluate_model_performance \\
        --symbols BTC-USD \\
        --horizons 1440 \\
        --days 30 \\
        --sample-freq 7
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import numpy as np

from ml.backtest import build_backtest_dataset, save_backtest_to_db
from config import get_all_symbols

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def calculate_overall_metrics(df: pd.DataFrame) -> Dict:
    """
    Calculate overall performance metrics.

    Returns:
        Dictionary with aggregate statistics
    """
    if df.empty:
        return {
            'total_forecasts': 0,
            'directional_accuracy': 0.0,
            'up_accuracy': 0.0,
            'down_accuracy': 0.0,
            'flat_accuracy': 0.0,
            'avg_confidence': 0.0,
            'forecasts_with_direction': 0,
        }

    # Filter to forecasts with valid predictions
    valid = df[df['direction_correct'].notna()]

    if valid.empty:
        return {
            'total_forecasts': len(df),
            'directional_accuracy': 0.0,
            'up_accuracy': 0.0,
            'down_accuracy': 0.0,
            'flat_accuracy': 0.0,
            'avg_confidence': df['confidence'].mean() if 'confidence' in df else 0.0,
            'forecasts_with_direction': 0,
        }

    # Overall accuracy
    total = len(valid)
    correct = valid['direction_correct'].sum()
    accuracy = (correct / total * 100) if total > 0 else 0.0

    # Accuracy by direction
    up_preds = valid[valid['predicted_direction'] == 'up']
    up_acc = (up_preds['direction_correct'].sum() / len(up_preds) * 100) if len(up_preds) > 0 else 0.0

    down_preds = valid[valid['predicted_direction'] == 'down']
    down_acc = (down_preds['direction_correct'].sum() / len(down_preds) * 100) if len(down_preds) > 0 else 0.0

    flat_preds = valid[valid['predicted_direction'] == 'flat']
    flat_acc = (flat_preds['direction_correct'].sum() / len(flat_preds) * 100) if len(flat_preds) > 0 else 0.0

    return {
        'total_forecasts': total,
        'directional_accuracy': accuracy,
        'up_predictions': len(up_preds),
        'up_accuracy': up_acc,
        'down_predictions': len(down_preds),
        'down_accuracy': down_acc,
        'flat_predictions': len(flat_preds),
        'flat_accuracy': flat_acc,
        'avg_confidence': df['confidence'].mean(),
    }


def analyze_confidence_calibration(df: pd.DataFrame, n_buckets: int = 5) -> pd.DataFrame:
    """
    Analyze confidence calibration by bucketing forecasts.

    A well-calibrated model should have accuracy ≈ confidence.
    For example, forecasts with 70% confidence should be correct ~70% of the time.

    Args:
        df: Backtest DataFrame
        n_buckets: Number of confidence buckets

    Returns:
        DataFrame with calibration analysis
    """
    valid = df[df['direction_correct'].notna() & df['confidence'].notna()].copy()

    if valid.empty:
        return pd.DataFrame()

    # Create confidence buckets
    valid['conf_bucket'] = pd.cut(
        valid['confidence'],
        bins=n_buckets,
        labels=[f'[{i/n_buckets:.1f}-{(i+1)/n_buckets:.1f}]' for i in range(n_buckets)]
    )

    # Calculate accuracy per bucket
    calibration = valid.groupby('conf_bucket', observed=True).agg({
        'direction_correct': ['count', 'sum', 'mean']
    }).round(4)

    calibration.columns = ['forecasts', 'correct', 'accuracy']
    calibration['accuracy_pct'] = calibration['accuracy'] * 100

    # Calculate calibration error (how far from perfect calibration)
    bucket_midpoints = [(i + 0.5) / n_buckets for i in range(n_buckets)]
    calibration['expected_conf'] = bucket_midpoints[:len(calibration)]
    calibration['calibration_error'] = abs(calibration['accuracy'] - calibration['expected_conf'])

    # Mark well-calibrated buckets (within 10% of expected)
    calibration['well_calibrated'] = calibration['calibration_error'] < 0.10

    return calibration


def analyze_by_regime(df: pd.DataFrame) -> pd.DataFrame:
    """
    Analyze forecast performance by market regime.

    Args:
        df: Backtest DataFrame

    Returns:
        DataFrame with regime-specific metrics
    """
    valid = df[df['direction_correct'].notna() & df['regime'].notna()]

    if valid.empty:
        return pd.DataFrame()

    regime_stats = valid.groupby('regime').agg({
        'direction_correct': ['count', 'sum', 'mean'],
        'confidence': 'mean',
        'sample_size': 'mean',
    }).round(4)

    regime_stats.columns = ['forecasts', 'correct', 'accuracy', 'avg_confidence', 'avg_sample_size']
    regime_stats['accuracy_pct'] = regime_stats['accuracy'] * 100

    return regime_stats.sort_values('accuracy', ascending=False)


def analyze_by_horizon(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compare forecast performance across different horizons.

    Args:
        df: Backtest DataFrame with multiple horizons

    Returns:
        DataFrame with horizon-specific metrics
    """
    valid = df[df['direction_correct'].notna()]

    if valid.empty:
        return pd.DataFrame()

    # Map horizon minutes to readable labels
    horizon_labels = {
        1440: '1 day',
        10080: '7 days',
        43200: '30 days',
    }

    horizon_stats = valid.groupby('horizon_minutes').agg({
        'direction_correct': ['count', 'sum', 'mean'],
        'confidence': 'mean',
        'sample_size': 'mean',
    }).round(4)

    horizon_stats.columns = ['forecasts', 'correct', 'accuracy', 'avg_confidence', 'avg_sample_size']
    horizon_stats['accuracy_pct'] = horizon_stats['accuracy'] * 100

    # Add readable labels
    horizon_stats['horizon_label'] = horizon_stats.index.map(lambda x: horizon_labels.get(x, f'{x} min'))

    return horizon_stats.sort_values('horizon_minutes')


def analyze_by_confidence_tier(df: pd.DataFrame) -> pd.DataFrame:
    """
    Analyze performance by confidence tier (high/medium/low).

    Args:
        df: Backtest DataFrame

    Returns:
        DataFrame with tier-specific metrics
    """
    valid = df[df['direction_correct'].notna() & df['confidence'].notna()].copy()

    if valid.empty:
        return pd.DataFrame()

    # Define confidence tiers
    def get_tier(conf):
        if conf >= 0.6:
            return 'High (≥0.6)'
        elif conf >= 0.4:
            return 'Medium (0.4-0.6)'
        else:
            return 'Low (<0.4)'

    valid['tier'] = valid['confidence'].apply(get_tier)

    tier_stats = valid.groupby('tier').agg({
        'direction_correct': ['count', 'sum', 'mean'],
        'confidence': 'mean',
    }).round(4)

    tier_stats.columns = ['forecasts', 'correct', 'accuracy', 'avg_confidence']
    tier_stats['accuracy_pct'] = tier_stats['accuracy'] * 100

    # Order tiers
    tier_order = ['High (≥0.6)', 'Medium (0.4-0.6)', 'Low (<0.4)']
    tier_stats = tier_stats.reindex([t for t in tier_order if t in tier_stats.index])

    return tier_stats


def print_report(df: pd.DataFrame, symbols: List[str], horizons: List[int]):
    """
    Print comprehensive performance report to console.

    Args:
        df: Backtest DataFrame
        symbols: List of symbols analyzed
        horizons: List of horizons analyzed
    """
    print("\n" + "=" * 80)
    print("FORECAST PERFORMANCE REPORT")
    print("=" * 80)
    print(f"Generated: {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Symbols: {', '.join(symbols)}")
    print(f"Horizons: {', '.join(str(h) for h in horizons)} minutes")
    print(f"Date range: {df['as_of'].min()} to {df['as_of'].max()}")
    print("=" * 80)

    # Overall metrics
    print("\nOVERALL PERFORMANCE")
    print("-" * 80)
    overall = calculate_overall_metrics(df)
    print(f"Total forecasts: {overall['total_forecasts']}")
    print(f"Directional accuracy: {overall['directional_accuracy']:.1f}%")
    print(f"  - Up predictions: {overall['up_predictions']} forecasts, {overall['up_accuracy']:.1f}% accurate")
    print(f"  - Down predictions: {overall['down_predictions']} forecasts, {overall['down_accuracy']:.1f}% accurate")
    print(f"  - Flat predictions: {overall['flat_predictions']} forecasts, {overall['flat_accuracy']:.1f}% accurate")
    print(f"Average confidence: {overall['avg_confidence']:.4f}")

    # Key insight: better than random?
    if overall['directional_accuracy'] > 50:
        print(f"\n✓ FINDING: Forecasts are {overall['directional_accuracy'] - 50:.1f}% better than random")
    else:
        print(f"\n✗ WARNING: Forecasts are {50 - overall['directional_accuracy']:.1f}% worse than random")

    # Performance by confidence tier
    print("\n\nPERFORMANCE BY CONFIDENCE TIER")
    print("-" * 80)
    tier_stats = analyze_by_confidence_tier(df)
    if not tier_stats.empty:
        print(tier_stats.to_string())

        # Check for overconfidence
        high_tier = tier_stats.loc[tier_stats.index.str.contains('High')]
        if not high_tier.empty:
            high_acc = high_tier['accuracy_pct'].iloc[0]
            high_conf = high_tier['avg_confidence'].iloc[0] * 100
            if high_acc < high_conf - 10:
                print(f"\n✗ WARNING: Overconfident! High tier shows {high_conf:.1f}% confidence but {high_acc:.1f}% accuracy")
            elif high_acc > high_conf + 10:
                print(f"\n✓ FINDING: Underconfident! High tier shows {high_conf:.1f}% confidence but {high_acc:.1f}% accuracy")
    else:
        print("No data available")

    # Confidence calibration
    print("\n\nCONFIDENCE CALIBRATION")
    print("-" * 80)
    calibration = analyze_confidence_calibration(df)
    if not calibration.empty:
        print(calibration[['forecasts', 'accuracy_pct', 'expected_conf', 'calibration_error', 'well_calibrated']].to_string())
    else:
        print("No data available")

    # Performance by regime
    print("\n\nPERFORMANCE BY MARKET REGIME")
    print("-" * 80)
    regime_stats = analyze_by_regime(df)
    if not regime_stats.empty:
        print(regime_stats.to_string())

        # Identify hardest regime
        worst_regime = regime_stats['accuracy_pct'].idxmin()
        worst_acc = regime_stats.loc[worst_regime, 'accuracy_pct']
        print(f"\nFINDING: Hardest regime is '{worst_regime}' with {worst_acc:.1f}% accuracy")
    else:
        print("No data available")

    # Performance by horizon (if multiple horizons)
    if len(df['horizon_minutes'].unique()) > 1:
        print("\n\nPERFORMANCE BY HORIZON")
        print("-" * 80)
        horizon_stats = analyze_by_horizon(df)
        if not horizon_stats.empty:
            print(horizon_stats[['horizon_label', 'forecasts', 'accuracy_pct', 'avg_confidence']].to_string())

            # Check for horizon degradation
            if len(horizon_stats) >= 2:
                accuracy_trend = horizon_stats['accuracy_pct'].diff().mean()
                if accuracy_trend < -5:
                    print(f"\n✗ FINDING: Accuracy degrades significantly with longer horizons ({accuracy_trend:.1f}% per horizon)")
                elif accuracy_trend > 5:
                    print(f"\n✓ FINDING: Accuracy improves with longer horizons ({accuracy_trend:.1f}% per horizon)")
        else:
            print("No data available")

    # Performance by symbol (if multiple symbols)
    if len(df['symbol'].unique()) > 1:
        print("\n\nPERFORMANCE BY SYMBOL")
        print("-" * 80)
        symbol_stats = df[df['direction_correct'].notna()].groupby('symbol').agg({
            'direction_correct': ['count', 'mean'],
            'confidence': 'mean',
        }).round(4)
        symbol_stats.columns = ['forecasts', 'accuracy', 'avg_confidence']
        symbol_stats['accuracy_pct'] = symbol_stats['accuracy'] * 100
        print(symbol_stats[['forecasts', 'accuracy_pct', 'avg_confidence']].to_string())

    print("\n" + "=" * 80 + "\n")


def save_csv_report(df: pd.DataFrame, output_dir: Path):
    """
    Save comprehensive CSV reports.

    Args:
        df: Backtest DataFrame
        output_dir: Directory to save reports
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=timezone.utc).strftime('%Y%m%d_%H%M%S')

    # Full backtest dataset
    full_path = output_dir / f'backtest_full_{timestamp}.csv'
    df.to_csv(full_path, index=False)
    logger.info(f"Saved full dataset to {full_path}")

    # Summary statistics
    summary_path = output_dir / f'backtest_summary_{timestamp}.csv'
    summary_data = []

    for symbol in df['symbol'].unique():
        for horizon in df['horizon_minutes'].unique():
            subset = df[(df['symbol'] == symbol) & (df['horizon_minutes'] == horizon)]
            metrics = calculate_overall_metrics(subset)

            summary_data.append({
                'symbol': symbol,
                'horizon_minutes': horizon,
                'total_forecasts': metrics['total_forecasts'],
                'directional_accuracy': metrics['directional_accuracy'],
                'up_accuracy': metrics['up_accuracy'],
                'down_accuracy': metrics['down_accuracy'],
                'flat_accuracy': metrics['flat_accuracy'],
                'avg_confidence': metrics['avg_confidence'],
            })

    summary_df = pd.DataFrame(summary_data)
    summary_df.to_csv(summary_path, index=False)
    logger.info(f"Saved summary to {summary_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Evaluate forecast model performance through backtesting',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--symbols',
        type=str,
        default=None,
        help='Comma-separated list of symbols (default: all configured symbols)'
    )

    parser.add_argument(
        '--horizons',
        type=str,
        default='1440,10080,43200',
        help='Comma-separated list of horizons in minutes (default: 1440,10080,43200 for 1d/7d/30d)'
    )

    parser.add_argument(
        '--days',
        type=int,
        default=60,
        help='Number of days to backtest (default: 60)'
    )

    parser.add_argument(
        '--lookback-days',
        type=int,
        default=60,
        help='Lookback window for forecasts (default: 60)'
    )

    parser.add_argument(
        '--sample-freq',
        type=int,
        default=1,
        help='Sample every N days (default: 1 = daily)'
    )

    parser.add_argument(
        '--output-csv',
        action='store_true',
        help='Save CSV reports to backend/notebooks/outputs/'
    )

    parser.add_argument(
        '--insert-db',
        action='store_true',
        help='Insert results into forecast_metrics table'
    )

    parser.add_argument(
        '--model-name',
        type=str,
        default='naive',
        help='Model name for tracking (default: naive)'
    )

    args = parser.parse_args()

    # Parse symbols
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(',')]
    else:
        symbols = get_all_symbols()

    # Parse horizons
    horizons = [int(h.strip()) for h in args.horizons.split(',')]

    # Calculate date range
    end_date = datetime.now(tz=timezone.utc)
    start_date = end_date - timedelta(days=args.days)

    logger.info(f"Starting backtest evaluation")
    logger.info(f"  Symbols: {symbols}")
    logger.info(f"  Horizons: {horizons} minutes")
    logger.info(f"  Period: {start_date.date()} to {end_date.date()}")
    logger.info(f"  Lookback: {args.lookback_days} days")
    logger.info(f"  Sample frequency: every {args.sample_freq} days")

    # Build backtest dataset
    all_results = []

    for horizon in horizons:
        logger.info(f"\nProcessing horizon: {horizon} minutes")

        df = build_backtest_dataset(
            symbols=symbols,
            horizon_minutes=horizon,
            start_date=start_date,
            end_date=end_date,
            lookback_days=args.lookback_days,
            sample_frequency=args.sample_freq,
            model_name=args.model_name,
        )

        if not df.empty:
            all_results.append(df)
        else:
            logger.warning(f"No results generated for horizon {horizon}")

    if not all_results:
        logger.error("No backtest results generated - exiting")
        sys.exit(1)

    # Combine all results
    combined_df = pd.concat(all_results, ignore_index=True)
    logger.info(f"\nGenerated {len(combined_df)} total backtest samples")

    # Print report
    print_report(combined_df, symbols, horizons)

    # Save CSV if requested
    if args.output_csv:
        output_dir = Path(__file__).parent.parent / 'notebooks' / 'outputs'
        save_csv_report(combined_df, output_dir)

    # Insert to database if requested
    if args.insert_db:
        logger.info("\nInserting results to forecast_metrics table...")
        rows_inserted = save_backtest_to_db(combined_df)
        logger.info(f"Successfully inserted {rows_inserted} rows")

    logger.info("\nBacktest evaluation complete!")


if __name__ == '__main__':
    main()
