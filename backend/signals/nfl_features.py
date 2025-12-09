# backend/signals/nfl_features.py
"""
NFL-specific feature extraction and event-to-game temporal mapping.

This module connects sports events to upcoming/past games for event-based forecasting.
"""

import re
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from typing import List, Optional, Dict
from uuid import UUID

from db import get_conn
from config import NFL_MAX_DAYS_AHEAD, NFL_MAX_DAYS_BEFORE_GAME, NFL_MIN_DAYS_BEFORE_GAME


@dataclass
class GameInfo:
    """Information about an NFL game"""
    game_date: datetime
    symbol: str  # NFL:DAL_COWBOYS
    opponent_abbr: str  # PHI, WAS, etc.
    opponent_name: Optional[str]  # Philadelphia Eagles
    horizon_minutes: int  # Time from event to game
    is_home: Optional[bool]  # Home/away if known
    point_differential: Optional[float]  # Actual outcome if game completed


# Team name variations for matching (raw patterns)
_TEAM_MENTION_PATTERNS_RAW = {
    "NFL:DAL_COWBOYS": [
        r"\bCowboys?\b",
        r"\bDallas\b",
        r"\bDAL\b",
        r"\bDak\s+Prescott\b",  # QB
        r"\bCeeDee\s+Lamb\b",   # Star WR
        r"\bMicah\s+Parsons\b", # Star DE
    ],
    "NFL:KC_CHIEFS": [
        r"\bChiefs?\b",
        r"\bKansas\s+City\b",
        r"\bKC\b",
        r"\bPatrick\s+Mahomes\b",  # QB
        r"\bTravis\s+Kelce\b",     # Star TE
    ],
    "NFL:SF_49ERS": [
        r"\b49ers?\b",
        r"\bSan\s+Francisco\b",
        r"\bNiners?\b",
        r"\bSF\b",
        r"\bBrock\s+Purdy\b",     # QB
    ],
    "NFL:PHI_EAGLES": [
        r"\bEagles?\b",
        r"\bPhiladelphia\b",
        r"\bPHI\b",
        r"\bJalen\s+Hurts\b",     # QB
    ],
    "NFL:BUF_BILLS": [
        r"\bBills?\b",
        r"\bBuffalo\b",
        r"\bBUF\b",
        r"\bJosh\s+Allen\b",      # QB
        r"\bStefon\s+Diggs\b",    # Star WR (note: may have moved, but historically relevant)
    ],
    "NFL:DET_LIONS": [
        r"\bLions?\b",
        r"\bDetroit\b",
        r"\bDET\b",
        r"\bJared\s+Goff\b",      # QB
        r"\bAmon-Ra\s+St\.\s+Brown\b",  # Star WR
    ],
}

