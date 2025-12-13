# backend/models/confidence_utils.py
"""
Confidence calculation utilities for multi-horizon forecasts.

Statistical Foundation:
- Returns scale linearly with time: E[R_t] = t × E[R_daily]
- Volatility scales with sqrt(time): σ_t = √t × σ_daily
- Signal-to-noise ratio should be constant across horizons when normalized

This ensures fair comparison between 1-day, 7-day, and 30-day forecasts.
"""

from math import sqrt
from typing import Optional


def calculate_horizon_normalized_confidence(
    expected_return: float,
    volatility: float,
    horizon_minutes: int,
    sample_size: int,
    confidence_scale: float = 2.0,
    min_samples_for_confidence: int = 10,
) -> float:
    """
    Calculate confidence score normalized for forecast horizon.

    The confidence represents how strong the signal is relative to noise,
    measured on a standardized daily time scale. This allows fair comparison
    across different forecast horizons.

    Args:
        expected_return: Expected return over the horizon
        volatility: Standard deviation of returns over the horizon
        horizon_minutes: Forecast horizon in minutes
        sample_size: Number of data points used in forecast
        confidence_scale: Scaling factor (default 2.0 assumes Sharpe ~0-2)
        min_samples_for_confidence: Minimum samples for reasonable confidence

    Returns:
        Confidence score in [0, 1] where:
        - 0.0: No signal or insufficient data
        - 0.5: Moderate signal-to-noise
        - 1.0: Very strong signal (capped)

    Example:
        >>> # 1-day forecast: +0.14% return, 2.53% vol, 60 samples
        >>> conf_1d = calculate_horizon_normalized_confidence(0.0014, 0.0253, 1440, 60)
        >>> # 30-day forecast: +4.24% return, 14.77% vol, 60 samples
        >>> conf_30d = calculate_horizon_normalized_confidence(0.0424, 0.1477, 43200, 60)
        >>> # Both should be similar (~0.03) because signal-to-noise is similar
        >>> assert abs(conf_1d - conf_30d) < 0.01
    """
    # Insufficient data → low confidence
    if sample_size < min_samples_for_confidence:
        penalty = sample_size / min_samples_for_confidence
        return penalty * 0.2  # Max 0.2 confidence with low samples

    # No volatility → can't assess signal quality
    if volatility <= 0:
        return 0.0

    # Convert to daily time scale for normalization
    days = horizon_minutes / 1440.0

    # Normalize to daily equivalents
    # - Returns scale linearly with time
    # - Volatility scales with sqrt(time) (Brownian motion)
    daily_return = expected_return / days
    daily_vol = volatility / sqrt(days)

    # Signal-to-noise ratio (Sharpe-like, but no risk-free rate)
    # This is the key metric: how strong is the signal vs randomness?
    signal_strength = abs(daily_return) / (daily_vol + 1e-8)

    # Scale to [0, 1] range
    # Typical Sharpe ratios: 0 (random) to 2 (very good)
    # We use confidence_scale=2.0 so Sharpe=1.0 → confidence=0.5
    confidence = signal_strength / confidence_scale

    # Clamp to valid range
    return max(0.0, min(1.0, confidence))


def should_add_time_decay(horizon_minutes: int) -> bool:
    """
    Determine if time decay should be applied for very long horizons.

    Currently returns False - we don't apply time decay until backtesting
    proves it's necessary. The sqrt(time) volatility scaling already captures
    most of the uncertainty growth with horizon.

    Future enhancement: If backtesting shows we're overconfident on 30+ day
    forecasts, we can add exponential time decay here.

    Args:
        horizon_minutes: Forecast horizon in minutes

    Returns:
        Whether to apply time decay factor
    """
    # TODO: Enable after backtesting if needed
    # days = horizon_minutes / 1440.0
    # if days > 14:
    #     return True
    return False


def get_confidence_tier(
    confidence: float,
    sample_size: int
) -> str:
    """
    Convert numeric confidence to categorical tier for UI display.

    Follows PLAN_MAESTRO traffic light system:
    - 🟢 GREEN: High confidence (reliable forecast)
    - 🟡 YELLOW: Moderate confidence (use with caution)
    - 🔴 RED: Low confidence (unreliable)

    Args:
        confidence: Confidence score in [0, 1]
        sample_size: Number of data points

    Returns:
        Tier label: "green", "yellow", or "red"
    """
    # Red if insufficient samples, regardless of confidence
    if sample_size < 8:
        return "red"

    # Green requires both high confidence AND sufficient samples
    if confidence > 0.6 and sample_size >= 20:
        return "green"

    # Yellow for moderate confidence
    if confidence >= 0.4 or sample_size >= 8:
        return "yellow"

    # Red for low confidence
    return "red"
