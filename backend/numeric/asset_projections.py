# backend/numeric/asset_projections.py
# Storage helpers for model projections (e.g., Baker NFL win probabilities).
# Note: Table was renamed from 'asset_projections' to 'projections' for simplicity.

from datetime import datetime
from typing import Optional, List, Dict, Any

from db import get_conn
from psycopg.types.json import Jsonb

def _ensure_table() -> None:
    """
    Verify the projections table exists.

    Note: Table is now created in db/init.sql at database initialization.
    This function is kept for backward compatibility but no longer creates the table.
    """
    # Table is created by init.sql - no dynamic creation needed
    pass


def get_latest_projections(
    *,
    symbol: str,
    metric: str,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Fetch latest projections for a symbol/metric."""
    _ensure_table()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT symbol, as_of, horizon_minutes, metric, projected_value,
                       model_source, game_id, run_id, opponent, opponent_name, meta,
                       created_at, updated_at
                FROM projections
                WHERE symbol = %s AND metric = %s
                ORDER BY as_of DESC
                LIMIT %s
                """,
                (symbol, metric, limit),
            )
            return cur.fetchall()


def upsert_projection(
    *,
    symbol: str,
    as_of: datetime,
    horizon_minutes: int,
    metric: str,
    projected_value: float,
    model_source: str,
    game_id: Optional[int] = None,
    run_id: Optional[str] = None,
    opponent: Optional[str] = None,
    opponent_name: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Insert or update a projection row.

    Idempotent: if the PK exists, update projected_value/run_id/game_id/timestamps.
    """
    _ensure_table()

    meta_json = Jsonb(meta) if meta is not None else None

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO projections (
                    symbol,
                    as_of,
                    horizon_minutes,
                    metric,
                    projected_value,
                    model_source,
                    game_id,
                    run_id,
                    opponent,
                    opponent_name,
                    meta
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol, as_of, horizon_minutes, metric, model_source)
                DO UPDATE SET
                    projected_value = EXCLUDED.projected_value,
                    game_id = EXCLUDED.game_id,
                    run_id = EXCLUDED.run_id,
                    opponent = EXCLUDED.opponent,
                    opponent_name = EXCLUDED.opponent_name,
                    meta = EXCLUDED.meta,
                    updated_at = now()
                """,
                (
                    symbol,
                    as_of,
                    horizon_minutes,
                    metric,
                    projected_value,
                    model_source,
                    game_id,
                    run_id,
                    opponent,
                    opponent_name,
                    meta_json,
                ),
            )
