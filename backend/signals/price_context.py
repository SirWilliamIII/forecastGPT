from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from math import sqrt
from statistics import mean, pstdev
from typing import Dict, List, Tuple
from db import get_conn


@dataclass
class PriceFeatures:
    symbol: str
    as_of: datetime
    horizon_minutes: int
    lookback_days: int
    n_points: int

    # cumulative returns (approx “performance over window”)
    r_1d: float | None
    r_3d: float | None
    r_7d: float | None
    r_14d: float | None
    r_30d: float | None

    # realized volatility (std of simple returns)
    vol_3d: float | None
    vol_7d: float | None
    vol_30d: float | None

    # simple “is it stretched?” signal
    zscore_1d: float | None  # last 1d return vs last 20d distribution

    # rough drawdown over last month
    max_drawdown_30d: float | None  # in return space, e.g. -0.25 = -25%

    def to_dict(self) -> Dict:
        d = asdict(self)
        # ensure datetimes are ISO strings if you want JSON-friendly
        d["as_of"] = self.as_of.isoformat()
        return d


def _fetch_returns(
    symbol: str,
    as_of: datetime,
    horizon_minutes: int,
    lookback_days: int,
) -> List[Tuple[datetime, float]]:
    """
    Fetch simple returns for (symbol, horizon_minutes) going back lookback_days
    from as_of (inclusive).
    """
    start = as_of - timedelta(days=lookback_days)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT as_of, realized_return
                FROM asset_returns
                WHERE symbol = %s
                  AND horizon_minutes = %s
                  AND as_of BETWEEN %s AND %s
                ORDER BY as_of ASC
                """,
                (symbol, horizon_minutes, start, as_of),
            )
            rows = cur.fetchall()

    return [(row["as_of"], float(row["realized_return"])) for row in rows]


def _cum_return(returns: List[float]) -> float:
    """
    Convert a list of simple returns r_i into a single cumulative
    return: prod(1 + r_i) - 1
    """
    acc = 1.0
    for r in returns:
        acc *= (1.0 + r)
    return acc - 1.0


def _window(returns: List[float], n: int) -> List[float]:
    if len(returns) < n:
        return []
    return returns[-n:]


def build_price_features(
    symbol: str,
    as_of: datetime,
    horizon_minutes: int = 1440,
    lookback_days: int = 60,
) -> PriceFeatures:
    """
    Core Phase 2 price feature extractor.

    Uses the asset_returns table to build a small, interpretable set
    of features around `as_of` for a given symbol and horizon.
    """
    points = _fetch_returns(symbol, as_of, horizon_minutes, lookback_days)
    ts_list, r_list = zip(*points) if points else ([], [])

    n = len(r_list)

    # --- cumulative returns over windows (if enough data) ---
    def maybe_cum(n_days: int) -> float | None:
        # asset_returns is daily horizon, so n_days ~= n_points
        win = _window(list(r_list), n_days)
        return _cum_return(win) if win else None

    r_1d = maybe_cum(1)
    r_3d = maybe_cum(3)
    r_7d = maybe_cum(7)
    r_14d = maybe_cum(14)
    r_30d = maybe_cum(30)

    # --- realized vol over windows ---
    def maybe_vol(n_days: int) -> float | None:
        win = _window(list(r_list), n_days)
        if len(win) < 2:
            return None
        return float(pstdev(win))

    vol_3d = maybe_vol(3)
    vol_7d = maybe_vol(7)
    vol_30d = maybe_vol(30)

    # --- z-score for last 1d vs last 20d ---
    if n == 0:
        zscore_1d = None
    else:
        last_r = r_list[-1]
        baseline = _window(list(r_list), 20)
        if len(baseline) < 2:
            zscore_1d = None
        else:
            mu = mean(baseline)
            sigma = pstdev(baseline)
            if sigma == 0:
                zscore_1d = None
            else:
                zscore_1d = float((last_r - mu) / sigma)

    # --- max drawdown over last 30d ---
    def compute_max_drawdown_30d() -> float | None:
        win = _window(list(r_list), 30)
        if not win:
            return None
        # convert returns → cumulative equity curve
        equity = [1.0]
        for r in win:
            equity.append(equity[-1] * (1.0 + r))
        peak = equity[0]
        max_dd = 0.0
        for v in equity:
            if v > peak:
                peak = v
            dd = (v / peak) - 1.0  # <= 0
            if dd < max_dd:
                max_dd = dd
        return max_dd  # negative number

    max_dd_30d = compute_max_drawdown_30d()

    # choose an effective as_of (if none returned, just use input)
    as_of_effective = as_of
    if ts_list:
        # last available timestamp
        as_of_effective = ts_list[-1]

    return PriceFeatures(
        symbol=symbol,
        as_of=as_of_effective,
        horizon_minutes=horizon_minutes,
        lookback_days=lookback_days,
        n_points=n,
        r_1d=r_1d,
        r_3d=r_3d,
        r_7d=r_7d,
        r_14d=r_14d,
        r_30d=r_30d,
        vol_3d=vol_3d,
        vol_7d=vol_7d,
        vol_30d=vol_30d,
        zscore_1d=zscore_1d,
        max_drawdown_30d=max_dd_30d,
    )
