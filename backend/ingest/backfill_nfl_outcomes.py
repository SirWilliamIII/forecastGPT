# backend/ingest/backfill_nfl_outcomes.py
"""
Backfill NFL game outcomes into asset_returns table.

Multi-source strategy:
1. Try ESPN API first (free, official, reliable)
2. Fall back to Pro Football Reference (scraping, slower but comprehensive)
3. Store outcomes as "returns": Win=1.0, Loss=-1.0, Tie=0.0

Usage:
    python -m ingest.backfill_nfl_outcomes
"""

import os
import sys
from datetime import datetime, timezone, timedelta
from typing import List, Tuple, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from db import get_conn
from numeric.asset_returns import insert_asset_return
from utils import espn_api, pfr_scraper
from ingest.status import update_ingest_status

# Configuration
DEFAULT_SEASONS = int(os.getenv("NFL_BACKFILL_SEASONS", "3"))
DEFAULT_HORIZON_MINUTES = 24 * 60  # 1 day (simplification for now)

# Team configuration - start with Dallas Cowboys
COWBOYS_CONFIG = {
    "symbol": "NFL:DAL_COWBOYS",
    "espn_abbr": "DAL",
    "display_name": "Dallas Cowboys",
}


def fetch_games_multi_source(
    team_config: dict,
    start_season: int,
    end_season: int,
) -> List[Tuple[datetime, str, str, int, int, bool, bool]]:
    """
    Fetch games using multiple sources with intelligent fallback.

    Args:
        team_config: Team configuration dict
        start_season: First season to fetch
        end_season: Last season to fetch

    Returns:
        List of (game_date, opp_abbr, opp_name, pts_for, pts_against, is_win, is_home)
    """
    espn_abbr = team_config["espn_abbr"]
    games = []

    # Strategy 1: Try ESPN API first
    print(f"\n[nfl_backfill] Attempting ESPN API for {espn_abbr}...")
    try:
        games = espn_api.fetch_team_games(espn_abbr, start_season, end_season)
        if games:
            print(f"[nfl_backfill] ✓ ESPN API success: {len(games)} games")
            return games
    except Exception as e:
        print(f"[nfl_backfill] ✗ ESPN API failed: {e}")

    # Strategy 2: Fall back to Pro Football Reference
    print(f"[nfl_backfill] Attempting Pro Football Reference scraper...")
    try:
        games = pfr_scraper.fetch_team_games(espn_abbr, start_season, end_season)
        if games:
            print(f"[nfl_backfill] ✓ PFR scraper success: {len(games)} games")
            return games
    except Exception as e:
        print(f"[nfl_backfill] ✗ PFR scraper failed: {e}")

    print(f"[nfl_backfill] ✗ All sources failed for {espn_abbr}")
    return []


def check_existing_games(symbol: str) -> int:
    """Check how many games already exist in asset_returns"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM asset_returns
                WHERE symbol = %s
                """,
                (symbol,),
            )
            row = cur.fetchone()
            return row["count"] if row else 0