# Pre-compiled regex patterns for performance
TEAM_MENTION_PATTERNS = {
    team: [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    for team, patterns in _TEAM_MENTION_PATTERNS_RAW.items()
}


def get_team_regex_pattern(team_symbol: str) -> Optional[str]:
    r"""
    Get combined PostgreSQL regex pattern for a team.
    Returns pattern like: '(Cowboys?|Dallas|DAL|Dak\s+Prescott|...)'

    This is used for database-side filtering with PostgreSQL ~* operator.

    Args:
        team_symbol: Team symbol (e.g., "NFL:DAL_COWBOYS")

    Returns:
        Combined regex pattern, or None if team not found
    """
    raw_patterns = _TEAM_MENTION_PATTERNS_RAW.get(team_symbol, [])
    if not raw_patterns:
        return None

    # Combine patterns with OR (remove \b word boundaries, PostgreSQL uses different syntax)
    # PostgreSQL ~* is case-insensitive by default
    cleaned_patterns = []
    for pattern in raw_patterns:
        # Remove \b word boundaries (PostgreSQL uses [[:<:]] and [[:>:]] but not needed for ~*)
        cleaned = pattern.replace(r'\b', '')
        cleaned_patterns.append(cleaned)

    return '(' + '|'.join(cleaned_patterns) + ')'


def find_next_game(
    team_symbol: str,
    reference_time: datetime,
    max_days_ahead: int = NFL_MAX_DAYS_AHEAD,
) -> Optional[GameInfo]:
    """
    Find the next scheduled game for a team after a reference time.

    Checks both completed games in database AND upcoming scheduled games from ESPN API.

    Args:
        team_symbol: Team symbol (e.g., "NFL:DAL_COWBOYS")
        reference_time: Reference timestamp (must be timezone-aware UTC)
        max_days_ahead: Maximum days to look ahead for next game

    Returns:
        GameInfo if a game is found, None otherwise
    """
    if reference_time.tzinfo is None:
        raise ValueError("reference_time must be timezone-aware (use datetime.now(tz=timezone.utc))")

    max_date = reference_time + timedelta(days=max_days_ahead)

    # First, check database for completed games
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    as_of,
                    price_end - price_start as point_diff,
                    realized_return
                FROM asset_returns
                WHERE symbol = %s
                  AND as_of > %s
                  AND as_of <= %s
                ORDER BY as_of ASC
                LIMIT 1
                """,
                (team_symbol, reference_time, max_date),
            )
            row = cur.fetchone()

            if row:
                game_date = row["as_of"]
                point_diff = float(row["point_diff"])

                # Calculate horizon in minutes
                horizon_minutes = int((game_date - reference_time).total_seconds() / 60)

                return GameInfo(
                    game_date=game_date,
                    symbol=team_symbol,
                    opponent_abbr="UNK",  # Don't have opponent info in asset_returns
                    opponent_name=None,
                    horizon_minutes=horizon_minutes,
                    is_home=None,
                    point_differential=point_diff,
                )

    # If no completed game found, check ESPN for upcoming scheduled games
    try:
        from utils.espn_api import fetch_upcoming_games

        # Extract team abbreviation from symbol (NFL:DAL_COWBOYS -> DAL)
        team_abbr = team_symbol.split(":")[1].split("_")[0] if ":" in team_symbol else None

        if team_abbr:
            upcoming_games = fetch_upcoming_games(team_abbr, max_days_ahead=max_days_ahead)

            if upcoming_games:
                # Get the first upcoming game
                game_date, opp_abbr, opp_name = upcoming_games[0]

                # Calculate horizon in minutes
                horizon_minutes = int((game_date - reference_time).total_seconds() / 60)

                return GameInfo(
                    game_date=game_date,
                    symbol=team_symbol,
                    opponent_abbr=opp_abbr,
                    opponent_name=opp_name,
                    horizon_minutes=horizon_minutes,
                    is_home=None,  # ESPN API doesn't always provide home/away
                    point_differential=None,  # Game hasn't been played yet
                )
    except Exception as e:
        print(f"[nfl_features] Error fetching upcoming games from ESPN: {e}")

    return None


def find_previous_game(
    team_symbol: str,
    reference_time: datetime,
    max_days_back: int = 30,
) -> Optional[GameInfo]:
    """
    Find the most recent game before a reference time.

    Args:
        team_symbol: Team symbol (e.g., "NFL:DAL_COWBOYS")
        reference_time: Reference timestamp (must be timezone-aware UTC)
        max_days_back: Maximum days to look back

    Returns:
        GameInfo if a game is found, None otherwise
    """
    if reference_time.tzinfo is None:
        raise ValueError("reference_time must be timezone-aware (use datetime.now(tz=timezone.utc))")

    min_date = reference_time - timedelta(days=max_days_back)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    as_of,
                    price_end - price_start as point_diff,
                    realized_return
                FROM asset_returns
                WHERE symbol = %s
                  AND as_of < %s
                  AND as_of >= %s
                ORDER BY as_of DESC
                LIMIT 1
                """,
                (team_symbol, reference_time, min_date),
            )
            row = cur.fetchone()

            if not row:
                return None

            game_date = row["as_of"]
            point_diff = float(row["point_diff"])

            # Horizon is negative (game was in the past)
            horizon_minutes = int((game_date - reference_time).total_seconds() / 60)

            return GameInfo(
                game_date=game_date,
                symbol=team_symbol,
                opponent_abbr="UNK",
                opponent_name=None,
                horizon_minutes=horizon_minutes,
                is_home=None,
                point_differential=point_diff,
            )


