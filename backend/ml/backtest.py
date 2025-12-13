"""
Backtesting framework for forecast validation.

This module generates historical forecasts and compares them against realized returns
to evaluate model performance, confidence calibration, and directional accuracy.

Key principles:
1. No lookahead bias: Only uses data available at as_of timestamp
2. Temporal integrity: Maintains strict < as_of filtering
3. Regime awareness: Tracks market conditions for each forecast
4. Comprehensive metrics: Captures expected vs realized, direction, confidence

Usage:
    from ml.backtest import build_backtest_dataset

    df = build_backtest_dataset(
        symbols=['BTC-USD', 'ETH-USD'],
        horizon_minutes=1440,
        start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2024, 3, 1, tzinfo=timezone.utc),
        lookback_days=60
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import uuid4

import pandas as pd

from db import get_conn
from models.naive_asset_forecaster import forecast_asset
from models.regime_classifier import classify_regime
from config import FORECAST_DIRECTION_THRESHOLD

logger = logging.getLogger(__name__)


@dataclass
class BacktestRow:
    """Single row in the backtest dataset."""

    id: str
    symbol: str
    as_of: datetime
    horizon_minutes: int
    model_name: str
    schema_version: str

    # Forecast outputs
    expected_return: Optional[float]
    predicted_direction: Optional[str]
    confidence: float
    sample_size: int

    # Realized outcomes
    realized_return: Optional[float]
    actual_direction: Optional[str]
    direction_correct: Optional[bool]

    # Market context
    regime: str


def _get_direction(return_value: Optional[float], threshold: float = FORECAST_DIRECTION_THRESHOLD) -> Optional[str]:
    """
    Classify return as 'up', 'down', or 'flat' based on threshold.

    Args:
        return_value: The return value (can be None)
        threshold: Minimum absolute return to classify as up/down

    Returns:
        Direction label or None if return_value is None
    """
    if return_value is None:
        return None

    if return_value > threshold:
        return "up"
    elif return_value < -threshold:
        return "down"
    else:
        return "flat"


def _fetch_realized_return(
    symbol: str,
    as_of: datetime,
    horizon_minutes: int,
) -> Optional[float]:
    """
    Fetch the realized return for a specific forecast.

    This is the ground truth we're comparing our forecast against.

    Args:
        symbol: Asset symbol
        as_of: Forecast timestamp (timezone-aware UTC)
        horizon_minutes: Forecast horizon

    Returns:
        Realized return or None if not available
    """
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware (use datetime.now(tz=timezone.utc))")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT realized_return
                FROM asset_returns
                WHERE symbol = %s
                  AND as_of = %s
                  AND horizon_minutes = %s
                LIMIT 1
                """,
                (symbol, as_of, horizon_minutes)
            )
            row = cur.fetchone()

    if row:
        return float(row["realized_return"])
    return None


