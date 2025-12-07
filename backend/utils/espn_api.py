# backend/utils/espn_api.py
"""
ESPN API client for NFL game data.
Free public API, no key required.
"""

import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
import requests

ESPN_BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
TIMEOUT_SECONDS = 10
MAX_RETRIES = 3


class ESPNAPIError(Exception):
    """ESPN API request failed"""
    pass


def _fetch_with_retry(url: str, params: Optional[Dict] = None) -> dict:
    """Fetch URL with exponential backoff retry"""
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                delay = 2 ** attempt
                print(f"[espn_api] Error fetching {url}: {e}. Retrying in {delay}s...")
                time.sleep(delay)

    raise ESPNAPIError(f"Failed after {MAX_RETRIES} attempts: {last_error}")


def get_scoreboard(date: Optional[datetime] = None) -> dict:
    """
    Get scoreboard for a specific date.

    Args:
        date: Date to fetch (defaults to today). Must be timezone-aware UTC.

    Returns:
        Scoreboard data with all games for that date
    """
    if date is None:
        date = datetime.now(tz=timezone.utc)
    elif date.tzinfo is None:
        raise ValueError("date must be timezone-aware (use datetime.now(tz=timezone.utc))")

    # ESPN API expects YYYYMMDD format
    date_str = date.strftime("%Y%m%d")
    url = f"{ESPN_BASE_URL}/scoreboard"
    params = {"dates": date_str}

    return _fetch_with_retry(url, params)


def get_team_schedule(team_abbr: str, season: int) -> dict:
    """
    Get full season schedule for a team.

    Args:
        team_abbr: Team abbreviation (e.g., 'DAL' for Dallas Cowboys)
        season: Season year (e.g., 2024)

    Returns:
        Season schedule data
    """
    # ESPN team endpoint
    url = f"{ESPN_BASE_URL}/teams/{team_abbr}/schedule"
    params = {"season": season}

    return _fetch_with_retry(url, params)


def parse_game_outcome(
    game: dict,
    team_abbr: str,
) -> Optional[Tuple[datetime, str, str, int, int, bool, bool]]:
    """
    Parse a game from ESPN data.

    Args:
        game: Game data from ESPN API
        team_abbr: Team abbreviation to parse for

    Returns:
        Tuple of (game_date, opponent_abbr, opponent_name, points_for, points_against, is_win, is_home)
        Returns None if game is scheduled (not completed) or data is invalid
    """
    try:
        # Check if game is completed
        status = game.get("status", {}).get("type", {}).get("name", "")
        if status != "STATUS_FINAL":
            return None  # Only return completed games for backfill

        # Parse timestamp
        date_str = game.get("date")
        if not date_str:
            return None
        game_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if game_date.tzinfo is None:
            game_date = game_date.replace(tzinfo=timezone.utc)

        # Get teams
        competitions = game.get("competitions", [])
        if not competitions:
            return None

        competition = competitions[0]
        competitors = competition.get("competitors", [])

        if len(competitors) != 2:
            return None

        # Find our team and opponent
        our_team = None
        opponent = None

        for competitor in competitors:
            abbr = competitor.get("team", {}).get("abbreviation", "")
            if abbr.upper() == team_abbr.upper():
                our_team = competitor
            else:
                opponent = competitor

        if not our_team or not opponent:
            return None

        # Parse scores
        our_score = int(our_team.get("score", 0))
        opp_score = int(opponent.get("score", 0))

        # Determine outcome
        is_win = our_score > opp_score

        # Home/away
        is_home = our_team.get("homeAway", "").lower() == "home"

        # Opponent info
        opp_abbr = opponent.get("team", {}).get("abbreviation", "UNK")
        opp_name = opponent.get("team", {}).get("displayName", "Unknown")

        return (game_date, opp_abbr, opp_name, our_score, opp_score, is_win, is_home)

    except (KeyError, ValueError, TypeError) as e:
        print(f"[espn_api] Error parsing game: {e}")
        return None


def fetch_team_games(
    team_abbr: str,
    start_season: int,
    end_season: int,
) -> List[Tuple[datetime, str, str, int, int, bool, bool]]:
    """
    Fetch historical games for a team across multiple seasons.

    Args:
        team_abbr: Team abbreviation (e.g., 'DAL')
        start_season: First season to fetch (e.g., 2022)
        end_season: Last season to fetch (e.g., 2024)

    Returns:
        List of parsed game outcomes
    """
    all_games = []

    for season in range(start_season, end_season + 1):
        print(f"[espn_api] Fetching {team_abbr} games for season {season}...")

        try:
            # Use week-by-week scoreboard approach (more reliable)
            events = _fetch_season_week_by_week(season, team_abbr)

            # Parse each game
            season_games = 0
            for event in events:
                outcome = parse_game_outcome(event, team_abbr)
                if outcome:
                    all_games.append(outcome)
                    season_games += 1

            print(f"[espn_api] Found {season_games} completed games in {season}")

            # Rate limiting - be nice to ESPN
            time.sleep(1)

        except ESPNAPIError as e:
            print(f"[espn_api] Failed to fetch season {season}: {e}")
            continue

    return all_games


