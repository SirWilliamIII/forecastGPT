# backend/signals/context_window.py
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any
from db import get_conn

def get_events_near_time(
    as_of: datetime,
    window_minutes: int = 120,
) -> List[Dict[str, Any]]:
    """
    Return events within +/- window_minutes around as_of.
    This is the semantic context you'll later embed into features.
    """
    start = as_of - timedelta(minutes=window_minutes)
    end = as_of + timedelta(minutes=window_minutes)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, timestamp, source, url, title, summary, raw_text, categories, tags, embed
                FROM events
                WHERE timestamp BETWEEN %s AND %s
                ORDER BY timestamp ASC
                """,
                (start, end),
            )
            rows = cur.fetchall()

    return [dict(r) for r in rows]
