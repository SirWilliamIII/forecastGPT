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
    from vector_store import get_vector_store

    samples: List[Tuple[float, float]] = []

    # Get anchor event timestamp
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT timestamp
                FROM events
                WHERE id = %s
                """,
                (event_id,),
            )
            row = cur.fetchone()
            if not row:
                return []

            anchor_ts = row["timestamp"]

    # Get anchor vector from vector store
    vector_store = get_vector_store()
    query_vector = vector_store.get_vector(event_id)
    if not query_vector:
        return []

    # Search for nearest neighbors
    results = vector_store.search(
        query_vector=query_vector,
        limit=k_neighbors,
        exclude_id=event_id,
    )

    if not results:
        return []

    # Get neighbor IDs and fetch their timestamps
    neighbor_ids = [r.event_id for r in results]
    distance_map = {r.event_id: r.distance for r in results}

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Get neighbor timestamps (with lookback filter)
            # Also fetch text for symbol filtering
            start_ts = anchor_ts - timedelta(days=lookback_days)
            cur.execute(
                """
                SELECT id, timestamp, title, summary, clean_text
                FROM events
                WHERE id = ANY(%s)
                  AND timestamp BETWEEN %s AND %s
                """,
                (neighbor_ids, start_ts, anchor_ts),
            )
            neighbors = cur.fetchall()

            # Apply symbol-specific filtering for all asset types
            # This ensures BTC forecasts use BTC events, Cowboys use Cowboys events, etc.
            from signals.symbol_filter import is_symbol_mentioned

            filtered_neighbors = []
            for n in neighbors:
                # Build text to check
                text_to_check = " ".join(filter(None, [
                    n.get('title', ''),
                    n.get('summary', ''),
                    n.get('clean_text', ''),
                ]))

                # Check if this event mentions the symbol
                if is_symbol_mentioned(text_to_check, symbol):
                    filtered_neighbors.append(n)

            # For each neighbor, get realized_return after its timestamp
            for n in filtered_neighbors:
                event_uuid = str(n["id"])
                dist = distance_map.get(event_uuid, 0.0)
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