def _get_available_dates(
    symbol: str,
    horizon_minutes: int,
    start_date: datetime,
    end_date: datetime,
) -> List[datetime]:
    """
    Get all dates with available return data for backtesting.

    This queries the asset_returns table to find which dates we can
    actually backtest (need both historical data for forecast AND
    realized return for validation).

    Args:
        symbol: Asset symbol
        horizon_minutes: Forecast horizon
        start_date: Start of backtest period (timezone-aware UTC)
        end_date: End of backtest period (timezone-aware UTC)

    Returns:
        List of datetime objects with available data
    """
    if start_date.tzinfo is None or end_date.tzinfo is None:
        raise ValueError("start_date and end_date must be timezone-aware")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT as_of
                FROM asset_returns
                WHERE symbol = %s
                  AND horizon_minutes = %s
                  AND as_of BETWEEN %s AND %s
                ORDER BY as_of ASC
                """,
                (symbol, horizon_minutes, start_date, end_date)
            )
            rows = cur.fetchall()

    return [row["as_of"] for row in rows]


def build_backtest_dataset(
    symbols: List[str],
    horizon_minutes: int,
    start_date: datetime,
    end_date: datetime,
    lookback_days: int = 60,
    sample_frequency: int = 1,  # Sample every N days (1 = daily)
    model_name: str = "naive",
    schema_version: str = "v1",
) -> pd.DataFrame:
    """
    Build backtest dataset by generating historical forecasts and comparing to realized returns.

    This is the core backtesting engine. For each (symbol, as_of, horizon) combination:
    1. Generate forecast using naive_asset_forecaster with historical as_of date
    2. Fetch realized return from asset_returns table
    3. Calculate directional accuracy
    4. Classify market regime at as_of time

    CRITICAL: No lookahead bias - only uses data available at as_of timestamp.

    Args:
        symbols: List of asset symbols to backtest
        horizon_minutes: Forecast horizon (1440, 10080, 43200 for 1d/7d/30d)
        start_date: Start of backtest period (timezone-aware UTC)
        end_date: End of backtest period (timezone-aware UTC)
        lookback_days: Historical lookback window for forecasts
        sample_frequency: Sample every N days (default 1 = daily)
        model_name: Model identifier for tracking
        schema_version: Feature schema version

    Returns:
        DataFrame with columns matching BacktestRow dataclass

    Example:
        >>> from datetime import datetime, timezone
        >>> df = build_backtest_dataset(
        ...     symbols=['BTC-USD'],
        ...     horizon_minutes=1440,
        ...     start_date=datetime(2024, 11, 1, tzinfo=timezone.utc),
        ...     end_date=datetime(2024, 12, 1, tzinfo=timezone.utc),
        ...     lookback_days=60
        ... )
        >>> print(f"Generated {len(df)} backtest samples")
    """
    if start_date.tzinfo is None or end_date.tzinfo is None:
        raise ValueError("start_date and end_date must be timezone-aware")

    rows = []
    total_forecasts = 0
    successful_forecasts = 0

    logger.info(f"Starting backtest: symbols={symbols}, horizon={horizon_minutes}min, "
                f"period={start_date.date()} to {end_date.date()}")

    for symbol in symbols:
        logger.info(f"Processing {symbol}...")

        # Get all available dates with return data
        available_dates = _get_available_dates(symbol, horizon_minutes, start_date, end_date)

        if not available_dates:
            logger.warning(f"No data available for {symbol} in backtest period")
            continue

        # Sample dates according to frequency
        sampled_dates = available_dates[::sample_frequency]
        logger.info(f"  Found {len(available_dates)} dates, sampling {len(sampled_dates)} "
                   f"(every {sample_frequency} days)")

        for i, as_of in enumerate(sampled_dates):
            total_forecasts += 1

            try:
                # Generate forecast using historical as_of date
                # CRITICAL: This only uses data from BEFORE as_of (no lookahead)
                forecast = forecast_asset(
                    symbol=symbol,
                    as_of=as_of,
                    horizon_minutes=horizon_minutes,
                    lookback_days=lookback_days
                )

                # Fetch realized return (ground truth)
                realized = _fetch_realized_return(symbol, as_of, horizon_minutes)

                # Calculate actual direction
                actual_dir = _get_direction(realized)

                # Check if direction prediction was correct
                direction_correct = None
                if forecast.direction and actual_dir:
                    direction_correct = (forecast.direction == actual_dir)

                # Classify market regime at forecast time
                regime_result = classify_regime(symbol, as_of)

                # Create backtest row
                row = BacktestRow(
                    id=str(uuid4()),
                    symbol=symbol,
                    as_of=as_of,
                    horizon_minutes=horizon_minutes,
                    model_name=model_name,
                    schema_version=schema_version,
                    expected_return=forecast.expected_return,
                    predicted_direction=forecast.direction,
                    confidence=forecast.confidence,
                    sample_size=forecast.n_points,
                    realized_return=realized,
                    actual_direction=actual_dir,
                    direction_correct=direction_correct,
                    regime=regime_result.regime,
                )

                rows.append(row)
                successful_forecasts += 1

                # Progress logging
                if (i + 1) % 10 == 0:
                    logger.info(f"  Progress: {i + 1}/{len(sampled_dates)} forecasts")

            except Exception as e:
                logger.error(f"Error generating forecast for {symbol} at {as_of}: {e}")
                continue

    logger.info(f"Backtest complete: {successful_forecasts}/{total_forecasts} successful forecasts")

    # Convert to DataFrame
    df = pd.DataFrame([vars(row) for row in rows])

    if df.empty:
        logger.warning("No backtest data generated - DataFrame is empty")
        return df

    # Ensure as_of is datetime64[ns, UTC] for pandas
    df['as_of'] = pd.to_datetime(df['as_of'], utc=True)

    return df


def save_backtest_to_db(df: pd.DataFrame) -> int:
    """
    Save backtest results to forecast_metrics table.

    Args:
        df: Backtest DataFrame from build_backtest_dataset()

    Returns:
        Number of rows inserted
    """
    if df.empty:
        logger.warning("Cannot save empty DataFrame to database")
        return 0

    # Prepare data for insertion
    records = df.to_dict('records')

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Bulk insert using executemany for performance
            cur.executemany(
                """
                INSERT INTO forecast_metrics (
                    id, symbol, as_of, horizon_minutes, model_name, schema_version,
                    expected_return, predicted_direction, confidence, sample_size,
                    realized_return, actual_direction, direction_correct, regime
                ) VALUES (
                    %(id)s, %(symbol)s, %(as_of)s, %(horizon_minutes)s,
                    %(model_name)s, %(schema_version)s,
                    %(expected_return)s, %(predicted_direction)s,
                    %(confidence)s, %(sample_size)s,
                    %(realized_return)s, %(actual_direction)s,
                    %(direction_correct)s, %(regime)s
                )
                ON CONFLICT (id) DO NOTHING
                """,
                records
            )
            conn.commit()
            rows_inserted = cur.rowcount

    logger.info(f"Saved {rows_inserted} backtest results to database")
    return rows_inserted
