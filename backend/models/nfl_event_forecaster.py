# backend/models/nfl_event_forecaster.py
"""
NFL event-based forecaster.

Predicts game outcomes based on semantic similarity of news events.
Wraps the existing crypto event forecaster with NFL-specific logic.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from models.event_return_forecaster import forecast_event_return
from signals.nfl_features import find_next_game, find_previous_game


@dataclass
class NFLEventForecastResult:
    """Result from NFL event forecasting"""
    event_id: UUID
    team_symbol: str

    # Game info
    next_game_date: Optional[datetime]
    opponent: Optional[str]
    days_until_game: Optional[float]

    # Predictions
    win_probability: Optional[float]  # 0.0 to 1.0
    expected_point_diff: Optional[float]  # Expected point differential
    confidence: float  # 0.0 to 1.0

    # Supporting data
    similar_events_found: int
    sample_size: int

    # Diagnostics
    forecast_available: bool
    no_game_reason: Optional[str] = None  # Why no game was found


def convert_return_to_win_prob(expected_return: float, method: str = "linear") -> float:
    """
    Convert [-1, 1] return scale to [0, 1] win probability.

    Args:
        expected_return: Expected return from event forecaster (-1 to 1)
        method: Conversion method ('linear' or 'sigmoid')

    Returns:
        Win probability (0.0 to 1.0)

    Examples:
        expected_return = 1.0  → win_prob ≈ 0.9
        expected_return = 0.0  → win_prob = 0.5
        expected_return = -1.0 → win_prob ≈ 0.1
    """
    if method == "sigmoid":
        # Sigmoid transformation: emphasizes extreme values
        # Scale factor 3.0 makes sigmoid steep enough
        return 1.0 / (1.0 + math.exp(-3.0 * expected_return))
    else:
        # Linear transformation: simpler, more interpretable
        # Maps [-1, 1] → [0.1, 0.9] (avoid extreme 0/1 probabilities)
        return 0.5 + 0.4 * expected_return


def forecast_nfl_event(
    event_id: UUID,
    team_symbol: str,
    event_timestamp: Optional[datetime] = None,
    k_neighbors: int = 25,
    lookback_days: int = 365,
    price_window_minutes: int = 60,
    alpha: float = 0.5,
) -> NFLEventForecastResult:
    """
    Forecast how an event will affect a team's next game outcome.

    This is the main entry point for NFL event-based forecasting.

    Args:
        event_id: Event UUID to forecast from
        team_symbol: Team symbol (e.g., "NFL:DAL_COWBOYS")
        event_timestamp: Event timestamp (fetched from DB if None)
        k_neighbors: Number of nearest neighbor events to use
        lookback_days: How far back to look for similar events
        price_window_minutes: Time window after event to find realized outcomes
        alpha: Distance weighting parameter (higher = more local)

    Returns:
        NFLEventForecastResult with win probability and game info
    """
    # Get event timestamp if not provided
    if event_timestamp is None:
        from db import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT timestamp FROM events WHERE id = %s",
                    (event_id,),
                )
                row = cur.fetchone()
                if not row:
                    return NFLEventForecastResult(
                        event_id=event_id,
                        team_symbol=team_symbol,
                        next_game_date=None,
                        opponent=None,
                        days_until_game=None,
                        win_probability=None,
                        expected_point_diff=None,
                        confidence=0.0,
                        similar_events_found=0,
                        sample_size=0,
                        forecast_available=False,
                        no_game_reason="Event not found in database",
                    )
                event_timestamp = row["timestamp"]

    if event_timestamp.tzinfo is None:
        event_timestamp = event_timestamp.replace(tzinfo=timezone.utc)

    # Find next game after this event
    next_game = find_next_game(team_symbol, event_timestamp, max_days_ahead=30)

    if not next_game:
        return NFLEventForecastResult(
            event_id=event_id,
            team_symbol=team_symbol,
            next_game_date=None,
            opponent=None,
            days_until_game=None,
            win_probability=None,
            expected_point_diff=None,
            confidence=0.0,
            similar_events_found=0,
            sample_size=0,
            forecast_available=False,
            no_game_reason="No upcoming game found within 30 days",
        )

    # Use existing event forecaster
    # This finds similar historical events and their game outcomes
    result = forecast_event_return(
        event_id=event_id,
        symbol=team_symbol,
        horizon_minutes=next_game.horizon_minutes,
        k_neighbors=k_neighbors,
        lookback_days=lookback_days,
        price_window_minutes=price_window_minutes,
        alpha=alpha,
    )

    # Convert to NFL-specific format
    # expected_return is ~1.0 for wins, ~-1.0 for losses
    win_prob = convert_return_to_win_prob(result.expected_return, method="linear")

    # p_up is the weighted probability of positive returns (wins)
    # Use this as an alternative win probability estimate
    win_prob_alternative = result.p_up

    # Average the two estimates for more robust prediction
    win_prob_final = (win_prob + win_prob_alternative) / 2.0

    # Calculate confidence based on sample size and std
    # Low sample size = low confidence
    # High variance = low confidence
    confidence = min(1.0, result.sample_size / 20.0)  # Scale by expected sample size
    if result.sample_size > 0 and result.std_return > 0:
        # Penalize high variance (uncertain outcomes)
        signal_to_noise = abs(result.expected_return) / (result.std_return + 0.01)
        confidence *= min(1.0, signal_to_noise / 2.0)

    # Expected point differential (rough estimate)
    # This is speculative - the system tracks win/loss, not exact scores
    # But we can estimate based on historical point differentials
    expected_point_diff = result.expected_return * 10.0  # Rough scaling

    return NFLEventForecastResult(
        event_id=event_id,
        team_symbol=team_symbol,
        next_game_date=next_game.game_date,
        opponent=next_game.opponent_abbr,
        days_until_game=next_game.horizon_minutes / 1440.0,
        win_probability=win_prob_final,
        expected_point_diff=expected_point_diff,
        confidence=confidence,
        similar_events_found=result.neighbors_used,
        sample_size=result.sample_size,
        forecast_available=result.sample_size > 0,
        no_game_reason=None if result.sample_size > 0 else "No similar historical events found",
    )


def forecast_team_next_game(
    team_symbol: str,
    reference_time: Optional[datetime] = None,
    include_recent_events: bool = True,
    max_event_age_days: int = 7,
) -> dict:
    """
    Forecast a team's next game, optionally incorporating recent events.

    Args:
        team_symbol: Team symbol (e.g., "NFL:DAL_COWBOYS")
        reference_time: Reference time (defaults to now)
        include_recent_events: Whether to include event-based forecasts
        max_event_age_days: How far back to look for recent events

    Returns:
        Dict with game info and event forecasts
    """
    if reference_time is None:
        reference_time = datetime.now(tz=timezone.utc)
    elif reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)

    # Find next game
    next_game = find_next_game(team_symbol, reference_time)

    if not next_game:
        return {
            "team_symbol": team_symbol,
            "next_game_found": False,
            "message": "No upcoming games found",
        }

    result = {
        "team_symbol": team_symbol,
        "next_game_found": True,
        "game_date": next_game.game_date,
        "days_until_game": next_game.horizon_minutes / 1440.0,
        "opponent": next_game.opponent_abbr,
    }

    if include_recent_events:
        from signals.nfl_features import get_events_for_next_game

        # Get recent team-relevant events
        events = get_events_for_next_game(
            team_symbol,
            max_days_before=max_event_age_days,
            reference_time=reference_time,
        )

        # Forecast from each event
        event_forecasts = []
        for event in events:
            forecast = forecast_nfl_event(
                event_id=event['id'],
                team_symbol=team_symbol,
                event_timestamp=event['timestamp'],
            )

            if forecast.forecast_available:
                event_forecasts.append({
                    "event_id": str(event['id']),
                    "event_title": event['title'],
                    "event_date": event['timestamp'],
                    "win_probability": forecast.win_probability,
                    "confidence": forecast.confidence,
                    "similar_events": forecast.similar_events_found,
                })

        result["event_forecasts"] = event_forecasts
        result["event_forecasts_count"] = len(event_forecasts)

        # Aggregate win probability if we have event forecasts
        if event_forecasts:
            # Weighted average by confidence
            total_weight = sum(f["confidence"] for f in event_forecasts)
            if total_weight > 0:
                weighted_win_prob = sum(
                    f["win_probability"] * f["confidence"]
                    for f in event_forecasts
                ) / total_weight

                result["aggregated_win_probability"] = weighted_win_prob
                result["forecast_confidence"] = min(1.0, total_weight / len(event_forecasts))

    return result


if __name__ == "__main__":
    # Test the forecaster
    print("Testing NFL Event Forecaster...")
    print("="*60)

    from db import get_conn

    # Get a recent Cowboys event to test with
    team_symbol = "NFL:DAL_COWBOYS"

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, title, timestamp
                FROM events
                WHERE (title ILIKE '%cowboys%' OR title ILIKE '%dallas%')
                  AND 'sports' = ANY(categories)
                ORDER BY timestamp DESC
                LIMIT 1
                """
            )
            event = cur.fetchone()

    if event:
        print(f"Test event: {event['title']}")
        print(f"Event date: {event['timestamp'].date()}")
        print()

        forecast = forecast_nfl_event(
            event_id=event['id'],
            team_symbol=team_symbol,
        )

        print("Forecast Results:")
        print(f"  Next game: {forecast.next_game_date.date() if forecast.next_game_date else 'None'}")
        print(f"  Days until game: {forecast.days_until_game:.1f}" if forecast.days_until_game else "  No game")
        print(f"  Win probability: {forecast.win_probability:.1%}" if forecast.win_probability else "  N/A")
        print(f"  Confidence: {forecast.confidence:.1%}")
        print(f"  Similar events found: {forecast.similar_events_found}")
        print(f"  Sample size: {forecast.sample_size}")

        if not forecast.forecast_available:
            print(f"  Note: {forecast.no_game_reason}")
    else:
        print("No Cowboys events found in database to test with")

    print("\n" + "="*60)
    print("Testing team forecast...")

    team_forecast = forecast_team_next_game(team_symbol, include_recent_events=True)

    if team_forecast["next_game_found"]:
        print(f"Next game: {team_forecast['game_date'].date()}")
        print(f"Days away: {team_forecast['days_until_game']:.1f}")
        print(f"Event forecasts found: {team_forecast.get('event_forecasts_count', 0)}")

        if team_forecast.get('aggregated_win_probability'):
            print(f"Aggregated win probability: {team_forecast['aggregated_win_probability']:.1%}")
    else:
        print("No upcoming games found")
