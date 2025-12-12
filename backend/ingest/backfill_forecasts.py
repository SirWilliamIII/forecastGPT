"""
Backfill historical forecast snapshots for NFL teams.

This script retroactively computes what the ML forecast WOULD have been at specific
points in time, ensuring strict temporal correctness (no lookahead bias).

Key principles:
1. For each forecast computed at time T, ONLY use data strictly before T
2. Events must have timestamp < T
3. Game outcomes must have game_date < T
4. ML model features computed with as_of=T

Usage:
    # Backfill last 60 days for all NFL teams
    python -m ingest.backfill_forecasts

    # Backfill specific team with custom window
    python -m ingest.backfill_forecasts --symbol NFL:DAL_COWBOYS --days 90

    # Backfill specific forecast types
    python -m ingest.backfill_forecasts --types ml_model_v2,event_weighted

    # Dry run (no database writes)
    python -m ingest.backfill_forecasts --dry-run
"""

import argparse
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple
from uuid import UUID

from db import get_conn
from config import (
    NFL_FORECAST_BACKFILL_DAYS,
    FORECAST_BACKFILL_BATCH_SIZE,
    FORECAST_TYPES_ENABLED,
    NFL_FORECAST_MIN_EVENT_AGE_HOURS,
    NFL_FORECAST_MAX_EVENTS_PER_DAY,
    FORECAST_DAILY_SNAPSHOT_ENABLED,
    FORECAST_DAILY_SNAPSHOT_HOUR,
)
from models.nfl_event_forecaster import forecast_nfl_event
from signals.nfl_features import is_team_mentioned, get_team_regex_pattern


def get_nfl_team_symbols() -> List[str]:
    """Get all NFL team symbols from database."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT symbol
                FROM asset_returns
                WHERE symbol LIKE 'NFL:%'
                ORDER BY symbol
                """
            )
            rows = cur.fetchall()
            return [row["symbol"] for row in rows]


def get_team_events_in_window(
    team_symbol: str,
    start_date: datetime,
    end_date: datetime,
    max_events_per_day: int = NFL_FORECAST_MAX_EVENTS_PER_DAY,
) -> List[Dict]:
    """
    Get team-relevant events in time window, strictly before each timestamp.

    Args:
        team_symbol: Team symbol (e.g., "NFL:DAL_COWBOYS")
        start_date: Window start (timezone-aware UTC)
        end_date: Window end (timezone-aware UTC)
        max_events_per_day: Limit events to prevent explosion

    Returns:
        List of event dicts with id, timestamp, title
    """
    if start_date.tzinfo is None or end_date.tzinfo is None:
        raise ValueError("Dates must be timezone-aware UTC")

    team_pattern = get_team_regex_pattern(team_symbol)

    with get_conn() as conn:
        with conn.cursor() as cur:
            if team_pattern:
                # Database-side filtering with PostgreSQL regex
                cur.execute(
                    """
                    SELECT id, timestamp, title, summary, clean_text
                    FROM events
                    WHERE timestamp BETWEEN %s AND %s
                      AND 'sports' = ANY(categories)
                      AND (title ~* %s OR summary ~* %s OR clean_text ~* %s)
                    ORDER BY timestamp DESC
                    LIMIT %s
                    """,
                    (start_date, end_date, team_pattern, team_pattern, team_pattern, max_events_per_day * 60),
                )
            else:
                # Fallback: Load all sports events
                cur.execute(
                    """
                    SELECT id, timestamp, title, summary, clean_text
                    FROM events
                    WHERE timestamp BETWEEN %s AND %s
                      AND 'sports' = ANY(categories)
                    ORDER BY timestamp DESC
                    LIMIT %s
                    """,
                    (start_date, end_date, max_events_per_day * 60),
                )

            rows = cur.fetchall()

    # Filter in Python if needed (double-check team mentions)
    events = []
    for row in rows:
        if not team_pattern:
            # Need to filter in Python
            text = f"{row['title']} {row['summary'] or ''} {row['clean_text'] or ''}"
            if not is_team_mentioned(text, team_symbol):
                continue

        events.append({
            "id": row["id"],
            "timestamp": row["timestamp"],
            "title": row["title"],
        })

    return events


