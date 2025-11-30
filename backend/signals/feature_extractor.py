# backend/signals/feature_extractor.py
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple
from uuid import UUID

from db import get_conn
from signals.price_context import get_returns_for_time_window


def get_event_anchor(event_id: UUID) -> Dict[str, Any]:
    """
    Fetch the anchor event's timestamp and embedding.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, timestamp, embed
                FROM events
                WHERE id = %s
                """,
                (event_id,),
            )
            row = cur.fetchone()

    if not row:
        raise ValueError(f"Event {event_id} not found")

    row_dict = dict(row)
    if row_dict["embed"] is None:
        raise ValueError(f"Event {event_id} has no embedding")

    return row_dict


def get_neighbor_events(
    anchor_id: UUID,
    anchor_embed: List[float],
    anchor_ts: datetime,
    lookback_days: int = 365,
    k_neighbors: int = 25,
) -> List[Dict[str, Any]]:
    """
    Get the top-k nearest neighbor events (by embedding distance),
    restricted to events in the PAST within lookback_days.
    """
    start_ts = anchor_ts - timedelta(days=lookback_days)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    timestamp,
                    embed <-> %s::vector AS distance
                FROM events
                WHERE id <> %s
                  AND timestamp BETWEEN %s AND %s
                  AND embed IS NOT NULL
                ORDER BY embed <-> %s::vector
                LIMIT %s
                """,
                (anchor_embed, anchor_id, start_ts, anchor_ts, anchor_embed, k_neighbors),
            )
            rows = cur.fetchall()

    return [dict(r) for r in rows]


def build_return_samples_for_event(
    event_id: UUID,
    symbol: str,
    horizon_minutes: int,
    k_neighbors: int = 25,
    lookback_days: int = 365,
    price_window_minutes: int = 60,
) -> List[Tuple[float, float]]:
    """
    For a given event_id, find nearest neighbor events and attach realized returns
    around their timestamps.

    Returns a list of (distance, realized_return) tuples.
    """
    anchor = get_event_anchor(event_id)
    anchor_ts: datetime = anchor["timestamp"]
    anchor_embed = anchor["embed"]

    neighbors = get_neighbor_events(
        anchor_id=event_id,
        anchor_embed=anchor_embed,
        anchor_ts=anchor_ts,
        lookback_days=lookback_days,
        k_neighbors=k_neighbors,
    )

    samples: List[Tuple[float, float]] = []

    for n in neighbors:
        n_ts: datetime = n["timestamp"]
        dist: float = float(n["distance"])

        # For each neighbor event, fetch price returns near its timestamp
        rets = get_returns_for_time_window(
            symbol=symbol,
            horizon_minutes=horizon_minutes,
            center_ts=n_ts,
            window_minutes=price_window_minutes,
        )

        for r in rets:
            samples.append((dist, float(r)))

    return samples