def is_team_mentioned(
    event_text: str,
    team_symbol: str,
    case_sensitive: bool = False,
) -> bool:
    """
    Check if event text mentions a specific team.

    Args:
        event_text: Event title/summary text
        team_symbol: Team symbol (e.g., "NFL:DAL_COWBOYS")
        case_sensitive: Whether to use case-sensitive matching (ignored - patterns are pre-compiled with IGNORECASE)

    Returns:
        True if team is mentioned, False otherwise
    """
    patterns = TEAM_MENTION_PATTERNS.get(team_symbol, [])
    if not patterns:
        return False

    # Patterns are pre-compiled with IGNORECASE flag
    # case_sensitive parameter is now ignored for performance
    for pattern in patterns:
        if pattern.search(event_text):
            return True

    return False


def get_events_for_next_game(
    team_symbol: str,
    max_days_before: int = NFL_MAX_DAYS_BEFORE_GAME,
    min_days_before: int = NFL_MIN_DAYS_BEFORE_GAME,
    reference_time: Optional[datetime] = None,
) -> List[Dict]:
    """
    Get sports events that occurred before the team's next game.

    Args:
        team_symbol: Team symbol (e.g., "NFL:DAL_COWBOYS")
        max_days_before: Maximum days before game to consider events
        min_days_before: Minimum days before game (to filter out same-day events)
        reference_time: Reference time (defaults to now)

    Returns:
        List of event dicts with id, timestamp, title, summary, distance_to_game_minutes
    """
    if reference_time is None:
        reference_time = datetime.now(tz=timezone.utc)
    elif reference_time.tzinfo is None:
        raise ValueError("reference_time must be timezone-aware")

    # Find next game
    next_game = find_next_game(team_symbol, reference_time)
    if not next_game:
        return []

    # Calculate time window for events
    event_window_start = next_game.game_date - timedelta(days=max_days_before)
    event_window_end = next_game.game_date - timedelta(days=min_days_before)

    # Get PostgreSQL regex pattern for team (database-side filtering)
    team_pattern = get_team_regex_pattern(team_symbol)

    with get_conn() as conn:
        with conn.cursor() as cur:
            if team_pattern:
                # OPTIMIZED: Use PostgreSQL regex filtering to reduce data transfer
                cur.execute(
                    """
                    SELECT
                        id,
                        timestamp,
                        title,
                        summary,
                        clean_text,
                        categories
                    FROM events
                    WHERE timestamp BETWEEN %s AND %s
                      AND 'sports' = ANY(categories)
                      AND (title ~* %s OR summary ~* %s OR clean_text ~* %s)
                    ORDER BY timestamp DESC
                    """,
                    (event_window_start, event_window_end, team_pattern, team_pattern, team_pattern),
                )
            else:
                # Fallback: Load all sports events and filter in Python
                cur.execute(
                    """
                    SELECT
                        id,
                        timestamp,
                        title,
                        summary,
                        clean_text,
                        categories
                    FROM events
                    WHERE timestamp BETWEEN %s AND %s
                      AND 'sports' = ANY(categories)
                    ORDER BY timestamp DESC
                    """,
                    (event_window_start, event_window_end),
                )
            rows = cur.fetchall()

    # Build result list (with optional Python-side filtering as double-check)
    team_events = []
    for row in rows:
        # If we used regex in DB, trust it; otherwise filter in Python
        if not team_pattern:
            text_to_check = f"{row['title']} {row['summary'] or ''} {row['clean_text'] or ''}"
            if not is_team_mentioned(text_to_check, team_symbol):
                continue

        # Calculate time distance to game
        distance_minutes = int((next_game.game_date - row['timestamp']).total_seconds() / 60)

        team_events.append({
            'id': row['id'],
            'timestamp': row['timestamp'],
            'title': row['title'],
            'summary': row['summary'],
            'clean_text': row['clean_text'],
            'categories': row['categories'],
            'distance_to_game_minutes': distance_minutes,
            'game_date': next_game.game_date,
        })

    return team_events


