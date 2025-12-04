# backend/numeric/asset_returns.py
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
      PRIMARY KEY (symbol, as_of, horizon_minutes)
      ON CONFLICT DO NOTHING

    Args:
        symbol: Asset symbol
        as_of: Reference timestamp (must be timezone-aware)
        horizon_minutes: Forecast horizon
        price_start: Starting price
        price_end: Ending price

    Raises:
        ValueError: If price_start <= 0 or price_end <= 0
    """
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware (use datetime.now(tz=timezone.utc))")

    if price_start <= 0:
        raise ValueError(f"price_start must be positive, got {price_start}")

    if price_end <= 0:
        raise ValueError(f"price_end must be positive, got {price_end}")

    realized = (price_end - price_start) / price_start

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO asset_returns (
                    symbol,
                    as_of,
                    horizon_minutes,
                    realized_return,
                    price_start,
                    price_end
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol, as_of, horizon_minutes)
                DO NOTHING
                """,
                (
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
    as_of: datetime | None = None,
) -> List[Tuple[datetime, float]]:
    """
    Fetch historic realized returns for training / empirical distribution.

    Args:
        symbol: Asset symbol
        horizon_minutes: Forecast horizon
        lookback_days: How many days back to look
        as_of: Reference time (defaults to now in UTC). Must be timezone-aware.
    """
    if as_of is None:
        as_of = datetime.now(tz=timezone.utc)
    elif as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware (use datetime.now(tz=timezone.utc))")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT as_of, realized_return
                FROM asset_returns
                WHERE symbol = %s
                  AND horizon_minutes = %s
                  AND as_of >= (%s - (%s || ' days')::interval)
                ORDER BY as_of ASC
                """,
                (symbol, horizon_minutes, as_of, lookback_days),
            )
            rows = cur.fetchall()
    return [(row["as_of"], row["realized_return"]) for row in rows]