def _fetch_season_week_by_week(season: int, team_abbr: Optional[str] = None) -> List[dict]:
    """
    Fallback method: fetch entire season by iterating through weeks.
    NFL season runs ~September through February, ~18 weeks.

    Args:
        season: Season year
        team_abbr: Optional team filter - only return games for this team
    """
    events = []

    # NFL season typically starts early September
    start_date = datetime(season, 9, 1, tzinfo=timezone.utc)
    end_date = datetime(season + 1, 2, 28, tzinfo=timezone.utc)

    current_date = start_date

    while current_date <= end_date:
        try:
            scoreboard = get_scoreboard(current_date)
            week_events = scoreboard.get("events", [])

            # Filter by team if specified
            if team_abbr:
                filtered_events = []
                for event in week_events:
                    # Check if team is in this game
                    competitions = event.get("competitions", [])
                    if competitions:
                        competitors = competitions[0].get("competitors", [])
                        for competitor in competitors:
                            abbr = competitor.get("team", {}).get("abbreviation", "")
                            if abbr.upper() == team_abbr.upper():
                                filtered_events.append(event)
                                break
                events.extend(filtered_events)
            else:
                events.extend(week_events)

            # Jump ahead 7 days (weekly games)
            current_date += timedelta(days=7)
            time.sleep(0.5)  # Rate limiting

        except ESPNAPIError:
            current_date += timedelta(days=7)
            continue

    return events


def fetch_upcoming_games(
    team_abbr: str,
    max_days_ahead: int = 60,
) -> List[Tuple[datetime, str, str]]:
    """
    Fetch upcoming scheduled games for a team.

    Args:
        team_abbr: Team abbreviation (e.g., 'DAL')
        max_days_ahead: Maximum days to look ahead

    Returns:
        List of (game_date, opponent_abbr, opponent_name) for scheduled games
    """
    from datetime import timedelta

    upcoming = []
    end_date = datetime.now(tz=timezone.utc) + timedelta(days=max_days_ahead)
    current_date = datetime.now(tz=timezone.utc)

    # Iterate through weeks looking for scheduled games
    while current_date <= end_date:
        try:
            scoreboard = get_scoreboard(current_date)
            events = scoreboard.get("events", [])

            for event in events:
                # Check if this is a scheduled game (not completed)
                status = event.get("status", {}).get("type", {}).get("name", "")
                if status == "STATUS_FINAL":
                    continue  # Skip completed games

                # Check if team is in this game
                competitions = event.get("competitions", [])
                if not competitions:
                    continue

                competition = competitions[0]
                competitors = competition.get("competitors", [])

                if len(competitors) != 2:
                    continue

                # Find our team and opponent
                our_team = None
                opponent = None

                for competitor in competitors:
                    abbr = competitor.get("team", {}).get("abbreviation", "")
                    if abbr.upper() == team_abbr.upper():
                        our_team = competitor
                    else:
                        opponent = competitor

                if not our_team or not opponent:
                    continue

                # Parse game date
                date_str = event.get("date")
                if not date_str:
                    continue

                game_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                if game_date.tzinfo is None:
                    game_date = game_date.replace(tzinfo=timezone.utc)

                # Extract opponent info
                opp_abbr = opponent.get("team", {}).get("abbreviation", "UNK")
                opp_name = opponent.get("team", {}).get("displayName", "Unknown")

                upcoming.append((game_date, opp_abbr, opp_name))

            # Jump ahead 7 days
            current_date += timedelta(days=7)
            time.sleep(0.5)  # Rate limiting

        except ESPNAPIError:
            current_date += timedelta(days=7)
            continue

    return sorted(upcoming, key=lambda x: x[0])


if __name__ == "__main__":
    # Test with Dallas Cowboys
    print("Testing ESPN API with Dallas Cowboys...")
    games = fetch_team_games("DAL", 2023, 2024)

    print(f"\nFound {len(games)} total games:")
    for game_date, opp_abbr, opp_name, pts_for, pts_against, is_win, is_home in games[:5]:
        result = "W" if is_win else "L"
        location = "vs" if is_home else "@"
        print(f"{game_date.date()} {result} {location} {opp_name} ({pts_for}-{pts_against})")

    print("\nTesting upcoming games...")
    upcoming = fetch_upcoming_games("DAL")
    print(f"\nFound {len(upcoming)} upcoming games:")
    for game_date, opp_abbr, opp_name in upcoming[:5]:
        print(f"{game_date.date()} vs/@ {opp_name}")