def backfill_team_outcomes(
    team_config: dict,
    seasons: int = DEFAULT_SEASONS,
    force: bool = False,
) -> Tuple[int, int]:
    """
    Backfill game outcomes for a team.

    Args:
        team_config: Team configuration
        seasons: Number of recent seasons to backfill
        force: If True, re-insert even if data exists

    Returns:
        (inserted_count, skipped_count)
    """
    symbol = team_config["symbol"]
    display_name = team_config["display_name"]

    print(f"\n{'='*60}")
    print(f"[nfl_backfill] Backfilling {display_name} ({symbol})")
    print(f"[nfl_backfill] Seasons: {seasons}")
    print(f"{'='*60}")

    # Check existing data
    existing = check_existing_games(symbol)
    if existing > 0 and not force:
        print(f"[nfl_backfill] Found {existing} existing games for {symbol}")
        print(f"[nfl_backfill] Use force=True to re-insert. Skipping...")
        return 0, existing

    # Calculate season range
    current_year = datetime.now(tz=timezone.utc).year
    current_month = datetime.now(tz=timezone.utc).month

    # NFL season starts in September, so if we're before September, go back one more year
    if current_month < 9:
        current_season = current_year - 1
    else:
        current_season = current_year

    start_season = current_season - seasons + 1
    end_season = current_season

    print(f"[nfl_backfill] Fetching seasons {start_season}-{end_season}...")

    # Fetch games from multiple sources
    games = fetch_games_multi_source(team_config, start_season, end_season)

    if not games:
        print(f"[nfl_backfill] ✗ No games found for {display_name}")
        return 0, 0

    # Sort games chronologically
    games.sort(key=lambda x: x[0])

    # Insert into asset_returns
    inserted = 0
    skipped = 0

    for game_date, opp_abbr, opp_name, pts_for, pts_against, is_win, is_home in games:
        # Convert outcome to "return"
        # Use a baseline of 100 and add/subtract point differential
        # This keeps prices positive while encoding win/loss information
        baseline = 100.0
        point_diff = float(pts_for - pts_against)

        price_start = baseline
        price_end = baseline + point_diff

        if pts_for > pts_against:
            realized_return = 1.0  # Win
        elif pts_for < pts_against:
            realized_return = -1.0  # Loss
        else:
            realized_return = 0.0  # Tie (rare)

        try:
            insert_asset_return(
                symbol=symbol,
                as_of=game_date,
                horizon_minutes=DEFAULT_HORIZON_MINUTES,
                price_start=price_start,
                price_end=price_end,
            )
            inserted += 1

            result = "W" if is_win else "L"
            location = "vs" if is_home else "@"
            print(
                f"[nfl_backfill] ✓ {game_date.date()} {result} {location} "
                f"{opp_name} ({pts_for}-{pts_against}) → return={realized_return}"
            )

        except Exception as e:
            # Likely duplicate (unique constraint violation)
            if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                skipped += 1
            else:
                print(f"[nfl_backfill] ✗ Error inserting game: {e}")
                skipped += 1

    print(f"\n{'='*60}")
    print(f"[nfl_backfill] ✓ Complete!")
    print(f"[nfl_backfill] Inserted: {inserted} games")
    print(f"[nfl_backfill] Skipped:  {skipped} duplicates/errors")
    print(f"{'='*60}\n")

    # Update ingest status
    update_ingest_status("nfl_outcomes_backfill", inserted)

    return inserted, skipped


def main():
    """Backfill Dallas Cowboys games"""
    inserted, skipped = backfill_team_outcomes(
        COWBOYS_CONFIG,
        seasons=DEFAULT_SEASONS,
        force=False,
    )

    # Validate data
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) as total_games,
                    SUM(CASE WHEN realized_return > 0 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN realized_return < 0 THEN 1 ELSE 0 END) as losses,
                    AVG(price_end) as avg_point_diff
                FROM asset_returns
                WHERE symbol = %s
                """,
                (COWBOYS_CONFIG["symbol"],),
            )
            stats = cur.fetchone()

            if stats and stats['total_games'] > 0:
                wins = stats['wins'] or 0
                losses = stats['losses'] or 0
                total = stats['total_games']
                avg_diff = stats['avg_point_diff'] or 0.0

                print(f"\n{'='*60}")
                print(f"[nfl_backfill] {COWBOYS_CONFIG['display_name']} Statistics:")
                print(f"  Total Games: {total}")
                print(f"  Wins: {wins}")
                print(f"  Losses: {losses}")
                print(f"  Win Rate: {wins / total * 100:.1f}%")
                print(f"  Avg Point Differential: {avg_diff:.1f}")
                print(f"{'='*60}\n")
            else:
                print(f"\n{'='*60}")
                print(f"[nfl_backfill] No games found for {COWBOYS_CONFIG['display_name']}")
                print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
