"""
SportsData.io NFL API Client

This module provides a Python client for the SportsData.io NFL API.
Documentation: https://sportsdata.io/developers/api-documentation/nfl

API Structure:
    Base URL: https://api.sportsdata.io/v3/nfl/{feed-type}/json/{endpoint}
    Authentication: API key via query parameter or header

Usage:
    from utils.sportsdata_api import SportsDataClient

    client = SportsDataClient(api_key="your-key")

    # Get team season stats
    stats = client.get_team_season_stats(season=2024)

    # Get standings
    standings = client.get_standings(season=2024)

    # Get scores by week
    scores = client.get_scores_by_week(season=2024, week=10)

Environment Variables:
    SPORTSDATA_API_KEY: API key for SportsData.io
    SPORTSDATA_BASE_URL: Base URL (defaults to production)
    SPORTSDATA_TIMEOUT: Request timeout in seconds (default: 15)

IMPORTANT: This API uses rate limiting. Free tier has limits.
Check your plan at https://sportsdata.io/developers
"""

import os
import time
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class SportsDataAPIError(Exception):
    """Base exception for SportsData.io API errors"""
    pass


class SportsDataRateLimitError(SportsDataAPIError):
    """Raised when API rate limit is exceeded"""
    pass


class SportsDataClient:
    """
    Client for SportsData.io NFL API.

    Handles authentication, retries, rate limiting, and error handling.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 15,
        max_retries: int = 3,
    ):
        """
        Initialize SportsData.io API client.

        Args:
            api_key: API key (defaults to SPORTSDATA_API_KEY env var)
            base_url: Base API URL (defaults to production)
            timeout: Request timeout in seconds
            max_retries: Number of retry attempts for failed requests
        """
        self.api_key = api_key or os.getenv("SPORTSDATA_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "SportsData.io API key required. "
                "Set SPORTSDATA_API_KEY environment variable or pass api_key parameter."
            )

        self.base_url = base_url or os.getenv(
            "SPORTSDATA_BASE_URL",
            "https://api.sportsdata.io/v3/nfl/"
        )
        self.timeout = int(os.getenv("SPORTSDATA_TIMEOUT", str(timeout)))

        # Configure session with retries
        self.session = requests.Session()

        # Retry strategy: retry on 429 (rate limit), 500, 502, 503, 504
        retry_strategy = Retry(
            total=max_retries,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            backoff_factor=2,  # Exponential backoff: 2, 4, 8 seconds
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _build_url(self, feed_type: str, endpoint: str) -> str:
        """
        Build full API URL.

        Args:
            feed_type: Feed type (scores, stats, odds, etc.)
            endpoint: Endpoint name

        Returns:
            Full URL with API key
        """
        # URL format: {base_url}/{feed_type}/json/{endpoint}?key={api_key}
        url = urljoin(self.base_url, f"{feed_type}/json/{endpoint}")
        return url

    def _make_request(self, feed_type: str, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Make API request with error handling.

        Args:
            feed_type: Feed type (scores, stats, etc.)
            endpoint: Endpoint name
            params: Optional query parameters

        Returns:
            JSON response as dict

        Raises:
            SportsDataRateLimitError: If rate limit exceeded
            SportsDataAPIError: For other API errors
        """
        url = self._build_url(feed_type, endpoint)

        # Add API key to params
        if params is None:
            params = {}
        params["key"] = self.api_key

        try:
            response = self.session.get(
                url,
                params=params,
                timeout=self.timeout,
            )

            # Handle rate limiting
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "60")
                raise SportsDataRateLimitError(
                    f"Rate limit exceeded. Retry after {retry_after} seconds."
                )

            # Raise for HTTP errors
            response.raise_for_status()

            # Parse JSON response
            return response.json()

        except requests.exceptions.Timeout:
            raise SportsDataAPIError(f"Request timed out after {self.timeout} seconds")
        except requests.exceptions.HTTPError as e:
            raise SportsDataAPIError(f"HTTP error: {e}")
        except requests.exceptions.RequestException as e:
            raise SportsDataAPIError(f"Request failed: {e}")
        except ValueError as e:
            raise SportsDataAPIError(f"Invalid JSON response: {e}")

    # ═══════════════════════════════════════════════════════════════════
    # Team Statistics Endpoints
    # ═══════════════════════════════════════════════════════════════════

    def get_team_season_stats(self, season: int) -> List[Dict[str, Any]]:
        """
        Get team season statistics for all teams.

        Endpoint: /stats/json/TeamSeasonStats/{season}

        Args:
            season: Season year (e.g., 2024)

        Returns:
            List of team stat dictionaries

        Example:
            stats = client.get_team_season_stats(2024)
            for team in stats:
                print(f"{team['Team']}: {team['Score']} points scored")
        """
        endpoint = f"TeamSeasonStats/{season}"
        return self._make_request("stats", endpoint)

    def get_standings(self, season: int) -> List[Dict[str, Any]]:
        """
        Get NFL standings for a season.

        Endpoint: /scores/json/Standings/{season}

        Args:
            season: Season year (e.g., 2024)

        Returns:
            List of team standing dictionaries

        Example:
            standings = client.get_standings(2024)
            for team in standings:
                print(f"{team['Team']}: {team['Wins']}-{team['Losses']}")
        """
        endpoint = f"Standings/{season}"
        return self._make_request("scores", endpoint)

    # ═══════════════════════════════════════════════════════════════════
    # Game/Schedule Endpoints
    # ═══════════════════════════════════════════════════════════════════

    def get_scores_by_week(self, season: int, week: int) -> List[Dict[str, Any]]:
        """
        Get game scores for a specific week.

        Endpoint: /scores/json/ScoresByWeek/{season}/{week}

        Args:
            season: Season year (e.g., 2024)
            week: Week number (1-18 regular, 19-22 playoffs)

        Returns:
            List of game score dictionaries

        Example:
            games = client.get_scores_by_week(2024, 10)
            for game in games:
                print(f"{game['AwayTeam']} @ {game['HomeTeam']}: {game['HomeScore']}")
        """
        endpoint = f"ScoresByWeek/{season}/{week}"
        return self._make_request("scores", endpoint)

    def get_schedules(self, season: int) -> List[Dict[str, Any]]:
        """
        Get full season schedule.

        Endpoint: /scores/json/Schedules/{season}

        Args:
            season: Season year (e.g., 2024)

        Returns:
            List of scheduled games

        Example:
            schedule = client.get_schedules(2024)
            for game in schedule:
                print(f"Week {game['Week']}: {game['AwayTeam']} @ {game['HomeTeam']}")
        """
        endpoint = f"Schedules/{season}"
        return self._make_request("scores", endpoint)

    def get_team_game_stats(self, season: int, week: int, team: str) -> Dict[str, Any]:
        """
        Get team statistics for a specific game.

        Endpoint: /stats/json/TeamGameStats/{season}/{week}/{team}

        Args:
            season: Season year
            week: Week number
            team: Team abbreviation (e.g., "DAL", "KC")

        Returns:
            Team game statistics dictionary

        Example:
            stats = client.get_team_game_stats(2024, 10, "DAL")
            print(f"Cowboys scored {stats['Score']} points in Week 10")
        """
        endpoint = f"TeamGameStats/{season}/{week}/{team}"
        return self._make_request("stats", endpoint)

    # ═══════════════════════════════════════════════════════════════════
    # News Endpoints
    # ═══════════════════════════════════════════════════════════════════

    def get_news(self) -> List[Dict[str, Any]]:
        """
        Get recent news articles for all teams.

        Endpoint: /scores/json/News

        Returns:
            List of news article dictionaries (limited to most recent ~4-5 items)

        Note:
            Free tier returns very few recent items. For historical data,
            use get_news_by_date() instead.
        """
        endpoint = "News"
        return self._make_request("scores", endpoint)

    def get_news_by_date(self, date: str) -> List[Dict[str, Any]]:
        """
        Get news articles for a specific date.

        Endpoint: /scores/json/NewsByDate/{date}

        Args:
            date: Date in YYYY-MM-DD format (e.g., "2024-11-28")

        Returns:
            List of news article dictionaries with:
                - NewsID: Unique identifier
                - Title: Article headline
                - Content: Full article text
                - Updated: Timestamp (ISO format)
                - Source: News source (e.g., "RotoBaller")
                - Categories: Category string (e.g., "Injuries")
                - Url: Article URL
                - PlayerID, TeamID: Related entities
                - Team: Team abbreviation

        Example:
            news = client.get_news_by_date("2024-11-28")
            for article in news:
                if article['Team'] == 'DAL':
                    print(f"{article['Title']}: {article['Content'][:100]}...")
        """
        endpoint = f"NewsByDate/{date}"
        return self._make_request("scores", endpoint)

    def get_news_by_team(self, team: str) -> List[Dict[str, Any]]:
        """
        Get recent news articles for a specific team.

        Endpoint: /scores/json/NewsByTeam/{team}

        Args:
            team: Team abbreviation (e.g., "DAL", "KC")

        Returns:
            List of news article dictionaries (see get_news() for field descriptions)

        Example:
            news = client.get_news_by_team("DAL")
            for article in news:
                if "Injuries" in article.get("Categories", ""):
                    print(f"{article['Title']}: {article['Content'][:100]}...")
        """
        endpoint = f"NewsByTeam/{team}"
        return self._make_request("scores", endpoint)

    # ═══════════════════════════════════════════════════════════════════
    # Injury Endpoints
    # ═══════════════════════════════════════════════════════════════════

    def get_injuries_by_team(self, season: int, week: int, team: str) -> List[Dict[str, Any]]:
        """
        Get injury report for a specific team and week.

        Endpoint: /scores/json/Injuries/{season}/{week}/{team}

        Args:
            season: Season year
            week: Week number
            team: Team abbreviation

        Returns:
            List of injury report dictionaries

        Example:
            injuries = client.get_injuries_by_team(2024, 10, "DAL")
            for injury in injuries:
                print(f"{injury['Name']} ({injury['Position']}): {injury['Status']}")
        """
        endpoint = f"Injuries/{season}/{week}/{team}"
        return self._make_request("scores", endpoint)

    # ═══════════════════════════════════════════════════════════════════
    # Utility Methods
    # ═══════════════════════════════════════════════════════════════════

    def get_current_season(self) -> int:
        """
        Get current NFL season year.

        Returns:
            Current season (e.g., 2024)

        Note:
            NFL season starts in September, so:
            - Jan-Aug: Previous calendar year
            - Sep-Dec: Current calendar year
        """
        now = datetime.now(tz=timezone.utc)
        if now.month >= 9:
            return now.year
        else:
            return now.year - 1

    def get_current_week(self) -> Optional[int]:
        """
        Get current NFL week number.

        Returns:
            Current week (1-18) or None if off-season

        Note:
            This requires checking the current season schedule.
            For production use, call get_schedules() and find the current week.
        """
        # Simplified implementation - production should query API
        now = datetime.now(tz=timezone.utc)

        # Off-season check (roughly Feb-Aug)
        if now.month < 9 and now.month > 1:
            return None

        # During season, estimate week (very rough approximation)
        # For accurate week, should query API schedules
        if now.month == 9:
            return min(4, ((now.day - 1) // 7) + 1)
        elif now.month >= 10:
            # This is a rough estimate - production should query API
            return 5 + (now.month - 10) * 4
        return 1

    def close(self):
        """Close the session"""
        self.session.close()

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()


# ═══════════════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════════════

def get_client() -> SportsDataClient:
    """
    Get a configured SportsData.io client instance.

    Returns:
        SportsDataClient instance

    Raises:
        ValueError: If API key not configured
    """
    return SportsDataClient()


# ═══════════════════════════════════════════════════════════════════
# CLI Testing
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    """
    Test the SportsData.io API client.

    Usage:
        python -m utils.sportsdata_api
    """
    import json

    print("=" * 60)
    print("SportsData.io NFL API Client Test")
    print("=" * 60)

    try:
        client = get_client()
        current_season = client.get_current_season()
        print(f"\nCurrent NFL Season: {current_season}")

        # Test: Get standings
        print(f"\nFetching standings for {current_season}...")
        standings = client.get_standings(current_season)
        print(f"✓ Retrieved {len(standings)} teams")

        if standings:
            # Show first team as example
            team = standings[0]
            print(f"\nExample team (first in response):")
            print(f"  Team: {team.get('Team', 'N/A')}")
            print(f"  Wins: {team.get('Wins', 'N/A')}")
            print(f"  Losses: {team.get('Losses', 'N/A')}")
            print(f"  Win %: {team.get('Percentage', 'N/A')}")

        # Test: Get team season stats
        print(f"\nFetching team season stats for {current_season}...")
        stats = client.get_team_season_stats(current_season)
        print(f"✓ Retrieved {len(stats)} teams")

        if stats:
            # Show first team stats as example
            team_stats = stats[0]
            print(f"\nExample team stats (first in response):")
            print(f"  Team: {team_stats.get('Team', 'N/A')}")
            print(f"  Points Scored: {team_stats.get('Score', 'N/A')}")
            print(f"  Points Allowed: {team_stats.get('OpponentScore', 'N/A')}")
            print(f"  Total Yards: {team_stats.get('TotalYards', 'N/A')}")

        print("\n" + "=" * 60)
        print("✓ All tests passed!")
        print("=" * 60)

    except ValueError as e:
        print(f"\n✗ Configuration error: {e}")
        print("\nPlease set SPORTSDATA_API_KEY in your .env file:")
        print("  SPORTSDATA_API_KEY=your-api-key-here")
    except SportsDataRateLimitError as e:
        print(f"\n✗ Rate limit error: {e}")
    except SportsDataAPIError as e:
        print(f"\n✗ API error: {e}")
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
