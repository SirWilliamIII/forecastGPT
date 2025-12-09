# backend/utils/pfr_scraper.py
"""
Pro Football Reference scraper (backup data source).
Provides historical game data when ESPN API is unavailable.
"""

import time
from datetime import datetime, timezone
from typing import List, Optional, Tuple
import requests
from bs4 import BeautifulSoup

PFR_BASE_URL = "https://www.pro-football-reference.com"
TIMEOUT_SECONDS = 10
MAX_RETRIES = 3

# Team abbreviation mapping (PFR uses different codes than ESPN)
PFR_TEAM_MAP = {
    "DAL": "dal",  # Dallas Cowboys
    "KC": "kan",   # Kansas City Chiefs
    "SF": "sfo",   # San Francisco 49ers
    "PHI": "phi",  # Philadelphia Eagles
    "BUF": "buf",  # Buffalo Bills
    "DET": "det",  # Detroit Lions
}


class PFRScraperError(Exception):
    """Pro Football Reference scraping failed"""
    pass


def _fetch_with_retry(url: str) -> str:
    """Fetch URL with retry logic"""
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            }
            resp = requests.get(url, headers=headers, timeout=TIMEOUT_SECONDS)
            resp.raise_for_status()
            return resp.text

        except requests.RequestException as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                delay = 2 ** attempt
                print(f"[pfr] Error fetching {url}: {e}. Retrying in {delay}s...")
                time.sleep(delay)

    raise PFRScraperError(f"Failed after {MAX_RETRIES} attempts: {last_error}")


def fetch_team_games(
    team_abbr: str,
    start_season: int,
    end_season: int,
) -> List[Tuple[datetime, str, str, int, int, bool, bool]]:
    """
    Scrape historical games from Pro Football Reference.

    Args:
        team_abbr: ESPN team abbreviation (e.g., 'DAL')
        start_season: First season year
        end_season: Last season year

    Returns:
        List of (game_date, opp_abbr, opp_name, pts_for, pts_against, is_win, is_home)
    """
    pfr_abbr = PFR_TEAM_MAP.get(team_abbr)
    if not pfr_abbr:
        raise PFRScraperError(f"Unknown team abbreviation: {team_abbr}")

    all_games = []

    for season in range(start_season, end_season + 1):
        print(f"[pfr] Scraping {team_abbr} games for {season}...")

        try:
            url = f"{PFR_BASE_URL}/teams/{pfr_abbr}/{season}.htm"
            html = _fetch_with_retry(url)
            soup = BeautifulSoup(html, 'html.parser')

            # Find the games table
            table = soup.find('table', {'id': 'games'})
            if not table:
                print(f"[pfr] No games table found for {season}")
                continue

            tbody = table.find('tbody')
            if not tbody:
                continue

            rows = tbody.find_all('tr')

            for row in rows:
                # Skip header rows and bye weeks
                if 'thead' in row.get('class', []):
                    continue

                game_data = _parse_game_row(row, team_abbr)
                if game_data:
                    all_games.append(game_data)

            print(f"[pfr] Found {len([g for g in all_games if g[0].year == season])} games in {season}")

            # Rate limiting - be respectful
            time.sleep(2)

        except PFRScraperError as e:
            print(f"[pfr] Failed to scrape season {season}: {e}")
            continue

    return all_games


def _parse_game_row(
    row,
    team_abbr: str,
) -> Optional[Tuple[datetime, str, str, int, int, bool, bool]]:
    """Parse a single game row from PFR table"""
    try:
        cells = row.find_all(['th', 'td'])
        if len(cells) < 10:
            return None

        # Skip playoff games (marked differently)
        week_cell = cells[0]
        week_text = week_cell.get_text(strip=True)
        if not week_text or not week_text.isdigit():
            # Could be playoff game or bye week
            if 'Bye' in week_text:
                return None

        # Date (format: "September 10")
        date_cell = cells[2]
        date_text = date_cell.get_text(strip=True)

        # Get year from boxscore link
        boxscore_link = cells[2].find('a')
        if not boxscore_link:
            return None

        href = boxscore_link.get('href', '')
        # href format: /boxscores/202309100dal.htm
        if len(href) < 20:
            return None

        year_str = href[12:16]
        year = int(year_str)

        # Reconstruct full date
        game_date = datetime.strptime(f"{date_text} {year}", "%B %d %Y")
        game_date = game_date.replace(tzinfo=timezone.utc)

        # Home/Away indicator
        location_cell = cells[4]
        location = location_cell.get_text(strip=True)
        is_home = location != '@'

        # Opponent
        opp_cell = cells[5]
        opp_name = opp_cell.get_text(strip=True)
        opp_abbr = opp_name[:3].upper()  # Rough approximation

        # Result (W/L)
        result_cell = cells[6]
        result = result_cell.get_text(strip=True)
        if not result or result == 'Bye':
            return None
        is_win = result.startswith('W')

        # Scores
        pts_for_cell = cells[7]
        pts_against_cell = cells[8]

        pts_for = int(pts_for_cell.get_text(strip=True) or 0)
        pts_against = int(pts_against_cell.get_text(strip=True) or 0)

        return (game_date, opp_abbr, opp_name, pts_for, pts_against, is_win, is_home)

    except (ValueError, IndexError, AttributeError) as e:
        print(f"[pfr] Error parsing row: {e}")
        return None


if __name__ == "__main__":
    # Test with Dallas Cowboys
    print("Testing PFR scraper with Dallas Cowboys...")
    try:
        games = fetch_team_games("DAL", 2023, 2024)

        print(f"\nFound {len(games)} total games:")
        for game_date, opp_abbr, opp_name, pts_for, pts_against, is_win, is_home in games[:5]:
            result = "W" if is_win else "L"
            location = "vs" if is_home else "@"
            print(f"{game_date.date()} {result} {location} {opp_name} ({pts_for}-{pts_against})")

    except PFRScraperError as e:
        print(f"Scraping failed: {e}")