def get_historical_events_for_games(
    team_symbol: str,
    lookback_days: int = 365,
    max_days_before_game: int = 7,
) -> List[Dict]:
    """
    Get historical events that occurred before past games.
    Useful for building training data or validating predictions.

    Args:
        team_symbol: Team symbol
        lookback_days: How far back to look for games
        max_days_before_game: Max days before each game to find events

    Returns:
        List of dicts with game info and associated events
    """
    now = datetime.now(tz=timezone.utc)
    start_date = now - timedelta(days=lookback_days)

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Get all past games in lookback window
            cur.execute(
                """
                SELECT
                    as_of,
                    price_end - price_start as point_diff,
                    realized_return
                FROM asset_returns
                WHERE symbol = %s
                  AND as_of BETWEEN %s AND %s
                ORDER BY as_of DESC
                """,
                (team_symbol, start_date, now),
            )
            games = cur.fetchall()

    # Get PostgreSQL regex pattern for team (database-side filtering)
    team_pattern = get_team_regex_pattern(team_symbol)

    game_events = []
    for game in games:
        game_date = game['as_of']
        point_diff = float(game['point_diff'])

        # Find events before this game
        event_window_start = game_date - timedelta(days=max_days_before_game)

        with get_conn() as conn:
            with conn.cursor() as cur:
                if team_pattern:
                    # OPTIMIZED: Use PostgreSQL regex filtering
                    cur.execute(
                        """
                        SELECT
                            id,
                            timestamp,
                            title,
                            summary,
                            clean_text
                        FROM events
                        WHERE timestamp BETWEEN %s AND %s
                          AND 'sports' = ANY(categories)
                          AND (title ~* %s OR summary ~* %s OR clean_text ~* %s)
                        """,
                        (event_window_start, game_date, team_pattern, team_pattern, team_pattern),
                    )
                else:
                    # Fallback: Load all and filter in Python
                    cur.execute(
                        """
                        SELECT
                            id,
                            timestamp,
                            title,
                            summary,
                            clean_text
                        FROM events
                        WHERE timestamp BETWEEN %s AND %s
                          AND 'sports' = ANY(categories)
                        """,
                        (event_window_start, game_date),
                    )
                events = cur.fetchall()

        # Build relevant events list
        relevant_events = []
        for event in events:
            # If we used regex in DB, trust it; otherwise filter in Python
            if not team_pattern:
                text_to_check = f"{event['title']} {event['summary'] or ''} {event['clean_text'] or ''}"
                if not is_team_mentioned(text_to_check, team_symbol):
                    continue

            relevant_events.append({
                'id': event['id'],
                'title': event['title'],
                'timestamp': event['timestamp'],
            })

        if relevant_events:  # Only include games with relevant events
            game_events.append({
                'game_date': game_date,
                'point_differential': point_diff,
                'outcome': 'win' if point_diff > 0 else 'loss',
                'events_count': len(relevant_events),
                'events': relevant_events,
            })

    return game_events


if __name__ == "__main__":
    # Test the module
    print("Testing NFL event-to-game mapping...")

    team_symbol = "NFL:DAL_COWBOYS"
    now = datetime.now(tz=timezone.utc)

    print(f"\nLooking for next Cowboys game after {now.date()}...")
    next_game = find_next_game(team_symbol, now)

    if next_game:
        print(f"✓ Next game: {next_game.game_date.date()}")
        print(f"  Horizon: {next_game.horizon_minutes / 60:.1f} hours")
        print(f"  Days away: {next_game.horizon_minutes / 1440:.1f}")
    else:
        print("✗ No upcoming games found")

    print(f"\nLooking for recent events related to next game...")
    events = get_events_for_next_game(team_symbol, max_days_before=7)

    print(f"Found {len(events)} Cowboys-related sports events:")
    for event in events[:5]:
        days_before = event['distance_to_game_minutes'] / 1440
        print(f"  - {event['timestamp'].date()} ({days_before:.1f}d before): {event['title'][:60]}...")

    print(f"\nLooking for historical game-event associations...")
    historical = get_historical_events_for_games(team_symbol, lookback_days=90, max_days_before_game=7)

    print(f"Found {len(historical)} games with related events:")
    for game_data in historical[:3]:
        print(f"  - {game_data['game_date'].date()} ({game_data['outcome']}): {game_data['events_count']} events")
        for event in game_data['events'][:2]:
            print(f"      • {event['title'][:50]}...")
