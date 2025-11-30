# backend/signals/price_context.py
from datetime import datetime, timedelta
from typing import List
from db import get_conn


def get_returns_for_time_window(
    symbol: str,
    horizon_minutes: int,
    center_ts: datetime,
    window_minutes: int = 60,
) -> List[float]:
    """
    Fetch realized returns for a given asset (symbol, horizon_minutes)
    in a +/- window around center_ts.

    Returns a list of floats (realized_return).
    """
    start = center_ts - timedelta(minutes=window_minutes)
    end = center_ts + timedelta(minutes=window_minutes)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT realized_return
                FROM asset_returns
                WHERE symbol = %s
                  AND horizon_minutes = %s
                  AND as_of BETWEEN %s AND %s
                ORDER BY as_of ASC
                """,
                (symbol, horizon_minutes, start, end),
            )
            rows = cur.fetchall()

    return [row["realized_return"] for row in rows]