def compute_event_forecast_snapshot(
    event_id: UUID,
    event_timestamp: datetime,
    event_title: str,
    team_symbol: str,
    preloaded_games: Optional[list] = None,
    game_cache: Optional[dict] = None,
) -> Optional[Dict]:
    """
    Compute forecast snapshot for a specific event at its timestamp.

    CRITICAL: This ensures temporal correctness by only using data BEFORE event_timestamp.

    Args:
        event_id: Event UUID
        event_timestamp: Event timestamp (timezone-aware UTC)
        event_title: Event title for UI display
        team_symbol: Team symbol
        preloaded_games: Optional list of preloaded GameInfo objects (for performance)
        game_cache: Optional session cache dict (for performance)

    Returns:
        Dict with forecast snapshot data, or None if forecast unavailable
    """
    if event_timestamp.tzinfo is None:
        raise ValueError("event_timestamp must be timezone-aware UTC")

    # Use existing forecaster - it already enforces temporal correctness
    result = forecast_nfl_event(
        event_id=event_id,
        team_symbol=team_symbol,
        event_timestamp=event_timestamp,
        preloaded_games=preloaded_games,
        game_cache=game_cache,
    )

    if not result.forecast_available:
        return None

    # Truncate event title for summary
    event_summary = event_title[:200] if event_title else None

    return {
        "symbol": team_symbol,
        "forecast_type": "win_probability",
        "snapshot_at": event_timestamp,
        "forecast_value": result.win_probability,
        "confidence": result.confidence,
        "sample_size": result.sample_size,
        "model_source": "event_weighted",
        "model_version": "v1.0",
        "event_id": event_id,
        "event_summary": event_summary,
        "target_date": result.next_game_date,
        "horizon_minutes": result.next_game_date and int((result.next_game_date - event_timestamp).total_seconds() / 60),
        "metadata": {
            "similar_events": result.similar_events_found,
            "opponent": result.opponent,
            "days_until_game": result.days_until_game,
            "expected_point_diff": result.expected_point_diff,
        },
    }


def compute_daily_baseline_snapshot(
    team_symbol: str,
    snapshot_date: datetime,
) -> Optional[Dict]:
    """
    Compute baseline forecast snapshot for a specific date (no event).

    This provides a daily baseline trend independent of events.

    Args:
        team_symbol: Team symbol
        snapshot_date: Snapshot date at noon UTC (timezone-aware)

    Returns:
        Dict with snapshot data, or None if not enough data
    """
    if snapshot_date.tzinfo is None:
        raise ValueError("snapshot_date must be timezone-aware UTC")

    # Use naive forecaster for baseline
    from models.naive_asset_forecaster import forecast_asset

    # Look for next game from this snapshot date
    from signals.nfl_features import find_next_game

    next_game = find_next_game(team_symbol, snapshot_date)
    if not next_game:
        return None

    # Compute baseline forecast using historical win rate
    forecast_result = forecast_asset(
        symbol=team_symbol,
        horizon_minutes=next_game.horizon_minutes,
        lookback_days=90,
        as_of=snapshot_date,
    )

    if forecast_result.n_points < 5:
        return None

    # Convert expected return to win probability (baseline uses same conversion)
    from models.nfl_event_forecaster import convert_return_to_win_prob

    win_prob = convert_return_to_win_prob(
        forecast_result.expected_return or 0.0,
        method="linear",
    )

    return {
        "symbol": team_symbol,
        "forecast_type": "win_probability",
        "snapshot_at": snapshot_date,
        "forecast_value": win_prob,
        "confidence": forecast_result.confidence,
        "sample_size": forecast_result.n_points,
        "model_source": "naive_baseline",
        "model_version": "v1.0",
        "event_id": None,
        "event_summary": None,
        "target_date": next_game.game_date,
        "horizon_minutes": next_game.horizon_minutes,
        "metadata": {
            "lookback_days": 90,
            "mean_return": forecast_result.mean_return,
            "vol_return": forecast_result.vol_return,
            "opponent": next_game.opponent_abbr,
        },
    }


