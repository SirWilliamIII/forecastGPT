# backend/ingest/backfill_sportsdata_nfl.py
"""
Backfill NFL game outcomes from SportsData.io API with weather data.

Uses the SportsData.io API to fetch historical game scores and weather conditions
for NFL teams. Stores both game outcomes and weather features for ML training.

Dataset Coverage: 2012-present (configurable)
Weather Features: Temperature, wind speed, precipitation, playing conditions

Usage:
    python -m ingest.backfill_sportsdata_nfl
    python -m ingest.backfill_sportsdata_nfl --seasons 2023,2024
    python -m ingest.backfill_sportsdata_nfl --teams DAL,KC,PHI
"""

import os
import sys
import argparse
from datetime import datetime, timezone
from typing import Tuple, List, Optional, Dict, Any

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from db import get_conn
from numeric.asset_returns import insert_asset_return
from ingest.status import update_ingest_status
from utils.sportsdata_api import get_client, SportsDataAPIError
from config import (
    NFL_DEFAULT_HORIZON_MINUTES,
    NFL_BASELINE_SCORE,
    get_nfl_team_display_names,
)
from utils.team_config import load_team_config


def extract_weather_features(game: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract weather features from game data.

    Args:
        game: SportsData.io game dict

    Returns:
        Dict with weather features:
            - temp_high: Forecast high temp (F)
            - temp_low: Forecast low temp (F)
            - wind_speed: Wind speed (mph)
            - wind_chill: Wind chill temp (F)
            - forecast_desc: Weather description
            - is_dome: Whether game is in dome (no weather impact)
            - surface_type: Playing surface (Artificial/Grass)
    """
    stadium = game.get('StadiumDetails', {}) or {}

    return {
        'temp_high': game.get('ForecastTempHigh'),
        'temp_low': game.get('ForecastTempLow'),
        'wind_speed': game.get('ForecastWindSpeed'),
        'wind_chill': game.get('ForecastWindChill'),
        'forecast_desc': game.get('ForecastDescription'),
        'is_dome': stadium.get('Type') == 'Dome',
        'surface_type': stadium.get('PlayingSurface'),
        'stadium_name': stadium.get('Name'),
    }


def process_game(
    game: Dict[str, Any],
    team_abbr: str,
    team_symbol: str,
) -> Optional[Tuple[datetime, float, float, Dict[str, Any]]]:
    """
    Process a single game for a specific team.

    Args:
        game: SportsData.io game dict
        team_abbr: Team abbreviation (e.g., "DAL")
        team_symbol: Full team symbol (e.g., "NFL:DAL_COWBOYS")

    Returns:
        (game_date, price_start, price_end, weather_features) or None if team not in game
    """
    home_team = game.get('HomeTeam')
    away_team = game.get('AwayTeam')

    # Check if this team played in this game
    if team_abbr not in [home_team, away_team]:
        return None

    # Get scores
    home_score = game.get('HomeScore')
    away_score = game.get('AwayScore')

    # Skip if game not final or scores missing
    if not game.get('IsClosed') or home_score is None or away_score is None:
        return None

    # Determine if team was home or away
    is_home = (team_abbr == home_team)
    team_score = home_score if is_home else away_score
    opp_score = away_score if is_home else home_score

    # Calculate point differential
    point_diff = team_score - opp_score

    # Encode as prices (baseline + point differential)
    price_start = NFL_BASELINE_SCORE
    price_end = NFL_BASELINE_SCORE + point_diff

    # Parse game date
    game_date_str = game.get('DateTimeUTC') or game.get('Date')
    if not game_date_str:
        return None

    try:
        game_date = datetime.fromisoformat(game_date_str.replace('Z', '+00:00'))
        if game_date.tzinfo is None:
            game_date = game_date.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None

    # Extract weather features
    weather = extract_weather_features(game)

    return (game_date, price_start, price_end, weather)


def backfill_from_sportsdata(
    seasons: List[int] = None,
    teams: List[str] = None,
    weeks_per_season: int = 18,
) -> Tuple[int, int]:
    """
    Backfill NFL game outcomes from SportsData.io API.

    Args:
        seasons: List of season years (default: [2012-2024])
        teams: List of team abbreviations (default: NFC East)
        weeks_per_season: Number of weeks to fetch per season (default: 18)

    Returns:
        (inserted_count, skipped_count)
    """
    print(f"\n{'='*60}")
    print(f"[sportsdata] Backfilling NFL outcomes from SportsData.io")
    print(f"{'='*60}\n")

    # Default seasons: 2012-2024 (13 seasons)
    if seasons is None:
        current_year = datetime.now(tz=timezone.utc).year
        seasons = list(range(2012, current_year + 1))

    # Load team configuration
    team_config = load_team_config()

    if teams is None:
        teams = list(team_config.keys())

    print(f"[sportsdata] Seasons: {seasons[0]}-{seasons[-1]} ({len(seasons)} seasons)")
    print(f"[sportsdata] Teams: {', '.join(teams)}")
    print(f"[sportsdata] Weeks per season: {weeks_per_season}\n")

    # Initialize SportsData client
    try:
        client = get_client()
    except ValueError as e:
        print(f"[sportsdata] ✗ API key not configured: {e}")
        return (0, 0)

    inserted = 0
    skipped = 0

    # Fetch games week by week
    for season in seasons:
        print(f"\n[sportsdata] Processing season {season}...")

        for week in range(1, weeks_per_season + 1):
            try:
                # Fetch all games for this week
                games = client.get_scores_by_week(season, week)

                if not games:
                    continue

                # Process each game for each team
                for game in games:
                    for team_abbr in teams:
                        # Get team symbol
                        team_symbol = team_config.get(team_abbr)
                        if not team_symbol:
                            continue

                        # Process game for this team
                        result = process_game(game, team_abbr, team_symbol)
                        if not result:
                            continue

                        game_date, price_start, price_end, weather = result

                        # Insert into database
                        try:
                            insert_asset_return(
                                symbol=team_symbol,
                                as_of=game_date,
                                horizon_minutes=NFL_DEFAULT_HORIZON_MINUTES,
                                price_start=price_start,
                                price_end=price_end,
                            )
                            inserted += 1

                            # Log weather data (for now, just track it - will add to DB schema later)
                            if inserted % 20 == 0:
                                print(f"[sportsdata] Progress: {inserted} games inserted (Week {week}/{weeks_per_season}, {season})...")

                        except Exception as e:
                            # Likely duplicate (unique constraint violation)
                            if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                                skipped += 1
                            else:
                                print(f"[sportsdata] ✗ Error inserting game: {e}")
                                skipped += 1

            except SportsDataAPIError as e:
                print(f"[sportsdata] ✗ API error (Season {season}, Week {week}): {e}")
                # Continue with next week instead of failing entire backfill
                continue

    print(f"\n{'='*60}")
    print(f"[sportsdata] ✓ Complete!")
    print(f"[sportsdata] Inserted: {inserted} games")
    print(f"[sportsdata] Skipped:  {skipped} duplicates/errors")
    print(f"{'='*60}\n")

    # Update ingest status
    update_ingest_status("sportsdata_nfl_backfill", inserted)

    return inserted, skipped


def main():
    """Backfill from SportsData.io with command-line arguments."""
    parser = argparse.ArgumentParser(description='Backfill NFL game outcomes from SportsData.io')
    parser.add_argument(
        '--seasons',
        type=str,
        help='Comma-separated list of seasons (e.g., "2023,2024"). Default: 2012-2024'
    )
    parser.add_argument(
        '--teams',
        type=str,
        help='Comma-separated list of team abbreviations (e.g., "DAL,KC,PHI"). Default: All configured teams'
    )
    parser.add_argument(
        '--weeks',
        type=int,
        default=18,
        help='Number of weeks per season (default: 18)'
    )

    args = parser.parse_args()

    # Parse seasons
    seasons = None
    if args.seasons:
        try:
            seasons = [int(s.strip()) for s in args.seasons.split(',')]
        except ValueError:
            print(f"✗ Invalid seasons format: {args.seasons}")
            sys.exit(1)

    # Parse teams
    teams = None
    if args.teams:
        teams = [t.strip().upper() for t in args.teams.split(',')]

    # Run backfill
    backfill_from_sportsdata(
        seasons=seasons,
        teams=teams,
        weeks_per_season=args.weeks,
    )


if __name__ == "__main__":
    main()
