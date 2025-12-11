# backend/ingest/backfill_github_nfl.py
"""
Backfill NFL game outcomes from GitHub CSV datasets with weather data.

Data Sources:
1. Nolanole/NFL-Weather-Project (2012-2018): Detailed weather data
2. nflverse/nfldata games.csv (2019-2024): Temp, wind, roof, surface

Coverage: 2012-2024 (~3000+ games with weather data)

Usage:
    python -m ingest.backfill_github_nfl
    python -m ingest.backfill_github_nfl --start-year 2015 --end-year 2020
    python -m ingest.backfill_github_nfl --teams DAL,KC,PHI
"""

import os
import sys
import argparse
from datetime import datetime, timezone
from typing import Tuple, List, Optional, Dict, Any
import pandas as pd

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from db import get_conn
from numeric.asset_returns import insert_asset_return
from ingest.status import update_ingest_status
from config import (
    NFL_DEFAULT_HORIZON_MINUTES,
    NFL_BASELINE_SCORE,
)
from utils.team_config import load_team_config

# Team name mapping (different datasets use different abbreviations)
TEAM_NAME_MAP = {
    # Nolanole dataset uses full names
    'Dallas Cowboys': 'DAL',
    'New York Giants': 'NYG',
    'Philadelphia Eagles': 'PHI',
    'Washington Redskins': 'WAS',
    'Washington Football Team': 'WAS',
    'Washington Commanders': 'WAS',
    'Kansas City Chiefs': 'KC',
    'San Francisco 49ers': 'SF',
    'Buffalo Bills': 'BUF',
    'Detroit Lions': 'DET',
    # nflverse uses abbreviations (already correct)
    'DAL': 'DAL',
    'NYG': 'NYG',
    'PHI': 'PHI',
    'WAS': 'WAS',
    'KC': 'KC',
    'SF': 'SF',
    'BUF': 'BUF',
    'DET': 'DET',
}


def normalize_team_name(team_name: str) -> Optional[str]:
    """Convert team name/abbreviation to standard abbreviation."""
    if not team_name:
        return None
    return TEAM_NAME_MAP.get(team_name.strip())


def process_nolanole_csv(
    csv_path: str,
    team_config: Dict[str, str],
    teams_filter: Optional[List[str]] = None,
    start_year: int = 2012,
    end_year: int = 2018,
) -> Tuple[int, int]:
    """
    Process Nolanole/NFL-Weather-Project CSV (2012-2018).

    Args:
        csv_path: Path to all_games_weather.csv
        team_config: Team abbreviation to symbol mapping
        teams_filter: Optional list of team abbreviations to include
        start_year: Start year (inclusive)
        end_year: End year (inclusive)

    Returns:
        (inserted_count, skipped_count)
    """
    print(f"\n[nolanole] Processing 2012-2018 weather data...")

    df = pd.read_csv(csv_path)

    # Filter by date range
    df['date'] = pd.to_datetime(df['date'])
    df = df[(df['date'].dt.year >= start_year) & (df['date'].dt.year <= end_year)]

    inserted = 0
    skipped = 0

    for idx, row in df.iterrows():
        # Skip if scores are missing (cancelled/postponed games)
        if pd.isna(row['score_home']) or pd.isna(row['score_away']):
            skipped += 1
            continue

        home_score = float(row['score_home'])
        away_score = float(row['score_away'])
        game_date = pd.to_datetime(row['date']).to_pydatetime().replace(tzinfo=timezone.utc)

        # Process home team
        home_abbr = normalize_team_name(row['home'])
        if home_abbr and (not teams_filter or home_abbr in teams_filter):
            home_symbol = team_config.get(home_abbr)
            if home_symbol:
                point_diff = home_score - away_score
                price_end = NFL_BASELINE_SCORE + point_diff

                try:
                    insert_asset_return(
                        symbol=home_symbol,
                        as_of=game_date,
                        horizon_minutes=NFL_DEFAULT_HORIZON_MINUTES,
                        price_start=NFL_BASELINE_SCORE,
                        price_end=price_end,
                    )
                    inserted += 1
                except Exception as e:
                    if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                        skipped += 1
                    else:
                        print(f"[nolanole] ✗ Error inserting {home_abbr}: {e}")
                        skipped += 1

        # Process away team
        away_abbr = normalize_team_name(row['away'])
        if away_abbr and (not teams_filter or away_abbr in teams_filter):
            away_symbol = team_config.get(away_abbr)
            if away_symbol:
                point_diff = away_score - home_score
                price_end = NFL_BASELINE_SCORE + point_diff

                try:
                    insert_asset_return(
                        symbol=away_symbol,
                        as_of=game_date,
                        horizon_minutes=NFL_DEFAULT_HORIZON_MINUTES,
                        price_start=NFL_BASELINE_SCORE,
                        price_end=price_end,
                    )
                    inserted += 1
                except Exception as e:
                    if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                        skipped += 1
                    else:
                        print(f"[nolanole] ✗ Error inserting {away_abbr}: {e}")
                        skipped += 1

        if inserted % 100 == 0 and inserted > 0:
            print(f"[nolanole] Progress: {inserted} games inserted...")

    print(f"[nolanole] Inserted: {inserted}, Skipped: {skipped}")
    return inserted, skipped