def insert_forecast_snapshots(snapshots: List[Dict]) -> Tuple[int, int]:
    """
    Batch insert forecast snapshots into database.

    Args:
        snapshots: List of snapshot dicts

    Returns:
        Tuple of (inserted_count, skipped_count)
    """
    if not snapshots:
        return 0, 0

    inserted = 0
    skipped = 0

    with get_conn() as conn:
        with conn.cursor() as cur:
            for snapshot in snapshots:
                try:
                    cur.execute(
                        """
                        INSERT INTO forecast_snapshots
                        (symbol, forecast_type, snapshot_at, forecast_value, confidence,
                         sample_size, model_source, model_version, event_id, event_summary,
                         target_date, horizon_minutes, metadata)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (symbol, forecast_type, model_source, snapshot_at) DO NOTHING
                        """,
                        (
                            snapshot["symbol"],
                            snapshot["forecast_type"],
                            snapshot["snapshot_at"],
                            snapshot["forecast_value"],
                            snapshot["confidence"],
                            snapshot["sample_size"],
                            snapshot["model_source"],
                            snapshot["model_version"],
                            snapshot["event_id"],
                            snapshot.get("event_summary"),
                            snapshot.get("target_date"),
                            snapshot.get("horizon_minutes"),
                            snapshot.get("metadata"),
                        ),
                    )
                    if cur.rowcount > 0:
                        inserted += 1
                    else:
                        skipped += 1
                except Exception as e:
                    print(f"[backfill_forecasts] Error inserting snapshot: {e}")
                    skipped += 1

            conn.commit()

    return inserted, skipped


def backfill_team_forecasts(
    team_symbol: str,
    days: int = NFL_FORECAST_BACKFILL_DAYS,
    forecast_types: List[str] = None,
    dry_run: bool = False,
) -> Dict[str, int]:
    """
    Backfill forecast snapshots for a single team.

    Args:
        team_symbol: Team symbol (e.g., "NFL:DAL_COWBOYS")
        days: Number of days to backfill
        forecast_types: List of forecast types to compute (default: from config)
        dry_run: If True, compute but don't insert

    Returns:
        Dict with statistics (snapshots_computed, snapshots_inserted, snapshots_skipped)
    """
    if forecast_types is None:
        forecast_types = FORECAST_TYPES_ENABLED

    now = datetime.now(tz=timezone.utc)
    start_date = now - timedelta(days=days)

    print(f"[backfill_forecasts] Starting backfill for {team_symbol}")
    print(f"[backfill_forecasts] Window: {start_date.date()} to {now.date()}")
    print(f"[backfill_forecasts] Forecast types: {forecast_types}")

    snapshots = []
    stats = {
        "events_processed": 0,
        "daily_snapshots_computed": 0,
        "event_snapshots_computed": 0,
        "snapshots_inserted": 0,
        "snapshots_skipped": 0,
    }

    # PERFORMANCE OPTIMIZATION: Preload games and create cache ONCE for this backfill run
    # This reduces ESPN API calls from 30+ to 1-2 per backfill
    print(f"[backfill_forecasts] Preloading team games...")
    from signals.nfl_features import preload_team_games

    preloaded_games = preload_team_games(
        team_symbol=team_symbol,
        start_date=start_date,
        end_date=now,
        max_days_ahead=30,
    )
    game_lookup_cache = {}  # Session-scoped cache for this backfill
    print(f"[backfill_forecasts] Preloaded {len(preloaded_games)} games")

    # 1. Compute event-based snapshots
    if "event_weighted" in forecast_types:
        print(f"[backfill_forecasts] Fetching team events...")
        events = get_team_events_in_window(team_symbol, start_date, now)
        print(f"[backfill_forecasts] Found {len(events)} relevant events")

        for event in events:
            # Skip very recent events (might not have enough data yet)
            age_hours = (now - event["timestamp"]).total_seconds() / 3600
            if age_hours < NFL_FORECAST_MIN_EVENT_AGE_HOURS:
                continue

            snapshot = compute_event_forecast_snapshot(
                event_id=event["id"],
                event_timestamp=event["timestamp"],
                event_title=event["title"],
                team_symbol=team_symbol,
                preloaded_games=preloaded_games,
                game_cache=game_lookup_cache,
            )

            if snapshot:
                snapshots.append(snapshot)
                stats["event_snapshots_computed"] += 1

                # Print progress
                if stats["event_snapshots_computed"] % 10 == 0:
                    print(f"[backfill_forecasts] Computed {stats['event_snapshots_computed']} event snapshots...")

            stats["events_processed"] += 1

    # 2. Compute daily baseline snapshots (noon UTC each day)
    if FORECAST_DAILY_SNAPSHOT_ENABLED and "baseline" in forecast_types:
        print(f"[backfill_forecasts] Computing daily baseline snapshots...")
        current_date = start_date.replace(
            hour=FORECAST_DAILY_SNAPSHOT_HOUR,
            minute=0,
            second=0,
            microsecond=0,
        )

        while current_date <= now:
            snapshot = compute_daily_baseline_snapshot(team_symbol, current_date)
            if snapshot:
                snapshots.append(snapshot)
                stats["daily_snapshots_computed"] += 1

            current_date += timedelta(days=1)

        print(f"[backfill_forecasts] Computed {stats['daily_snapshots_computed']} daily snapshots")

    # 3. Batch insert snapshots
    print(f"[backfill_forecasts] Total snapshots computed: {len(snapshots)}")

    if dry_run:
        print(f"[backfill_forecasts] DRY RUN - would insert {len(snapshots)} snapshots")
        stats["snapshots_inserted"] = 0
        stats["snapshots_skipped"] = 0
    else:
        # Insert in batches
        batch_size = FORECAST_BACKFILL_BATCH_SIZE
        for i in range(0, len(snapshots), batch_size):
            batch = snapshots[i:i + batch_size]
            inserted, skipped = insert_forecast_snapshots(batch)
            stats["snapshots_inserted"] += inserted
            stats["snapshots_skipped"] += skipped

            print(f"[backfill_forecasts] Batch {i//batch_size + 1}: {inserted} inserted, {skipped} skipped")

    print(f"[backfill_forecasts] ✓ Completed backfill for {team_symbol}")
    print(f"[backfill_forecasts] Stats: {stats}")

    return stats


