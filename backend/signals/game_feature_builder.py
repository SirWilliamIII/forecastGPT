# backend/signals/game_feature_builder.py
"""
NFL game feature computation pipeline for ML forecasting.

Computes 10-12 features from team statistics and game data:
- Team performance metrics (win%, points, differentials)
- Recent form and trends
- Head-to-head history
- External projections (Baker API)
- League rankings (computed from stats)

All timestamps must be timezone-aware UTC.
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from psycopg import sql

from db import get_conn
from config import (
    NFL_FEATURES_VERSION,
    NFL_LOOKBACK_GAMES,
    NFL_MIN_GAMES_FOR_FEATURES,
    NFL_FORM_WINDOW,
)


def _validate_datetime(dt: datetime, name: str) -> None:
    """Validate datetime is timezone-aware UTC."""
    if dt.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware (use datetime.now(tz=timezone.utc))")


def compute_team_features(
    team_symbol: str,
    season: int,
    week: int,
    lookback_weeks: int = NFL_LOOKBACK_GAMES,
) -> Dict[str, Optional[float]]:
    """
    Compute rolling statistics for a team based on recent performance.

    Queries team_stats table for the team's last N weeks before the given season/week.
    Computes:
    - Win percentage (last N weeks)
    - Points scored/allowed averages
    - Point differential average
    - Recent form (last 3 weeks)
    - Offensive/defensive rank (from team_stats)

    Args:
        team_symbol: Team symbol (e.g., "NFL:DAL_COWBOYS")
        season: Season year
        week: Week number (strictly before this week)
        lookback_weeks: Number of weeks to look back for rolling stats

    Returns:
        Dict with computed features. NULL values if insufficient data.
    """
    # Query team_stats for recent weeks (before this game's week)
    # Use < week to prevent lookahead bias
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    season,
                    week,
                    win_count,
                    loss_count,
                    win_pct,
                    points_scored,
                    points_allowed,
                    point_differential,
                    offensive_rank,
                    defensive_rank
                FROM team_stats
                WHERE team_symbol = %s
                  AND (
                    (season = %s AND week < %s) OR
                    (season < %s)
                  )
                ORDER BY season DESC, week DESC
                LIMIT %s
                """,
                (team_symbol, season, week, season, lookback_weeks),
            )
            rows = cur.fetchall()

    if len(rows) < NFL_MIN_GAMES_FOR_FEATURES:
        # Insufficient data - return NULLs
        return {
            "win_pct": None,
            "points_avg": None,
            "points_allowed_avg": None,
            "point_diff_avg": None,
            "last3_win_pct": None,
            "offensive_rank": None,
            "defensive_rank": None,
        }

    # Extract statistics from most recent weeks
    # team_stats contains cumulative season stats, so we need to compute per-game averages
    # by taking differences between consecutive weeks

    # Sort by season/week ascending for diff calculation
    sorted_rows = sorted(rows, key=lambda r: (r["season"], r["week"]))

    # Compute per-game stats from cumulative data
    game_wins = []
    game_points_scored = []
    game_points_allowed = []

    for i, row in enumerate(sorted_rows):
        if i == 0:
            # First week - use raw values
            wins = row["win_count"]
            losses = row["loss_count"]
            total_games = wins + losses
            if total_games > 0:
                game_wins.append(wins / total_games)  # Win rate so far
            game_points_scored.append(row["points_scored"] / max(total_games, 1))
            game_points_allowed.append(row["points_allowed"] / max(total_games, 1))
        else:
            # Compute delta from previous week
            prev = sorted_rows[i - 1]

            # Games this week
            games_this_week = (row["win_count"] + row["loss_count"]) - (prev["win_count"] + prev["loss_count"])

            if games_this_week > 0:
                # Wins this week
                wins_this_week = row["win_count"] - prev["win_count"]
                game_wins.append(wins_this_week / games_this_week)

                # Points this week
                points_this_week = row["points_scored"] - prev["points_scored"]
                game_points_scored.append(points_this_week / games_this_week)

                # Points allowed this week
                points_allowed_this_week = row["points_allowed"] - prev["points_allowed"]
                game_points_allowed.append(points_allowed_this_week / games_this_week)

    # Compute rolling averages
    if not game_wins:
        # Fallback to simple season average from most recent row
        latest = sorted_rows[-1]
        win_pct = latest["win_pct"] if latest["win_pct"] is not None else 0.5
        total_games = latest["win_count"] + latest["loss_count"]
        points_avg = latest["points_scored"] / max(total_games, 1)
        points_allowed_avg = latest["points_allowed"] / max(total_games, 1)
        point_diff_avg = latest["point_differential"] / max(total_games, 1)
    else:
        win_pct = sum(game_wins) / len(game_wins)
        points_avg = sum(game_points_scored) / len(game_points_scored)
        points_allowed_avg = sum(game_points_allowed) / len(game_points_allowed)
        point_diff_avg = points_avg - points_allowed_avg

    # Recent form (last 3 games)
    form_window = min(NFL_FORM_WINDOW, len(game_wins))
    if form_window > 0:
        last3_win_pct = sum(game_wins[-form_window:]) / form_window
    else:
        last3_win_pct = win_pct  # Fallback to overall win%

    # Ranks from most recent week
    latest = sorted_rows[-1]
    offensive_rank = latest["offensive_rank"]
    defensive_rank = latest["defensive_rank"]

    return {
        "win_pct": win_pct,
        "points_avg": points_avg,
        "points_allowed_avg": points_allowed_avg,
        "point_diff_avg": point_diff_avg,
        "last3_win_pct": last3_win_pct,
        "offensive_rank": offensive_rank,
        "defensive_rank": defensive_rank,
    }


