# backend/models/naive_asset_forecaster.py
from dataclasses import dataclass
from typing import List
from statistics import mean, pstdev
from numeric.asset_returns import get_past_returns

@dataclass
class ForecastResult:
    symbol: str
    horizon_minutes: int
    mean_return: float
    std_return: float
    p_up: float
    p_down: float
    sample_size: int

def naive_return_forecast(symbol: str, horizon_minutes: int) -> ForecastResult:
    """
    Super naive baseline:
    - Look at historic realized returns
    - Estimate mean, std, and p(return > 0)
    """
    hist = get_past_returns(symbol, horizon_minutes)
    if not hist:
        # No data → no signal
        return ForecastResult(
            symbol=symbol,
            horizon_minutes=horizon_minutes,
            mean_return=0.0,
            std_return=0.0,
            p_up=0.5,
            p_down=0.5,
            sample_size=0,
        )

    rets = [r for (_t, r) in hist]
    m = mean(rets)
    s = pstdev(rets) if len(rets) > 1 else 0.0
    p_up = sum(1 for r in rets if r > 0) / len(rets)
    p_down = 1 - p_up

    return ForecastResult(
        symbol=symbol,
        horizon_minutes=horizon_minutes,
        mean_return=m,
        std_return=s,
        p_up=p_up,
        p_down=p_down,
        sample_size=len(rets),
    )