def main(
    symbols: Optional[List[str]] = None,
    days: int = NFL_FORECAST_BACKFILL_DAYS,
    forecast_types: Optional[List[str]] = None,
    dry_run: bool = False,
) -> None:
    """
    Main backfill entry point.

    Args:
        symbols: List of team symbols to backfill (None = all NFL teams)
        days: Number of days to backfill
        forecast_types: List of forecast types (None = from config)
        dry_run: If True, compute but don't insert
    """
    if symbols is None:
        symbols = get_nfl_team_symbols()
        print(f"[backfill_forecasts] Auto-discovered {len(symbols)} NFL teams")
    else:
        print(f"[backfill_forecasts] Backfilling {len(symbols)} specified teams")

    if forecast_types is None:
        forecast_types = FORECAST_TYPES_ENABLED

    total_stats = {
        "teams_processed": 0,
        "total_snapshots_inserted": 0,
        "total_snapshots_skipped": 0,
        "total_events_processed": 0,
    }

    for symbol in symbols:
        try:
            stats = backfill_team_forecasts(
                team_symbol=symbol,
                days=days,
                forecast_types=forecast_types,
                dry_run=dry_run,
            )

            total_stats["teams_processed"] += 1
            total_stats["total_snapshots_inserted"] += stats["snapshots_inserted"]
            total_stats["total_snapshots_skipped"] += stats["snapshots_skipped"]
            total_stats["total_events_processed"] += stats["events_processed"]

        except Exception as e:
            print(f"[backfill_forecasts] ERROR processing {symbol}: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "="*70)
    print("[backfill_forecasts] ✓ BACKFILL COMPLETE")
    print("="*70)
    print(f"Teams processed: {total_stats['teams_processed']}")
    print(f"Events processed: {total_stats['total_events_processed']}")
    print(f"Snapshots inserted: {total_stats['total_snapshots_inserted']}")
    print(f"Snapshots skipped (duplicates): {total_stats['total_snapshots_skipped']}")
    print("="*70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill historical forecast snapshots")
    parser.add_argument(
        "--symbol",
        type=str,
        help="Specific team symbol to backfill (e.g., NFL:DAL_COWBOYS). If omitted, backfills all teams.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=NFL_FORECAST_BACKFILL_DAYS,
        help=f"Number of days to backfill (default: {NFL_FORECAST_BACKFILL_DAYS})",
    )
    parser.add_argument(
        "--types",
        type=str,
        help="Comma-separated forecast types (default: from config)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute forecasts but don't insert into database",
    )

    args = parser.parse_args()

    symbols = [args.symbol] if args.symbol else None
    forecast_types = args.types.split(",") if args.types else None

    main(
        symbols=symbols,
        days=args.days,
        forecast_types=forecast_types,
        dry_run=args.dry_run,
    )
