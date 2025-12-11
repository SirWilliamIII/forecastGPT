# backend/ingest/backfill_kaggle_nfl.py
"""
Backfill NFL game outcomes from Kaggle dataset (1999-2022).

Dataset: https://www.kaggle.com/datasets/philiphyde1/nfl-stats-1999-2022
Coverage: 2012-2024 (13 seasons) for NFC East teams

Usage:
    python -m ingest.backfill_kaggle_nfl
"""

import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Tuple
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
    get_nfl_team_display_names,
)


def estimate_game_date(season: int, week: int) -> datetime:
    """
    Estimate game date based on season and week number.
    
    NFL season typically starts first Thursday after Labor Day (early September).
    We'll use a simple heuristic: Week 1 = Sept 10, each week adds 7 days.
    """
    # Week 1 typically starts around September 10
    week_1_start = datetime(season, 9, 10, 20, 0, 0, tzinfo=timezone.utc)  # 8 PM ET
    
    # Add 7 days per week
    game_date = week_1_start + timedelta(days=7 * (week - 1))
    
    return game_date


def load_kaggle_dataset(csv_path: str, teams: list = None) -> pd.DataFrame:
    """
    Load Kaggle NFL dataset and filter to specified teams.

    Args:
        csv_path: Path to weekly_team_stats_offense.csv
        teams: List of team abbreviations (default: NFC East)

    Returns:
        DataFrame with columns: season, week, team, win, loss, total_off_points, total_def_points
    """
    if teams is None:
        teams = ['DAL', 'NYG', 'PHI', 'WAS']  # NFC East (WAS not WSH in this dataset)
    
    df = pd.read_csv(csv_path)
    
    # Filter to specified teams
    df = df[df['team'].isin(teams)].copy()
    
    # Select relevant columns
    df = df[['game_id', 'season', 'week', 'team', 'win', 'loss', 'tie', 
             'total_off_points', 'total_def_points']].copy()
    
    return df


def backfill_from_kaggle(
    csv_path: str,
    force: bool = False
) -> Tuple[int, int]:
    """
    Backfill NFL game outcomes from Kaggle dataset.
    
    Args:
        csv_path: Path to Kaggle CSV file
        force: If True, re-insert even if data exists
        
    Returns:
        (inserted_count, skipped_count)
    """
    print(f"\n{'='*60}")
    print(f"[kaggle] Backfilling NFL outcomes from Kaggle dataset")
    print(f"{'='*60}\n")
    
    # Load dataset
    df = load_kaggle_dataset(csv_path)
    
    print(f"[kaggle] Loaded {len(df)} games")
    print(f"[kaggle] Teams: {sorted(df['team'].unique())}")
    print(f"[kaggle] Seasons: {sorted(df['season'].unique())}")
    
    # Team mapping
    team_map = {
        'DAL': 'NFL:DAL_COWBOYS',
        'NYG': 'NFL:NYG_GIANTS',
        'PHI': 'NFL:PHI_EAGLES',
        'WAS': 'NFL:WSH_COMMANDERS',  # WAS in Kaggle dataset
    }
    
    team_names = get_nfl_team_display_names()
    
    inserted = 0
    skipped = 0
    
    for idx, row in df.iterrows():
        # Extract game info
        season = int(row['season'])
        week = int(row['week'])
        team_abbr = row['team']
        
        # Skip if team not in our mapping
        if team_abbr not in team_map:
            skipped += 1
            continue
        
        symbol = team_map[team_abbr]
        team_name = team_names.get(team_abbr, team_abbr)
        
        # Estimate game date
        game_date = estimate_game_date(season, week)
        
        # Determine outcome from point differential (more reliable than win/loss columns)
        pts_for = float(row['total_off_points']) if pd.notna(row['total_off_points']) else 0
        pts_against = float(row['total_def_points']) if pd.notna(row['total_def_points']) else 0

        # Skip if no scoring data (likely bye week or invalid entry)
        if pts_for == 0 and pts_against == 0:
            skipped += 1
            continue

        # Calculate prices using baseline + point differential
        point_diff = pts_for - pts_against
        price_start = NFL_BASELINE_SCORE
        price_end = NFL_BASELINE_SCORE + point_diff

        # Determine win/loss/tie from actual scores (not win/loss columns)
        if pts_for > pts_against:
            realized_return = 1.0  # Win
            result = "W"
        elif pts_for < pts_against:
            realized_return = -1.0  # Loss
            result = "L"
        else:
            realized_return = 0.0  # Tie
            result = "T"
        
        # Insert into database
        try:
            insert_asset_return(
                symbol=symbol,
                as_of=game_date,
                horizon_minutes=NFL_DEFAULT_HORIZON_MINUTES,
                price_start=price_start,
                price_end=price_end,
            )
            inserted += 1
            
            if inserted % 50 == 0:
                print(f"[kaggle] Progress: {inserted} games inserted...")
            
        except Exception as e:
            # Likely duplicate (unique constraint violation)
            if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                skipped += 1
            else:
                print(f"[kaggle] ✗ Error inserting game: {e}")
                skipped += 1
    
    print(f"\n{'='*60}")
    print(f"[kaggle] ✓ Complete!")
    print(f"[kaggle] Inserted: {inserted} games")
    print(f"[kaggle] Skipped:  {skipped} duplicates/errors")
    print(f"{'='*60}\n")
    
    # Update ingest status
    update_ingest_status("kaggle_nfl_backfill", inserted)
    
    return inserted, skipped


def main():
    """Backfill from Kaggle dataset."""
    # Path to downloaded Kaggle dataset
    csv_path = "/Users/will/.cache/kagglehub/datasets/philiphyde1/nfl-stats-1999-2022/versions/17/weekly_team_stats_offense.csv"
    
    if not os.path.exists(csv_path):
        print(f"[kaggle] ✗ Dataset not found: {csv_path}")
        print(f"[kaggle] Run this first:")
        print(f"  import kagglehub")
        print(f"  kagglehub.dataset_download('philiphyde1/nfl-stats-1999-2022')")
        sys.exit(1)
    
    backfill_from_kaggle(csv_path, force=False)


if __name__ == "__main__":
    main()
