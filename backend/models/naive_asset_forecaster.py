# backend/models/naive_asset_forecaster.py

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from statistics import mean, pstdev
from typing import Any, Dict, Optional, List

from db import get_conn
from signals.feature_extractor import build_features
from config import FORECAST_DIRECTION_THRESHOLD, FORECAST_CONFIDENCE_SCALE
from models.confidence_utils import calculate_horizon_normalized_confidence


@dataclass
class ForecastResult:
    symbol: str
    as_of: datetime
    horizon_minutes: int

    expected_return: Optional[float]
    direction: Optional[str]
    confidence: float

    lookback_days: int
    n_points: int
    mean_return: Optional[float]
    vol_return: Optional[float]

    features: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["as_of"] = self.as_of.isoformat()
        return d


def _fetch_recent_returns(
    symbol: str,
    as_of: datetime,
    horizon_minutes: int,
    lookback_days: int,
) -> List[float]:
    """
    Pull recent realized_return rows for (symbol, horizon_minutes)
    from asset_returns over a lookback window.
    """
    start = as_of - timedelta(days=lookback_days)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT realized_return
                FROM asset_returns
                WHERE symbol = %s
                  AND horizon_minutes = %s
                  AND as_of BETWEEN %s AND %s
                ORDER BY as_of ASC
                """,
                (symbol, horizon_minutes, start, as_of),
            )
            rows = cur.fetchall()

    return [float(r["realized_return"]) for r in rows]


def forecast_asset(
    symbol: str,
    as_of: Optional[datetime] = None,
    horizon_minutes: int = 1440,
    lookback_days: int = 60,
) -> ForecastResult:
    """
    Naive numeric forecaster:

    - expected_return = mean(last N daily returns)
    - vol = std(last N daily returns)
    - direction = sign(expected_return) with small deadzone
    - confidence = squashed signal-to-noise ratio

    Uses the unified feature extractor so we can later swap in ML.

    Args:
        symbol: Asset symbol to forecast
        as_of: Reference time (must be timezone-aware UTC)
        horizon_minutes: Forecast horizon
        lookback_days: Historical lookback window
    """
    if as_of is None:
        as_of = datetime.now(tz=timezone.utc)
    elif as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware (use datetime.now(tz=timezone.utc))")

    rets = _fetch_recent_returns(symbol, as_of, horizon_minutes, lookback_days)
    n = len(rets)

    if n == 0:
        # No data: we return "I don't know" with low confidence
        feats = build_features(symbol, as_of, horizon_minutes, lookback_days)
        return ForecastResult(
            symbol=symbol,
            as_of=as_of,
            horizon_minutes=horizon_minutes,
            expected_return=None,
            direction=None,
            confidence=0.0,
            lookback_days=lookback_days,
            n_points=0,
            mean_return=None,
            vol_return=None,
            features=feats,
        )

    mu = mean(rets)
    sigma = pstdev(rets) if n > 1 else 0.0

    # naive expected return = mean of recent returns
    expected = mu

    # direction with a small deadzone to avoid flip-flopping on noise
    threshold = FORECAST_DIRECTION_THRESHOLD
    if expected > threshold:
        direction = "up"
    elif expected < -threshold:
        direction = "down"
    else:
        direction = "flat"

    # Horizon-normalized confidence using proper statistical scaling
    # This ensures 1-day and 30-day forecasts are comparable
    # See models/confidence_utils.py for mathematical foundation
    confidence = calculate_horizon_normalized_confidence(
        expected_return=expected,
        volatility=sigma,
        horizon_minutes=horizon_minutes,
        sample_size=n,
        confidence_scale=FORECAST_CONFIDENCE_SCALE,
    )

    feats = build_features(symbol, as_of, horizon_minutes, lookback_days)

    return ForecastResult(
        symbol=symbol,
        as_of=as_of,
        horizon_minutes=horizon_minutes,
        expected_return=expected,
        direction=direction,
        confidence=confidence,
        lookback_days=lookback_days,
        n_points=n,
        mean_return=mu,
        vol_return=sigma,
        features=feats,
    )

