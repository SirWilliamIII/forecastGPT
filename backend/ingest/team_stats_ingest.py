"""
Team Statistics Ingestion

Fetches team statistics from ESPN API and stores them in the team_stats table.
Computes cumulative season statistics by aggregating game-level data.

Data Sources:
1. ESPN API (primary, free) - Game-level stats aggregated into season stats
2. SportsData.io (backup, requires valid key) - Pre-computed season stats

Usage:
    python -m ingest.team_stats_ingest
    python -m ingest.team_stats_ingest --season 2024 --week 10
    python -m ingest.team_stats_ingest --team DAL --seasons 3

Strategy:
    - ESPN provides game-level data (score, opponent, date)
    - We aggregate games into weekly cumulative stats
    - Store in team_stats table for ML feature building
"""

import argparse
import sys
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from db import get_conn
from utils import espn_api
from utils.team_config import load_team_config
from ingest.status import update_ingest_status
from config import get_nfl_team_display_names
from psycopg import sql


def compute_weekly_stats_from_games(
    games: List[Dict],
    team_abbr: str,
    season: int,
) -> List[Dict]:
    """
    Compute cumulative weekly stats from game-level data.

    Args:
        games: List of completed games from ESPN API
        team_abbr: Team abbreviation
        season: Season year

    Returns:
        List of weekly stat dictionaries
    """
    # Group games by week
    games_by_week = defaultdict(list)
    for game in games:
        week = game.get("week")
        if week:
            games_by_week[week].append(game)

    weekly_stats = []

    # Compute cumulative stats for each week
    for week in sorted(games_by_week.keys()):
        # Get all games up to and including this week
        cumulative_games = []
        for w in range(1, week + 1):
            cumulative_games.extend(games_by_week.get(w, []))

        if not cumulative_games:
            continue

        # Aggregate statistics
        total_points_scored = 0
        total_points_allowed = 0
        wins = 0
        losses = 0

        for game in cumulative_games:
            is_home = game["is_home"]
            home_score = game.get("home_score", 0)
            away_score = game.get("away_score", 0)

            if is_home:
                points_for = home_score
                points_against = away_score
            else:
                points_for = away_score
                points_against = home_score

            total_points_scored += points_for
            total_points_allowed += points_against

            if points_for > points_against:
                wins += 1
            elif points_for < points_against:
                losses += 1

        # Compute derived metrics
        games_played = wins + losses
        win_pct = wins / games_played if games_played > 0 else 0.0
        point_diff = total_points_scored - total_points_allowed
        avg_points_scored = total_points_scored / games_played if games_played > 0 else 0.0
        avg_points_allowed = total_points_allowed / games_played if games_played > 0 else 0.0

        weekly_stat = {
            "season": season,
            "week": week,
            "points_scored": float(total_points_scored),
            "points_allowed": float(total_points_allowed),
            "point_differential": float(point_diff),
            "win_count": wins,
            "loss_count": losses,
            "win_pct": win_pct,
            "games_played": games_played,
            "avg_points_scored": avg_points_scored,
            "avg_points_allowed": avg_points_allowed,
        }

        weekly_stats.append(weekly_stat)

    return weekly_stats


