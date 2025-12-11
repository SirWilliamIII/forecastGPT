# backend/utils/nfl_schedule.py
"""
NFL schedule utilities for determining current season/week and season dates.
"""

from datetime import datetime, timezone
from typing import Tuple


def get_nfl_season_info() -> Tuple[int, int, bool]:
    """
    Get current NFL season year, week number, and whether it's in-season.

    NFL Season Structure:
    - Season starts early September (typically Week 1 = Thursday after Labor Day)
    - Regular season: 18 weeks (Week 1-18)
    - Season year = year season started (e.g., 2024-2025 season = 2024)
    - Off-season: March-August

    Returns:
        (season_year, current_week, is_in_season)

    Examples:
        - December 10, 2024 → (2024, 14, True)
        - July 1, 2024 → (2024, 0, False)  # Off-season
        - February 1, 2025 → (2024, 18, True)  # Playoffs
    """
    now = datetime.now(tz=timezone.utc)
    month = now.month
    year = now.year

    # Determine season year
    # NFL season spans two calendar years (Sept-Feb)
    # Use the year the season STARTED
    if month >= 9:  # Sept-Dec = current year's season
        season_year = year
    elif month <= 2:  # Jan-Feb = previous year's season (playoffs)
        season_year = year - 1
    else:  # March-August = off-season
        return (year, 0, False)

    # Estimate current week
    # Week 1 typically starts ~Sept 7-10 (Thursday after Labor Day)
    # Simple heuristic: Week 1 = Sept 8
    season_start = datetime(season_year, 9, 8, tzinfo=timezone.utc)

    if now < season_start:
        # Before season starts (should only happen in Sept 1-7)
        return (season_year, 0, False)

    # Calculate weeks since season start
    days_since_start = (now - season_start).days
    current_week = min((days_since_start // 7) + 1, 18)

    # In-season check: Sept-Feb
    is_in_season = (month >= 9) or (month <= 2)

    return (season_year, current_week, is_in_season)


def should_run_nfl_updates() -> bool:
    """
    Determine if NFL outcome updates should run (only during season).

    Returns:
        True if currently in NFL season (Sept-Feb), False otherwise
    """
    _, _, is_in_season = get_nfl_season_info()
    return is_in_season


def get_weeks_to_fetch(lookback_weeks: int = 4) -> Tuple[int, int, int]:
    """
    Get the season year, start week, and end week for fetching recent games.

    Args:
        lookback_weeks: Number of weeks to look back (default: 4)

    Returns:
        (season_year, start_week, end_week)

    Example:
        If current week is 14, lookback=4:
        Returns (2024, 11, 14) to fetch weeks 11-14
    """
    season_year, current_week, is_in_season = get_nfl_season_info()

    if not is_in_season or current_week == 0:
        # Off-season or pre-season: fetch last week of previous season
        return (season_year - 1, 18, 18)

    # Calculate start week (don't go below 1)
    start_week = max(1, current_week - lookback_weeks + 1)
    end_week = current_week

    return (season_year, start_week, end_week)


if __name__ == "__main__":
    """Test the schedule utilities."""
    season_year, current_week, is_in_season = get_nfl_season_info()
    print(f"NFL Season Info:")
    print(f"  Season Year: {season_year}")
    print(f"  Current Week: {current_week}")
    print(f"  In Season: {is_in_season}")
    print(f"  Should Update: {should_run_nfl_updates()}")

    season, start, end = get_weeks_to_fetch(lookback_weeks=4)
    print(f"\nWeeks to Fetch (lookback=4):")
    print(f"  Season: {season}")
    print(f"  Weeks: {start}-{end}")
