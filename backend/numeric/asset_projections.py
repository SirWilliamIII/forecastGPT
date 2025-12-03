# backend/numeric/asset_projections.py
# Storage helpers for model projections (e.g., Baker NFL win probabilities).

from datetime import datetime
from typing import Optional, List, Dict, Any

from db import get_conn
from psycopg.types.json import Jsonb

_ENSURED = False


def _ensure_table() -> None:
    """
    Create the asset_projections table if it doesn't exist.

    Primary key enforces idempotency across:
      symbol, as_of, horizon_minutes, metric, model_source
    """
    global _ENSURED
    if _ENSURED:
        return

    ddl = """
    CREATE TABLE IF NOT EXISTS asset_projections (
        symbol TEXT NOT NULL,
        as_of TIMESTAMPTZ NOT NULL,
        horizon_minutes INTEGER NOT NULL,
        metric TEXT NOT NULL,
        projected_value DOUBLE PRECISION NOT NULL,
        model_source TEXT NOT NULL,
        game_id INTEGER,
        run_id TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (symbol, as_of, horizon_minutes, metric, model_source)
    );
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)
            cur.execute(
                "ALTER TABLE asset_projections ADD COLUMN IF NOT EXISTS opponent TEXT"
            )
            cur.execute(
                "ALTER TABLE asset_projections ADD COLUMN IF NOT EXISTS opponent_name TEXT"
            )
            cur.execute(
                "ALTER TABLE asset_projections ADD COLUMN IF NOT EXISTS meta JSONB"
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_asset_projections_symbol_metric_asof
                ON asset_projections (symbol, metric, as_of DESC)
                """
            )
    _ENSURED = True


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
                FROM asset_projections
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
                INSERT INTO asset_projections (
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