def compute_league_ranks(
    team_symbol: str,
    season: int,
    week: int,
) -> Tuple[Optional[int], Optional[int]]:
    """
    Compute offensive and defensive league ranks dynamically from team_stats.

    Ranks teams by:
    - Offensive rank: Points scored (descending)
    - Defensive rank: Points allowed (ascending)

    Args:
        team_symbol: Team symbol (e.g., "NFL:DAL_COWBOYS")
        season: Season year
        week: Week number (use previous week for rankings)

    Returns:
        Tuple of (offensive_rank, defensive_rank). None if data unavailable.
    """
    # Use the previous week for fair rankings (before this game)
    rank_week = week - 1
    if rank_week < 1:
        # First week of season - no rankings available
        return None, None

    # Get all teams' stats for that week
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    team_symbol,
                    points_scored,
                    points_allowed,
                    win_count + loss_count as games_played
                FROM team_stats
                WHERE season = %s AND week = %s AND (win_count + loss_count) > 0
                ORDER BY points_scored DESC
                """,
                (season, rank_week),
            )
            teams = cur.fetchall()

    if not teams:
        return None, None

    # Compute per-game averages and rank
    team_stats = []
    for team in teams:
        games = team["games_played"]
        ppg = team["points_scored"] / games if games > 0 else 0
        papg = team["points_allowed"] / games if games > 0 else 0
        team_stats.append({
            "symbol": team["team_symbol"],
            "ppg": ppg,
            "papg": papg,
        })

    # Offensive rank (by points per game, descending)
    offensive_sorted = sorted(team_stats, key=lambda x: x["ppg"], reverse=True)
    offensive_rank = None
    for i, team in enumerate(offensive_sorted, start=1):
        if team["symbol"] == team_symbol:
            offensive_rank = i
            break

    # Defensive rank (by points allowed per game, ascending)
    defensive_sorted = sorted(team_stats, key=lambda x: x["papg"])
    defensive_rank = None
    for i, team in enumerate(defensive_sorted, start=1):
        if team["symbol"] == team_symbol:
            defensive_rank = i
            break

    return offensive_rank, defensive_rank


def get_head_to_head_record(
    team_a_symbol: str,
    team_b_symbol: str,
    lookback_years: int = 5,
) -> Tuple[int, int]:
    """
    Get head-to-head record between two teams.

    Queries asset_returns table for historical games between teams.
    Note: Current data may not have opponent info, so this may return (0, 0).

    Args:
        team_a_symbol: Team A symbol (e.g., "NFL:DAL_COWBOYS")
        team_b_symbol: Team B symbol (e.g., "NFL:PHI_EAGLES")
        lookback_years: Years of history to consider

    Returns:
        Tuple of (team_a_wins, team_b_wins)
    """
    # For now, we don't have opponent info in asset_returns
    # This will be enhanced when we integrate game metadata
    # Return (0, 0) as placeholder
    return 0, 0


def get_baker_projection(
    team_symbol: str,
    game_date: datetime,
    tolerance_hours: int = 24,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Get Baker API projection for a game.

    Args:
        team_symbol: Team symbol (e.g., "NFL:DAL_COWBOYS")
        game_date: Game datetime. Must be timezone-aware UTC.
        tolerance_hours: Time tolerance for matching projections

    Returns:
        Tuple of (win_probability, spread). None if not found.
    """
    _validate_datetime(game_date, "game_date")

    tolerance = timedelta(hours=tolerance_hours)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    projected_value as win_prob,
                    meta->>'spread' as spread
                FROM projections
                WHERE symbol = %s
                  AND metric = 'win_prob'
                  AND as_of BETWEEN %s AND %s
                ORDER BY ABS(EXTRACT(EPOCH FROM (as_of - %s))) ASC
                LIMIT 1
                """,
                (team_symbol, game_date - tolerance, game_date + tolerance, game_date),
            )
            row = cur.fetchone()

            if row:
                win_prob = float(row["win_prob"]) if row["win_prob"] is not None else None
                spread = float(row["spread"]) if row["spread"] else None
                return win_prob, spread

    return None, None


def compute_game_features(
    home_team: str,
    away_team: str,
    game_date: datetime,
    game_id: str,
    season: int,
    week: int,
    is_playoff: bool = False,
    home_score: Optional[int] = None,
    away_score: Optional[int] = None,
) -> Dict:
    """
    Compute all ML features for a game.

    Combines:
    - Home team features (from team_stats)
    - Away team features (from team_stats)
    - Head-to-head history
    - Baker projections (if available)
    - League ranks (computed dynamically)

    Args:
        home_team: Home team symbol (e.g., "NFL:DAL_COWBOYS")
        away_team: Away team symbol (e.g., "NFL:PHI_EAGLES")
        game_date: Game datetime. Must be timezone-aware UTC.
        game_id: Unique game identifier
        season: Season year
        week: Week number
        is_playoff: Whether game is playoff
        home_score: Actual home score (if game completed)
        away_score: Actual away score (if game completed)

    Returns:
        Dict with all features ready for insertion into game_features table
    """
    _validate_datetime(game_date, "game_date")

    # Compute team features (using data strictly before this game's week)
    home_features = compute_team_features(home_team, season, week)
    away_features = compute_team_features(away_team, season, week)

    # Compute league ranks dynamically
    home_off_rank, home_def_rank = compute_league_ranks(home_team, season, week)
    away_off_rank, away_def_rank = compute_league_ranks(away_team, season, week)

    # Override ranks if we computed them dynamically (better than team_stats ranks)
    if home_off_rank is not None:
        home_features["offensive_rank"] = home_off_rank
    if home_def_rank is not None:
        home_features["defensive_rank"] = home_def_rank
    if away_off_rank is not None:
        away_features["offensive_rank"] = away_off_rank
    if away_def_rank is not None:
        away_features["defensive_rank"] = away_def_rank

    # Head-to-head record
    h2h_home_wins, h2h_away_wins = get_head_to_head_record(home_team, away_team)

    # Baker projection (for home team)
    baker_win_prob, baker_spread = get_baker_projection(home_team, game_date)

    # Compute outcome labels (if game completed)
    home_win = None
    point_differential = None
    if home_score is not None and away_score is not None:
        home_win = home_score > away_score
        point_differential = home_score - away_score

    # Build feature dict
    features = {
        "game_id": game_id,
        "home_team": home_team,
        "away_team": away_team,
        "game_date": game_date,
        "season": season,
        "week": week,
        "is_playoff": is_playoff,
        # Home team features
        "home_win_pct": home_features["win_pct"],
        "home_points_avg": home_features["points_avg"],
        "home_points_allowed_avg": home_features["points_allowed_avg"],
        "home_point_diff_avg": home_features["point_diff_avg"],
        "home_last3_win_pct": home_features["last3_win_pct"],
        "home_offensive_rank": home_features["offensive_rank"],
        "home_defensive_rank": home_features["defensive_rank"],
        # Away team features
        "away_win_pct": away_features["win_pct"],
        "away_points_avg": away_features["points_avg"],
        "away_points_allowed_avg": away_features["points_allowed_avg"],
        "away_point_diff_avg": away_features["point_diff_avg"],
        "away_last3_win_pct": away_features["last3_win_pct"],
        "away_offensive_rank": away_features["offensive_rank"],
        "away_defensive_rank": away_features["defensive_rank"],
        # Matchup features
        "head_to_head_home_wins": h2h_home_wins,
        "head_to_head_away_wins": h2h_away_wins,
        # External signals
        "baker_home_win_prob": baker_win_prob,
        "baker_spread": baker_spread,
        # Rest days (not computed yet)
        "rest_days_home": None,
        "rest_days_away": None,
        # Outcome labels
        "home_score": home_score,
        "away_score": away_score,
        "home_win": home_win,
        "point_differential": point_differential,
        # Metadata
        "features_version": NFL_FEATURES_VERSION,
        "computed_at": datetime.now(tz=timezone.utc),
    }

    return features


def insert_game_features_batch(features_list: List[Dict]) -> Tuple[int, int]:
    """
    Batch insert game features into database.

    Uses ON CONFLICT to handle duplicates (idempotent).

    Args:
        features_list: List of feature dicts from compute_game_features()

    Returns:
        Tuple of (inserted_count, updated_count)
    """
    if not features_list:
        return 0, 0

    # Define all columns (order matters for INSERT)
    columns = [
        "game_id", "home_team", "away_team", "game_date", "season", "week", "is_playoff",
        "home_win_pct", "home_points_avg", "home_points_allowed_avg", "home_point_diff_avg",
        "home_last3_win_pct", "home_offensive_rank", "home_defensive_rank",
        "away_win_pct", "away_points_avg", "away_points_allowed_avg", "away_point_diff_avg",
        "away_last3_win_pct", "away_offensive_rank", "away_defensive_rank",
        "head_to_head_home_wins", "head_to_head_away_wins",
        "rest_days_home", "rest_days_away",
        "baker_home_win_prob", "baker_spread",
        "home_score", "away_score", "home_win", "point_differential",
        "features_version", "computed_at",
    ]

    # Build INSERT query with ON CONFLICT
    # Note: For executemany, we need %s placeholders, not sql.Placeholder()
    placeholders = ", ".join(["%s"] * len(columns))
    column_names = ", ".join(columns)

    insert_query = f"""
        INSERT INTO game_features ({column_names})
        VALUES ({placeholders})
        ON CONFLICT (game_id) DO UPDATE SET
            home_win_pct = EXCLUDED.home_win_pct,
            home_points_avg = EXCLUDED.home_points_avg,
            home_points_allowed_avg = EXCLUDED.home_points_allowed_avg,
            home_point_diff_avg = EXCLUDED.home_point_diff_avg,
            home_last3_win_pct = EXCLUDED.home_last3_win_pct,
            home_offensive_rank = EXCLUDED.home_offensive_rank,
            home_defensive_rank = EXCLUDED.home_defensive_rank,
            away_win_pct = EXCLUDED.away_win_pct,
            away_points_avg = EXCLUDED.away_points_avg,
            away_points_allowed_avg = EXCLUDED.away_points_allowed_avg,
            away_point_diff_avg = EXCLUDED.away_point_diff_avg,
            away_last3_win_pct = EXCLUDED.away_last3_win_pct,
            away_offensive_rank = EXCLUDED.away_offensive_rank,
            away_defensive_rank = EXCLUDED.away_defensive_rank,
            head_to_head_home_wins = EXCLUDED.head_to_head_home_wins,
            head_to_head_away_wins = EXCLUDED.head_to_head_away_wins,
            rest_days_home = EXCLUDED.rest_days_home,
            rest_days_away = EXCLUDED.rest_days_away,
            baker_home_win_prob = EXCLUDED.baker_home_win_prob,
            baker_spread = EXCLUDED.baker_spread,
            home_score = EXCLUDED.home_score,
            away_score = EXCLUDED.away_score,
            home_win = EXCLUDED.home_win,
            point_differential = EXCLUDED.point_differential,
            features_version = EXCLUDED.features_version,
            computed_at = EXCLUDED.computed_at,
            updated_at = now()
    """

    # Prepare data tuples
    data_tuples = []
    for features in features_list:
        row = tuple(features.get(col) for col in columns)
        data_tuples.append(row)

    # Execute batch insert
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(insert_query, data_tuples)
            inserted_count = cur.rowcount
            conn.commit()

    # For now, assume all are inserts (can track updates with RETURNING clause if needed)
    return inserted_count, 0


def backfill_game_features(
    team_symbols: List[str],
    start_season: int = 2023,
    end_season: int = 2025,
) -> Tuple[int, int, int]:
    """
    Backfill game_features table with historical data.

    For each team:
    1. Get all games from asset_returns
    2. Fetch game details from ESPN API (home/away, opponent)
    3. Compute features for each game
    4. Insert into game_features table

    Args:
        team_symbols: List of team symbols to backfill
        start_season: Starting season year
        end_season: Ending season year (inclusive)

    Returns:
        Tuple of (inserted_count, updated_count, skipped_count)
    """
    from utils.espn_api import get_team_schedule, parse_game_outcome

    total_inserted = 0
    total_updated = 0
    total_skipped = 0

    for team_symbol in team_symbols:
        print(f"\n[backfill_game_features] Processing {team_symbol}...")

        # Extract team abbreviation (e.g., NFL:DAL_COWBOYS -> DAL)
        team_abbr = team_symbol.split(":")[1].split("_")[0] if ":" in team_symbol else None
        if not team_abbr:
            print(f"  ✗ Invalid team symbol format: {team_symbol}")
            continue

        # Get games from asset_returns (ground truth)
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        as_of as game_date,
                        price_start,
                        price_end,
                        realized_return
                    FROM asset_returns
                    WHERE symbol = %s
                    ORDER BY as_of ASC
                    """,
                    (team_symbol,),
                )
                games_from_db = cur.fetchall()

        print(f"  Found {len(games_from_db)} games in asset_returns")

        # Fetch ESPN data for each season to get home/away and opponent info
        espn_games_map = {}  # game_date -> game_info
        for season in range(start_season, end_season + 1):
            try:
                schedule_data = get_team_schedule(team_abbr, season)

                # Parse games from ESPN response
                events = schedule_data.get("events", [])
                for event in events:
                    game_info = parse_game_outcome(event, team_abbr)
                    if game_info:
                        game_date, opp_abbr, opp_name, pts_for, pts_against, is_win, is_home = game_info
                        espn_games_map[game_date] = {
                            "opponent_abbr": opp_abbr,
                            "opponent_name": opp_name,
                            "points_for": pts_for,
                            "points_against": pts_against,
                            "is_home": is_home,
                            "is_win": is_win,
                        }

                print(f"  Fetched {len(events)} games from ESPN for {season} season")
            except Exception as e:
                print(f"  Warning: Could not fetch ESPN data for {season}: {e}")

        # Match games from DB with ESPN data
        features_to_insert = []
        for game in games_from_db:
            game_date = game["game_date"]

            # Try to find matching ESPN game (with tolerance for time differences)
            espn_match = None
            for espn_date, espn_info in espn_games_map.items():
                # Allow 12-hour tolerance for game time matching
                if abs((espn_date - game_date).total_seconds()) < 12 * 3600:
                    espn_match = espn_info
                    break

            if not espn_match:
                print(f"  ✗ No ESPN match for game on {game_date.date()}, skipping...")
                total_skipped += 1
                continue

            # Determine home/away teams
            is_home = espn_match["is_home"]
            opp_abbr = espn_match["opponent_abbr"]

            # Build opponent symbol (assume same format: NFL:OPP_TEAM)
            opponent_symbol = f"NFL:{opp_abbr}_{espn_match['opponent_name'].upper().replace(' ', '_')}"

            if is_home:
                home_team = team_symbol
                away_team = opponent_symbol
                home_score = espn_match["points_for"]
                away_score = espn_match["points_against"]
            else:
                home_team = opponent_symbol
                away_team = team_symbol
                home_score = espn_match["points_against"]
                away_score = espn_match["points_for"]

            # Generate game_id
            date_str = game_date.strftime("%Y%m%d")
            game_id = f"{date_str}_{home_team.split(':')[1]}_{away_team.split(':')[1]}"

            # Determine season/week (approximate from game_date)
            year = game_date.year
            month = game_date.month

            # NFL season: Sep-Feb (season year is when it started)
            if month >= 9:
                season = year
            else:
                season = year - 1

            # Rough week estimation (week 1 starts ~Sep 7)
            # This is approximate - could enhance with ESPN data
            if month >= 9:
                week = ((game_date.day - 7) // 7) + 1
            else:
                week = 17 + (month * 4)  # Rough estimate for playoffs

            week = max(1, min(week, 22))  # Clamp to valid range

            # Compute features
            try:
                features = compute_game_features(
                    home_team=home_team,
                    away_team=away_team,
                    game_date=game_date,
                    game_id=game_id,
                    season=season,
                    week=week,
                    is_playoff=week > 18,
                    home_score=home_score,
                    away_score=away_score,
                )
                features_to_insert.append(features)
            except Exception as e:
                print(f"  ✗ Error computing features for {game_id}: {e}")
                total_skipped += 1
                continue

        # Batch insert
        if features_to_insert:
            print(f"  Inserting {len(features_to_insert)} games...")
            inserted, updated = insert_game_features_batch(features_to_insert)
            total_inserted += inserted
            total_updated += updated
            print(f"  ✓ Inserted: {inserted}, Updated: {updated}")

    return total_inserted, total_updated, total_skipped


if __name__ == "__main__":
    # Test with a single team
    print("Testing game feature builder...")

    team_symbol = "NFL:DAL_COWBOYS"
    test_season = 2024
    test_week = 10  # Mid-season week for testing

    print(f"\n1. Computing team features for {team_symbol} (season {test_season}, week {test_week})...")
    features = compute_team_features(team_symbol, test_season, test_week)
    print(f"   Win%: {features['win_pct']:.3f}" if features['win_pct'] else "   Win%: None")
    print(f"   Pts/game: {features['points_avg']:.1f}" if features['points_avg'] else "   Pts/game: None")
    print(f"   Recent form: {features['last3_win_pct']:.3f}" if features['last3_win_pct'] else "   Recent form: None")

    print(f"\n2. Computing league ranks...")
    off_rank, def_rank = compute_league_ranks(team_symbol, test_season, test_week)
    print(f"   Offensive rank: {off_rank}")
    print(f"   Defensive rank: {def_rank}")

    print(f"\n3. Testing backfill (dry run)...")
    print("   Run backfill_game_features.py to perform actual backfill")
