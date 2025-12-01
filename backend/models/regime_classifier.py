# backend/models/regime_classifier.py
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from signals.price_context import build_price_features


Regime = Literal["uptrend", "downtrend", "chop"]


@dataclass
class RegimeResult:
    symbol: str
    as_of: datetime
    regime: Regime
    score: float  # strength in that direction


def classify_regime(symbol: str, as_of: datetime) -> RegimeResult:
    feats = build_price_features(symbol, as_of)

    # Access dataclass fields directly (not dict keys)
    r_7d = feats.r_7d or 0.0
    vol_30d = feats.vol_30d or 0.0

    # tiny heuristic: strong positive 7d momentum vs volatility
    threshold = 0.02 + 0.5 * vol_30d

    if r_7d > threshold:
        regime: Regime = "uptrend"
        score = r_7d
    elif r_7d < -threshold:
        regime = "downtrend"
        score = -r_7d
    else:
        regime = "chop"
        score = abs(r_7d)

    return RegimeResult(symbol=symbol, as_of=as_of, regime=regime, score=score)