def fetch_team_games_for_season(team_abbr: str, season: int) -> List[Dict]:
    """
    Fetch all completed games for a team in a season.

    Args:
        team_abbr: Team abbreviation (e.g., 'DAL')
        season: Season year

    Returns:
        List of game dictionaries with scores and metadata
    """
    try:
        schedule_data = espn_api.get_team_schedule(team_abbr, season)
    except espn_api.ESPNAPIError as e:
        print(f"[team_stats] ✗ ESPN API error for {team_abbr} {season}: {e}")
        return []

    # Parse games from schedule
    games = []
    events = schedule_data.get("events", [])

    for event in events:
        competitions = event.get("competitions", [])
        if not competitions:
            continue

        competition = competitions[0]

        # Check if game is completed
        status = competition.get("status", {})
        status_type = status.get("type", {}).get("name", "")
        if status_type != "STATUS_FINAL":
            continue  # Skip scheduled/in-progress games

        # Get week number
        week = event.get("week", {}).get("number", 0)

        # Get competitors
        competitors = competition.get("competitors", [])
        if len(competitors) != 2:
            continue

        home_team = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away_team = next((c for c in competitors if c.get("homeAway") == "away"), None)

        if not home_team or not away_team:
            continue

        # Determine if this team is home or away
        home_abbr = home_team.get("team", {}).get("abbreviation", "")
        away_abbr = away_team.get("team", {}).get("abbreviation", "")

        is_home = (home_abbr == team_abbr)
        opponent_abbr = away_abbr if is_home else home_abbr

        # Get scores (handle both string and number formats)
        home_score_raw = home_team.get("score", 0)
        away_score_raw = away_team.get("score", 0)

        # ESPN sometimes returns score as a dict with 'value' key
        if isinstance(home_score_raw, dict):
            home_score = int(home_score_raw.get("value", 0))
        else:
            home_score = int(home_score_raw) if home_score_raw else 0

        if isinstance(away_score_raw, dict):
            away_score = int(away_score_raw.get("value", 0))
        else:
            away_score = int(away_score_raw) if away_score_raw else 0

        # Get game date
        date_str = event.get("date", "")
        try:
            game_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            print(f"[team_stats] ⚠ Invalid date format: {date_str}")
            continue

        game_data = {
            "week": week,
            "date": game_date,
            "is_home": is_home,
            "opponent_abbr": opponent_abbr,
            "home_score": home_score,
            "away_score": away_score,
        }

        games.append(game_data)

    return games


def insert_team_stat(team_symbol: str, stat: Dict, source: str = "espn") -> bool:
    """
    Insert or update a team stat row.

    Args:
        team_symbol: Team symbol (e.g., 'NFL:DAL_COWBOYS')
        stat: Stat dictionary with season, week, and metrics
        source: Data source ('espn' or 'sportsdata')

    Returns:
        True if inserted/updated, False if failed
    """
    # Use current time as as_of timestamp
    as_of = datetime.now(tz=timezone.utc)

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Upsert using ON CONFLICT
                cur.execute(
                    sql.SQL("""
                        INSERT INTO team_stats (
                            team_symbol, season, week,
                            points_scored, points_allowed, point_differential,
                            win_count, loss_count, win_pct,
                            as_of, source, created_at, updated_at
                        ) VALUES (
                            %s, %s, %s,
                            %s, %s, %s,
                            %s, %s, %s,
                            %s, %s, %s, %s
                        )
                        ON CONFLICT (team_symbol, season, week)
                        DO UPDATE SET
                            points_scored = EXCLUDED.points_scored,
                            points_allowed = EXCLUDED.points_allowed,
                            point_differential = EXCLUDED.point_differential,
                            win_count = EXCLUDED.win_count,
                            loss_count = EXCLUDED.loss_count,
                            win_pct = EXCLUDED.win_pct,
                            as_of = EXCLUDED.as_of,
                            source = EXCLUDED.source,
                            updated_at = EXCLUDED.updated_at
                    """),
                    (
                        team_symbol,
                        stat["season"],
                        stat["week"],
                        stat["points_scored"],
                        stat["points_allowed"],
                        stat["point_differential"],
                        stat["win_count"],
                        stat["loss_count"],
                        stat["win_pct"],
                        as_of,
                        source,
                        as_of,
                        as_of,
                    ),
                )
                conn.commit()
        return True

    except Exception as e:
        print(f"[team_stats] ✗ Error inserting stat: {e}")
        return False


