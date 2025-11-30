# backend/models/event_return_forecaster.py
from dataclasses import dataclass
from math import exp, sqrt
from typing import List, Tuple
from uuid import UUID

from signals.feature_extractor import build_return_samples_for_event


@dataclass
class EventReturnForecastResult:
    event_id: UUID
    symbol: str
    horizon_minutes: int
    expected_return: float
    std_return: float
    p_up: float
    p_down: float
    sample_size: int
    neighbors_used: int


def _compute_weighted_moments(samples: List[Tuple[float, float]], alpha: float = 0.5):
    """
    samples: list of (distance, return)
    alpha: controls how fast weight decays with distance (higher = more local)
    """
    if not samples:
        return 0.0, 0.0, 0.5, 0.5, 0

    weights: List[float] = []
    rets: List[float] = []

    for dist, r in samples:
        # distance >= 0, so exp(-alpha * dist) decays with distance
        w = exp(-alpha * float(dist))
        weights.append(w)
        rets.append(float(r))

    w_sum = sum(weights)
    if w_sum == 0:
        # degenerate, fallback to unweighted
        mean = sum(rets) / len(rets)
        std = 0.0
        p_up = sum(1 for r in rets if r > 0) / len(rets)
        return mean, std, p_up, 1 - p_up, len(rets)

    # weighted mean
    mean = sum(w * r for w, r in zip(weights, rets)) / w_sum

    # weighted variance
    var = sum(w * (r - mean) ** 2 for w, r in zip(weights, rets)) / w_sum
    std = sqrt(var)

    # weighted p_up
    w_up = sum(w for w, r in zip(weights, rets) if r > 0)
    p_up = w_up / w_sum
    p_down = 1.0 - p_up

    return mean, std, p_up, p_down, len(rets)


def forecast_event_return(
    event_id: UUID,
    symbol: str,
    horizon_minutes: int,
    k_neighbors: int = 25,
    lookback_days: int = 365,
    price_window_minutes: int = 60,
    alpha: float = 0.5,
) -> EventReturnForecastResult:
    """
    Core Phase 1 forecaster:

    1. For the given event_id, find semantically nearest neighbor events.
    2. For each neighbor, fetch realized returns around its timestamp.
    3. Use distance-weighted statistics over those returns to produce a forecast.
    """
    samples = build_return_samples_for_event(
        event_id=event_id,
        symbol=symbol,
        horizon_minutes=horizon_minutes,
        k_neighbors=k_neighbors,
        lookback_days=lookback_days,
        price_window_minutes=price_window_minutes,
    )

    expected, std, p_up, p_down, sample_size = _compute_weighted_moments(
        samples,
        alpha=alpha,
    )

    neighbors_used = min(k_neighbors, sample_size)  # rough diagnostic

    return EventReturnForecastResult(
        event_id=event_id,
        symbol=symbol,
        horizon_minutes=horizon_minutes,
        expected_return=expected,
        std_return=std,
        p_up=p_up,
        p_down=p_down,
        sample_size=sample_size,
        neighbors_used=neighbors_used,
    )
