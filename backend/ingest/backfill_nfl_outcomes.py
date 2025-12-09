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
from utils.team_config import load_team_config
from ingest.status import update_ingest_status
from config import (
    NFL_BACKFILL_SEASONS,
    NFL_DEFAULT_HORIZON_MINUTES,
    NFL_BASELINE_SCORE,
)

# Team display names mapping
TEAM_DISPLAY_NAMES = {
    "KC": "Kansas City Chiefs",
    "DAL": "Dallas Cowboys",
    "SF": "San Francisco 49ers",
    "PHI": "Philadelphia Eagles",
    "BUF": "Buffalo Bills",
    "DET": "Detroit Lions",
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
        # Use a baseline score and add/subtract point differential
        # This keeps prices positive while encoding win/loss information
        point_diff = float(pts_for - pts_against)

        price_start = NFL_BASELINE_SCORE
        price_end = NFL_BASELINE_SCORE + point_diff

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
                horizon_minutes=NFL_DEFAULT_HORIZON_MINUTES,
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
    """Backfill NFL games for all configured teams"""
    # Load team configuration
    team_map = load_team_config()

    print(f"\n{'='*60}")
    print(f"[nfl_backfill] NFL Outcomes Backfill")
    print(f"[nfl_backfill] Teams to process: {len(team_map)}")
    print(f"[nfl_backfill] Seasons: {NFL_BACKFILL_SEASONS}")
    print(f"{'='*60}\n")

    total_inserted = 0
    total_skipped = 0
    team_results = []

    # Process each team
    for espn_abbr, symbol in team_map.items():
        # Build team config
        display_name = TEAM_DISPLAY_NAMES.get(espn_abbr, f"{espn_abbr} Team")
        team_config = {
            "symbol": symbol,
            "espn_abbr": espn_abbr,
            "display_name": display_name,
        }

        # Backfill this team
        inserted, skipped = backfill_team_outcomes(
            team_config,
            seasons=NFL_BACKFILL_SEASONS,
            force=False,
        )

        total_inserted += inserted
        total_skipped += skipped

        # Validate data for this team
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
                    (symbol,),
                )
                stats = cur.fetchone()

                if stats and stats['total_games'] > 0:
                    wins = stats['wins'] or 0
                    losses = stats['losses'] or 0
                    total = stats['total_games']
                    avg_diff = stats['avg_point_diff'] or 0.0

                    team_results.append({
                        "team": display_name,
                        "total": total,
                        "wins": wins,
                        "losses": losses,
                        "win_rate": wins / total * 100 if total > 0 else 0,
                        "avg_diff": avg_diff,
                    })

    # Print summary
    print(f"\n{'='*60}")
    print(f"[nfl_backfill] BACKFILL COMPLETE")
    print(f"{'='*60}")
    print(f"Total games inserted: {total_inserted}")
    print(f"Total games skipped:  {total_skipped}")
    print(f"\n{'='*60}")
    print(f"[nfl_backfill] TEAM STATISTICS")
    print(f"{'='*60}\n")

    for result in team_results:
        print(f"{result['team']}:")
        print(f"  Total Games: {result['total']}")
        print(f"  Wins: {result['wins']}")
        print(f"  Losses: {result['losses']}")
        print(f"  Win Rate: {result['win_rate']:.1f}%")
        print(f"  Avg Point Differential: {result['avg_diff']:.1f}")
        print()

    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