def ingest_team_stats(
    team_abbr: str,
    team_symbol: str,
    seasons: int = 3,
    display_name: Optional[str] = None,
) -> int:
    """
    Ingest team statistics for multiple seasons.

    Args:
        team_abbr: ESPN team abbreviation
        team_symbol: NFL symbol (e.g., 'NFL:DAL_COWBOYS')
        seasons: Number of recent seasons to ingest
        display_name: Team display name for logging

    Returns:
        Number of stat rows inserted
    """
    if display_name is None:
        display_name = team_abbr

    print(f"\n{'='*60}")
    print(f"[team_stats] Ingesting stats for {display_name} ({team_symbol})")
    print(f"[team_stats] Seasons: {seasons}")
    print(f"{'='*60}")

    # Calculate season range
    current_year = datetime.now(tz=timezone.utc).year
    current_month = datetime.now(tz=timezone.utc).month

    if current_month < 9:
        current_season = current_year - 1
    else:
        current_season = current_year

    season_range = range(current_season - seasons + 1, current_season + 1)

    total_inserted = 0

    for season in season_range:
        print(f"\n[team_stats] Processing season {season}...")

        # Fetch games for this season
        games = fetch_team_games_for_season(team_abbr, season)

        if not games:
            print(f"[team_stats] ⚠ No completed games found for {season}")
            continue

        print(f"[team_stats] Found {len(games)} completed games")

        # Compute weekly stats
        weekly_stats = compute_weekly_stats_from_games(games, team_abbr, season)

        if not weekly_stats:
            print(f"[team_stats] ⚠ No weekly stats computed for {season}")
            continue

        # Insert each week's stats
        for stat in weekly_stats:
            success = insert_team_stat(team_symbol, stat, source="espn")
            if success:
                total_inserted += 1
                print(
                    f"[team_stats] ✓ Week {stat['week']:2d}: "
                    f"{stat['win_count']}-{stat['loss_count']} "
                    f"({stat['points_scored']:.0f}-{stat['points_allowed']:.0f})"
                )

    print(f"\n{'='*60}")
    print(f"[team_stats] ✓ Complete! Inserted {total_inserted} stat rows")
    print(f"{'='*60}\n")

    return total_inserted


def main():
    """Main ingestion entry point"""
    parser = argparse.ArgumentParser(description="Ingest NFL team statistics")
    parser.add_argument(
        "--team",
        type=str,
        help="Team abbreviation (e.g., DAL, KC). If not provided, processes all configured teams."
    )
    parser.add_argument(
        "--seasons",
        type=int,
        default=3,
        help="Number of recent seasons to ingest (default: 3)"
    )
    parser.add_argument(
        "--season",
        type=int,
        help="Specific season year to ingest (e.g., 2024)"
    )

    args = parser.parse_args()

    # Load team configuration
    team_map = load_team_config()
    team_display_names = get_nfl_team_display_names()

    print(f"\n{'='*60}")
    print(f"[team_stats] NFL Team Statistics Ingestion")
    print(f"[team_stats] Configured teams: {len(team_map)}")
    print(f"[team_stats] Data source: ESPN API (free)")
    print(f"{'='*60}\n")

    # Determine which teams to process
    if args.team:
        # Process single team
        team_abbr = args.team.upper()
        if team_abbr not in team_map:
            print(f"[team_stats] ✗ Team {team_abbr} not in configuration")
            print(f"[team_stats] Available teams: {', '.join(team_map.keys())}")
            sys.exit(1)

        teams_to_process = [(team_abbr, team_map[team_abbr])]
    else:
        # Process all configured teams
        teams_to_process = list(team_map.items())

    # Ingest stats for each team
    total_rows = 0
    for team_abbr, team_symbol in teams_to_process:
        display_name = team_display_names.get(team_abbr, f"{team_abbr} Team")

        inserted = ingest_team_stats(
            team_abbr=team_abbr,
            team_symbol=team_symbol,
            seasons=args.seasons,
            display_name=display_name,
        )

        total_rows += inserted

    # Update ingest status
    update_ingest_status("team_stats_ingest", total_rows)

    # Print summary
    print(f"\n{'='*60}")
    print(f"[team_stats] INGESTION COMPLETE")
    print(f"[team_stats] Total stat rows inserted: {total_rows}")
    print(f"{'='*60}\n")

    # Verify data in database
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    team_symbol,
                    COUNT(*) as stat_count,
                    MIN(season) as earliest_season,
                    MAX(season) as latest_season,
                    MAX(week) as latest_week
                FROM team_stats
                GROUP BY team_symbol
                ORDER BY team_symbol
            """)
            results = cur.fetchall()

    if results:
        print("\nDatabase Summary:")
        for row in results:
            print(
                f"  {row['team_symbol']}: "
                f"{row['stat_count']} weeks "
                f"(seasons {row['earliest_season']}-{row['latest_season']}, "
                f"latest: week {row['latest_week']})"
            )
        print()


if __name__ == "__main__":
    main()
