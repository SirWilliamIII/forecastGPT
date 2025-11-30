# backend/signals/context_window.py

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Dict, Optional

from db import get_conn


@dataclass
class EventFeatures:
    as_of: datetime

    # basic density
    count_1d: int
    count_3d: int
    count_7d: int

    # how many distinct sources in last 7d
    distinct_sources_7d: int

    # fraction of last-7d events that look AI-related
    ai_share_7d: Optional[float]

    # recency of latest event (hours)
    hours_since_last_event: Optional[float]

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["as_of"] = self.as_of.isoformat()
        return d


def _window_counts(as_of: datetime, days: int) -> Dict[str, int]:
    start = as_of - timedelta(days=days)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    count(*) AS total,
                    count(DISTINCT source) AS distinct_sources
                FROM events
                WHERE timestamp BETWEEN %s AND %s
                """,
                (start, as_of),
            )
            row = conn.cursor().fetchone() if False else cur.fetchone()  # type: ignore

    row = row or {}
    return {
        "total": int(row.get("total") or 0),
        "distinct_sources": int(row.get("distinct_sources") or 0),
    }


def _ai_share_7d(as_of: datetime) -> Optional[float]:
    start = as_of - timedelta(days=7)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    count(*) AS total,
                    count(*) FILTER (
                        WHERE tags @> ARRAY['artificial intelligence']
                           OR tags @> ARRAY['Business / Artificial Intelligence']
                    ) AS ai_like
                FROM events
                WHERE timestamp BETWEEN %s AND %s
                """,
                (start, as_of),
            )
            row = cur.fetchone() or {}

    total = int(row.get("total") or 0)
    ai_like = int(row.get("ai_like") or 0)

    if total == 0:
        return None
    return ai_like / total


def _hours_since_last_event(as_of: datetime) -> Optional[float]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT timestamp
                FROM events
                WHERE timestamp <= %s
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (as_of,),
            )
            row = cur.fetchone()

    if not row:
        return None

    last_ts = row["timestamp"]
    delta = as_of - last_ts
    return delta.total_seconds() / 3600.0


def build_event_features(as_of: datetime) -> EventFeatures:
    """
    Event (news) context around `as_of`.

    We keep this small and interpretable:
      - how busy has the news tape been (1d/3d/7d)
      - how AI-heavy it is
      - how long since anything happened
    """
    c1 = _window_counts(as_of, days=1)
    c3 = _window_counts(as_of, days=3)
    c7 = _window_counts(as_of, days=7)

    ai_share = _ai_share_7d(as_of)
    hrs_last = _hours_since_last_event(as_of)

    return EventFeatures(
        as_of=as_of,
        count_1d=c1["total"],
        count_3d=c3["total"],
        count_7d=c7["total"],
        distinct_sources_7d=c7["distinct_sources"],
        ai_share_7d=ai_share,
        hours_since_last_event=hrs_last,
    )