def process_nflverse_csv(
    csv_path: str,
    team_config: Dict[str, str],
    teams_filter: Optional[List[str]] = None,
    start_year: int = 2019,
    end_year: int = 2024,
) -> Tuple[int, int]:
    """
    Process nflverse games.csv (2019-2024).

    Args:
        csv_path: Path to games.csv
        team_config: Team abbreviation to symbol mapping
        teams_filter: Optional list of team abbreviations to include
        start_year: Start year (inclusive)
        end_year: End year (inclusive)

    Returns:
        (inserted_count, skipped_count)
    """
    print(f"\n[nflverse] Processing 2019-2024 games data...")

    df = pd.read_csv(csv_path)

    # Filter by date range and regular season
    df['gameday'] = pd.to_datetime(df['gameday'])
    df = df[
        (df['gameday'].dt.year >= start_year) &
        (df['gameday'].dt.year <= end_year) &
        (df['game_type'] == 'REG')  # Regular season only
    ]

    inserted = 0
    skipped = 0

    for idx, row in df.iterrows():
        # Skip if scores are missing (future/cancelled games)
        if pd.isna(row['home_score']) or pd.isna(row['away_score']):
            skipped += 1
            continue

        home_score = float(row['home_score'])
        away_score = float(row['away_score'])
        game_date = pd.to_datetime(row['gameday']).to_pydatetime().replace(tzinfo=timezone.utc)

        # Process home team
        home_abbr = normalize_team_name(row['home_team'])
        if home_abbr and (not teams_filter or home_abbr in teams_filter):
            home_symbol = team_config.get(home_abbr)
            if home_symbol:
                point_diff = home_score - away_score
                price_end = NFL_BASELINE_SCORE + point_diff

                try:
                    insert_asset_return(
                        symbol=home_symbol,
                        as_of=game_date,
                        horizon_minutes=NFL_DEFAULT_HORIZON_MINUTES,
                        price_start=NFL_BASELINE_SCORE,
                        price_end=price_end,
                    )
                    inserted += 1
                except Exception as e:
                    if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                        skipped += 1
                    else:
                        print(f"[nflverse] ✗ Error inserting {home_abbr}: {e}")
                        skipped += 1

        # Process away team
        away_abbr = normalize_team_name(row['away_team'])
        if away_abbr and (not teams_filter or away_abbr in teams_filter):
            away_symbol = team_config.get(away_abbr)
            if away_symbol:
                point_diff = away_score - home_score
                price_end = NFL_BASELINE_SCORE + point_diff

                try:
                    insert_asset_return(
                        symbol=away_symbol,
                        as_of=game_date,
                        horizon_minutes=NFL_DEFAULT_HORIZON_MINUTES,
                        price_start=NFL_BASELINE_SCORE,
                        price_end=price_end,
                    )
                    inserted += 1
                except Exception as e:
                    if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                        skipped += 1
                    else:
                        print(f"[nflverse] ✗ Error inserting {away_abbr}: {e}")
                        skipped += 1

        if inserted % 100 == 0 and inserted > 0:
            print(f"[nflverse] Progress: {inserted} games inserted...")

    print(f"[nflverse] Inserted: {inserted}, Skipped: {skipped}")
    return inserted, skipped


def main():
    """Backfill from GitHub CSV datasets."""
    parser = argparse.ArgumentParser(description='Backfill NFL game outcomes from GitHub CSVs')
    parser.add_argument(
        '--start-year',
        type=int,
        default=2012,
        help='Start year (default: 2012)'
    )
    parser.add_argument(
        '--end-year',
        type=int,
        default=2024,
        help='End year (default: 2024)'
    )
    parser.add_argument(
        '--teams',
        type=str,
        help='Comma-separated list of team abbreviations (e.g., "DAL,KC,PHI"). Default: All configured teams'
    )

    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"[github] Backfilling NFL outcomes from GitHub datasets")
    print(f"{'='*60}\n")
    print(f"[github] Years: {args.start_year}-{args.end_year}")

    # Load team configuration
    team_config = load_team_config()

    # Parse teams filter
    teams_filter = None
    if args.teams:
        teams_filter = [t.strip().upper() for t in args.teams.split(',')]
        print(f"[github] Teams filter: {', '.join(teams_filter)}")
    else:
        print(f"[github] Teams: All configured ({len(team_config)} teams)")

    total_inserted = 0
    total_skipped = 0

    # Process Nolanole dataset (2012-2018)
    nolanole_csv = "/tmp/nfl_weather_games.csv"
    if os.path.exists(nolanole_csv) and args.start_year <= 2018:
        inserted, skipped = process_nolanole_csv(
            nolanole_csv,
            team_config,
            teams_filter,
            max(args.start_year, 2012),
            min(args.end_year, 2018),
        )
        total_inserted += inserted
        total_skipped += skipped
    else:
        if args.start_year <= 2018:
            print(f"[github] ✗ Nolanole CSV not found: {nolanole_csv}")

    # Process nflverse dataset (2019-2024)
    nflverse_csv = "/tmp/nflverse_games.csv"
    if os.path.exists(nflverse_csv) and args.end_year >= 2019:
        inserted, skipped = process_nflverse_csv(
            nflverse_csv,
            team_config,
            teams_filter,
            max(args.start_year, 2019),
            args.end_year,
        )
        total_inserted += inserted
        total_skipped += skipped
    else:
        if args.end_year >= 2019:
            print(f"[github] ✗ nflverse CSV not found: {nflverse_csv}")

    print(f"\n{'='*60}")
    print(f"[github] ✓ Complete!")
    print(f"[github] Total Inserted: {total_inserted} games")
    print(f"[github] Total Skipped:  {total_skipped} duplicates/errors")
    print(f"{'='*60}\n")

    # Update ingest status
    update_ingest_status("github_nfl_backfill", total_inserted)


if __name__ == "__main__":
    main()
