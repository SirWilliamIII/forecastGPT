# backend/signals/feature_extractor.py

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Tuple
from uuid import UUID

from db import get_conn
from signals.price_context import build_price_features
from signals.context_window import build_event_features


def build_features(
    symbol: str,
    as_of: datetime | None = None,
    horizon_minutes: int = 1440,
    lookback_days: int = 60,
) -> Dict[str, Any]:
    """
    Unified feature builder for a given asset + time.

    Combines:
      - price features (returns, vols, drawdown, z-score)
      - event features (news density + AI share + recency)
    """
    if as_of is None:
        as_of = datetime.now(tz=timezone.utc)

    price_feats = build_price_features(
        symbol=symbol,
        as_of=as_of,
        horizon_minutes=horizon_minutes,
        lookback_days=lookback_days,
    )
    event_feats = build_event_features(as_of=as_of)

    pf = price_feats.to_dict()
    ef = event_feats.to_dict()

    out: Dict[str, Any] = {
        "symbol": symbol,
        "as_of": ef["as_of"],  # ISO string
        "horizon_minutes": horizon_minutes,
    }

    # Price features with prefix
    for k, v in pf.items():
        if k in ("symbol", "as_of", "horizon_minutes", "lookback_days"):
            continue
        out[f"price_{k}"] = v

    # Event features with prefix
    for k, v in ef.items():
        if k == "as_of":
            continue
        out[f"event_{k}"] = v

    return out


def build_return_samples_for_event(
    event_id: UUID,
    symbol: str,
    horizon_minutes: int,
    k_neighbors: int = 25,
    lookback_days: int = 365,
    price_window_minutes: int = 60,
) -> List[Tuple[float, float]]:
    """
    For a given event_id and asset symbol, build a list of (distance, realized_return)
    samples using semantically nearest neighbor events.

    Steps:
      1. Fetch anchor event (timestamp + embed).
      2. Find k nearest neighbor events in embedding space within lookback_days.
      3. For each neighbor, fetch the first realized_return for (symbol, horizon_minutes)
         whose as_of is in [neighbor_ts, neighbor_ts + price_window_minutes].
      4. Return a list of (distance, realized_return).
    """
    samples: List[Tuple[float, float]] = []

    with get_conn() as conn:
        with conn.cursor() as cur:
            # 1) anchor event
            cur.execute(
                """
                SELECT timestamp, embed
                FROM events
                WHERE id = %s
                """,
                (event_id,),
            )
            row = cur.fetchone()
            if not row or row["embed"] is None:
                return []

            anchor_ts = row["timestamp"]
            anchor_embed = row["embed"]

            start_ts = anchor_ts - timedelta(days=lookback_days)

            # 2) nearest neighbors in embedding space, time-bounded
            cur.execute(
                """
                SELECT
                    id,
                    timestamp,
                    embed <-> %s::vector AS distance
                FROM events
                WHERE id <> %s
                  AND timestamp BETWEEN %s AND %s
                ORDER BY embed <-> %s::vector
                LIMIT %s
                """,
                (anchor_embed, event_id, start_ts, anchor_ts, anchor_embed, k_neighbors),
            )
            neighbors = cur.fetchall()

            # 3) for each neighbor, get realized_return after its timestamp
            for n in neighbors:
                dist = float(n["distance"])
                ts = n["timestamp"]
                window_end = ts + timedelta(minutes=price_window_minutes)

                cur.execute(
                    """
                    SELECT realized_return
                    FROM asset_returns
                    WHERE symbol = %s
                      AND horizon_minutes = %s
                      AND as_of >= %s
                      AND as_of <= %s
                    ORDER BY as_of ASC
                    LIMIT 1
                    """,
                    (symbol, horizon_minutes, ts, window_end),
                )
                r_row = cur.fetchone()
                if not r_row:
                    continue

                realized = float(r_row["realized_return"])
                samples.append((dist, realized))

    return samples

