# backend/numeric/asset_returns.py
from uuid import uuid4
from datetime import datetime, timezone
from typing import List, Tuple
from db import get_conn


def insert_asset_return(
    symbol: str,
    as_of: datetime,
    horizon_minutes: int,
    price_start: float,
    price_end: float,
) -> None:
    """
    Insert a single realized return row.

    Idempotent because of:
      UNIQUE (symbol, as_of, horizon_minutes)
      ON CONFLICT (symbol, as_of, horizon_minutes) DO NOTHING
    """
    realized = (price_end - price_start) / price_start

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO asset_returns (
                    id,
                    symbol,
                    as_of,
                    horizon_minutes,
                    realized_return,
                    price_start,
                    price_end
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol, as_of, horizon_minutes)
                DO NOTHING
                """,
                (
                    uuid4(),
                    symbol,
                    as_of,
                    horizon_minutes,
                    realized,
                    price_start,
                    price_end,
                ),
            )


def get_past_returns(
    symbol: str,
    horizon_minutes: int,
    lookback_days: int = 365,
) -> List[Tuple[datetime, float]]:
    """Fetch historic realized returns for training / empirical distribution."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT as_of, realized_return
                FROM asset_returns
                WHERE symbol = %s
                  AND horizon_minutes = %s
                  AND as_of >= (now() - (%s || ' days')::interval)
                ORDER BY as_of ASC
                """,
                (symbol, horizon_minutes, lookback_days),
            )
            rows = cur.fetchall()
    return [(row["as_of"], row["realized_return"]) for row in rows]

