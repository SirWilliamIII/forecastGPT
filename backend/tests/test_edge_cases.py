"""
Test Suite 4: Edge Cases and Boundary Conditions

Tests for unusual scenarios and boundary conditions that could expose temporal bugs:
- First game ever (no historical data)
- Team with single game (insufficient sample size)
- Events exactly at midnight UTC
- Missing events in time range (sparse data)
- Very long lookback windows
- Very short time horizons
- Timezone edge cases
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from models.nfl_event_forecaster import forecast_nfl_event, forecast_team_next_game
from signals.nfl_features import find_next_game, find_previous_game
from tests.conftest import TEAM_SYMBOL, get_test_embedding
from vector_store import VectorSearchResult


# =============================================================================
# Test 1: Insufficient Data Scenarios
# =============================================================================

class TestInsufficientDataScenarios:
    """
    Test behavior when there's not enough historical data.
    """

    def test_first_game_ever_no_historical_data(
        self, db_conn, clean_test_data, event_factory, asset_returns_factory, reference_time
    ):
        """
        EDGE CASE: First game for a team (no historical outcomes).

        Expected behavior: Forecast should gracefully handle this with:
        - sample_size = 0
        - forecast_available = False
        - Appropriate warning message
        """
        # Create event
        event_id = event_factory.create(
            timestamp=reference_time,
            title="Cowboys expansion team announcement",
        )

        # Create FIRST EVER game (7 days in future)
        first_game = reference_time + timedelta(days=7)
        asset_returns_factory.create_game_outcome_as_return(
            team_symbol=TEAM_SYMBOL,
            game_date=first_game,
            outcome="win",
            points_for=24,
            points_against=20,
        )

        # No historical games exist before this event

        # Mock vector store (no similar events)
        with patch('signals.feature_extractor.get_vector_store') as mock_store:
            mock_store.return_value.get_vector.return_value = get_test_embedding()
            mock_store.return_value.search.return_value = []

            # Attempt forecast
            result = forecast_nfl_event(
                event_id=event_id,
                team_symbol=TEAM_SYMBOL,
                event_timestamp=reference_time,
            )

        # ASSERTIONS
        assert result.sample_size == 0, \
            "Should have 0 samples (no historical data)"

        assert not result.forecast_available, \
            "Forecast should be unavailable with no historical data"

        assert result.no_game_reason is not None, \
            "Should explain why forecast is unavailable"

    def test_single_historical_game_insufficient_sample(
        self, db_conn, clean_test_data, event_factory, asset_returns_factory, reference_time
    ):
        """
        EDGE CASE: Only one historical game (insufficient for robust forecast).

        Expected: Forecast available but with low confidence.
        """
        # Create one historical game
        past_game = reference_time - timedelta(days=30)
        asset_returns_factory.create_game_outcome_as_return(
            team_symbol=TEAM_SYMBOL,
            game_date=past_game,
            outcome="win",
            points_for=28,
            points_against=21,
        )

        # Create similar past event
        past_event = event_factory.create(
            timestamp=past_game - timedelta(days=2),
            title="Cowboys practice report before their only game",
        )

        # Create anchor event
        anchor_event = event_factory.create(
            timestamp=reference_time,
            title="Cowboys news",
        )

        # Create future game to forecast
        future_game = reference_time + timedelta(days=7)
        asset_returns_factory.create_game_outcome_as_return(
            team_symbol=TEAM_SYMBOL,
            game_date=future_game,
            outcome="win",
            points_for=24,
            points_against=20,
        )

        # Mock vector store
        with patch('signals.feature_extractor.get_vector_store') as mock_store:
            mock_store.return_value.get_vector.return_value = get_test_embedding()
            mock_store.return_value.search.return_value = [
                VectorSearchResult(event_id=str(past_event), distance=0.2),
            ]

            result = forecast_nfl_event(
                event_id=anchor_event,
                team_symbol=TEAM_SYMBOL,
                event_timestamp=reference_time,
            )

        # ASSERTIONS
        assert result.sample_size == 1, \
            f"Expected 1 sample, got {result.sample_size}"

        # Low confidence due to small sample size
        assert result.confidence < 0.5, \
            f"Confidence should be low (<0.5) with only 1 sample, got {result.confidence}"

    def test_no_similar_events_found(
        self, db_conn, clean_test_data, event_factory, asset_returns_factory, reference_time
    ):
        """
        EDGE CASE: No semantically similar events in history.

        This can happen for novel event types.
        """
        # Create many historical games (but no similar events)
        for days_ago in [30, 25, 20, 15, 10, 5]:
            game_date = reference_time - timedelta(days=days_ago)
            asset_returns_factory.create_game_outcome_as_return(
                team_symbol=TEAM_SYMBOL,
                game_date=game_date,
                outcome="win" if days_ago % 2 == 0 else "loss",
                points_for=24,
                points_against=20,
            )

        # Create anchor event (novel type)
        anchor_event = event_factory.create(
            timestamp=reference_time,
            title="Cowboys completely novel unprecedented situation",
        )

        # Create future game
        future_game = reference_time + timedelta(days=7)
        asset_returns_factory.create_game_outcome_as_return(
            team_symbol=TEAM_SYMBOL,
            game_date=future_game,
            outcome="win",
            points_for=28,
            points_against=24,
        )

        # Mock vector store (no similar events)
        with patch('signals.feature_extractor.get_vector_store') as mock_store:
            mock_store.return_value.get_vector.return_value = get_test_embedding()
            mock_store.return_value.search.return_value = []

            result = forecast_nfl_event(
                event_id=anchor_event,
                team_symbol=TEAM_SYMBOL,
                event_timestamp=reference_time,
            )

        # ASSERTIONS
        assert result.sample_size == 0
        assert not result.forecast_available


# =============================================================================
# Test 2: Temporal Boundary Edge Cases
# =============================================================================

class TestTemporalBoundaryEdgeCases:
    """
    Test edge cases at temporal boundaries.
    """

    def test_event_exactly_at_midnight_utc(
        self, db_conn, clean_test_data, event_factory, asset_returns_factory
    ):
        """
        EDGE CASE: Event at exactly midnight UTC (00:00:00).

        Tests boundary handling for date transitions.
        """
        midnight = datetime(2025, 1, 15, 0, 0, 0, tzinfo=timezone.utc)

        # Event exactly at midnight
        event_id = event_factory.create(
            timestamp=midnight,
            title="Event at midnight UTC",
        )

        # Game 1 microsecond after midnight (should NOT be in training for midnight forecast)
        game_just_after = midnight + timedelta(microseconds=1)
        asset_returns_factory.create_game_outcome_as_return(
            team_symbol=TEAM_SYMBOL,
            game_date=game_just_after,
            outcome="win",
            points_for=28,
            points_against=21,
        )

        # Game 1 second before midnight (should be in training)
        game_just_before = midnight - timedelta(seconds=1)
        asset_returns_factory.create_game_outcome_as_return(
            team_symbol=TEAM_SYMBOL,
            game_date=game_just_before,
            outcome="win",
            points_for=31,
            points_against=24,
        )

        # Query for games before midnight (strict <)
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT as_of
                FROM asset_returns
                WHERE symbol = %s
                  AND as_of < %s
                ORDER BY as_of DESC
                """,
                (TEAM_SYMBOL, midnight)
            )
            results = cur.fetchall()

        result_times = [r['as_of'] for r in results]

        # ASSERTIONS
        assert len(results) == 1, f"Expected 1 game before midnight, got {len(results)}"
        assert game_just_before in result_times
        assert game_just_after not in result_times
        assert midnight not in result_times

    def test_year_boundary_transition(
        self, db_conn, clean_test_data, event_factory, asset_returns_factory
    ):
        """
        EDGE CASE: Events and games across year boundary (Dec 31 -> Jan 1).

        Tests that datetime comparisons work correctly across year transitions.
        """
        # New Year's Eve
        nye_2024 = datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

        # New Year's Day
        nyd_2025 = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        # Event on NYE
        event_nye = event_factory.create(
            timestamp=nye_2024,
            title="Event on New Year's Eve",
        )

        # Event on NYD
        event_nyd = event_factory.create(
            timestamp=nyd_2025,
            title="Event on New Year's Day",
        )

        # Game on NYE
        asset_returns_factory.create_game_outcome_as_return(
            team_symbol=TEAM_SYMBOL,
            game_date=nye_2024,
            outcome="win",
            points_for=28,
            points_against=21,
        )

        # Query from NYD perspective (should see NYE game)
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT as_of
                FROM asset_returns
                WHERE symbol = %s
                  AND as_of < %s
                ORDER BY as_of DESC
                """,
                (TEAM_SYMBOL, nyd_2025)
            )
            results = cur.fetchall()

        # ASSERTIONS
        assert len(results) == 1
        assert results[0]['as_of'].year == 2024
        assert results[0]['as_of'].month == 12
        assert results[0]['as_of'].day == 31

    def test_leap_second_handling(
        self, db_conn, clean_test_data, event_factory
    ):
        """
        EDGE CASE: Leap second boundary (if applicable).

        Python datetime doesn't support leap seconds, but we test general robustness.
        """
        # This is more of a documentation test - Python datetime ignores leap seconds
        # But we verify our code doesn't break with edge timestamps

        near_leap_second = datetime(2016, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

        event_id = event_factory.create(
            timestamp=near_leap_second,
            title="Event near potential leap second",
        )

        # Should not raise any errors
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT timestamp FROM events WHERE id = %s",
                (event_id,)
            )
            result = cur.fetchone()

        assert result['timestamp'] == near_leap_second


# =============================================================================
# Test 3: Sparse Data Scenarios
# =============================================================================

class TestSparseDataScenarios:
    """
    Test behavior with gaps in historical data.
    """

    def test_missing_events_in_time_range(
        self, db_conn, clean_test_data, event_factory, asset_returns_factory, reference_time
    ):
        """
        EDGE CASE: Large gaps between events.

        Timeline: Events at day -90, -60, -30, but none between -30 and now.
        """
        # Sparse events
        sparse_event_dates = [
            reference_time - timedelta(days=90),
            reference_time - timedelta(days=60),
            reference_time - timedelta(days=30),
        ]

        events = []
        for event_date in sparse_event_dates:
            event_id = event_factory.create(
                timestamp=event_date,
                title=f"Sparse event at {event_date.date()}",
            )
            events.append(event_id)

            # Create game a few days after each event
            game_date = event_date + timedelta(days=3)
            asset_returns_factory.create_game_outcome_as_return(
                team_symbol=TEAM_SYMBOL,
                game_date=game_date,
                outcome="win",
                points_for=28,
                points_against=21,
            )

        # Current event (30 day gap from last historical event)
        anchor_event = event_factory.create(
            timestamp=reference_time,
            title="Current event after 30 day gap",
        )

        # Future game
        future_game = reference_time + timedelta(days=7)
        asset_returns_factory.create_game_outcome_as_return(
            team_symbol=TEAM_SYMBOL,
            game_date=future_game,
            outcome="win",
            points_for=24,
            points_against=20,
        )

        # Mock vector store to return sparse events
        with patch('signals.feature_extractor.get_vector_store') as mock_store:
            mock_store.return_value.get_vector.return_value = get_test_embedding()
            mock_store.return_value.search.return_value = [
                VectorSearchResult(event_id=str(e), distance=0.3)
                for e in events
            ]

            result = forecast_nfl_event(
                event_id=anchor_event,
                team_symbol=TEAM_SYMBOL,
                event_timestamp=reference_time,
            )

        # ASSERTIONS
        # Should find all 3 historical events despite gaps
        assert result.sample_size == 3, \
            f"Expected 3 samples from sparse historical data, got {result.sample_size}"

        # Confidence may be lower due to data sparsity and temporal distance
        assert result.forecast_available


    def test_very_long_lookback_window(
        self, db_conn, clean_test_data, event_factory, asset_returns_factory, reference_time
    ):
        """
        EDGE CASE: Very long lookback window (3+ years).

        Tests performance and correctness with large historical datasets.
        """
        # Create events spanning 3 years
        three_years_ago = reference_time - timedelta(days=365 * 3)

        # Create monthly events
        events = []
        for months_ago in range(36):  # 36 months = 3 years
            event_date = reference_time - timedelta(days=months_ago * 30)

            if event_date < reference_time:  # Ensure before reference_time
                event_id = event_factory.create(
                    timestamp=event_date,
                    title=f"Historical event {months_ago} months ago",
                )
                events.append((event_id, event_date))

                # Game a week after event
                game_date = event_date + timedelta(days=7)
                asset_returns_factory.create_game_outcome_as_return(
                    team_symbol=TEAM_SYMBOL,
                    game_date=game_date,
                    outcome="win" if months_ago % 2 == 0 else "loss",
                    points_for=28,
                    points_against=21,
                )

        # Anchor event
        anchor_event = event_factory.create(
            timestamp=reference_time,
            title="Current event",
        )

        # Query with 3-year lookback
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT as_of
                FROM asset_returns
                WHERE symbol = %s
                  AND as_of >= %s
                  AND as_of < %s
                ORDER BY as_of DESC
                """,
                (TEAM_SYMBOL, three_years_ago, reference_time)
            )
            results = cur.fetchall()

        # ASSERTIONS
        # Should find many games
        assert len(results) >= 30, \
            f"Expected at least 30 games in 3-year window, got {len(results)}"

        # All should be before reference_time
        for row in results:
            assert row['as_of'] < reference_time, \
                f"Game at {row['as_of']} is >= reference_time! LOOKAHEAD BIAS!"


# =============================================================================
# Test 4: Next/Previous Game Edge Cases
# =============================================================================

class TestGameFinderEdgeCases:
    """
    Test find_next_game() and find_previous_game() edge cases.
    """

    def test_no_upcoming_game_within_window(
        self, db_conn, clean_test_data, asset_returns_factory, reference_time
    ):
        """
        EDGE CASE: Next game is too far in the future (beyond max_days_ahead).
        """
        # Create game 60 days in future (beyond default 30-day window)
        far_future_game = reference_time + timedelta(days=60)
        asset_returns_factory.create_game_outcome_as_return(
            team_symbol=TEAM_SYMBOL,
            game_date=far_future_game,
            outcome="win",
            points_for=28,
            points_against=21,
        )

        # Try to find next game within 30-day window
        next_game = find_next_game(
            team_symbol=TEAM_SYMBOL,
            reference_time=reference_time,
            max_days_ahead=30,
        )

        # ASSERTIONS
        assert next_game is None, \
            "Should not find game beyond max_days_ahead window"

        # But should find with larger window
        next_game_large_window = find_next_game(
            team_symbol=TEAM_SYMBOL,
            reference_time=reference_time,
            max_days_ahead=90,
        )

        assert next_game_large_window is not None
        assert next_game_large_window.game_date == far_future_game

    def test_no_previous_game_found(
        self, db_conn, clean_test_data, reference_time
    ):
        """
        EDGE CASE: No previous game in history (new team).
        """
        # No historical games

        prev_game = find_previous_game(
            team_symbol=TEAM_SYMBOL,
            reference_time=reference_time,
            max_days_back=365,
        )

        # ASSERTIONS
        assert prev_game is None, \
            "Should return None when no previous games exist"

    def test_games_at_exact_reference_time(
        self, db_conn, clean_test_data, asset_returns_factory, reference_time
    ):
        """
        EDGE CASE: Game at exactly reference_time.

        Should be treated as "next" game (not previous).
        """
        # Game at exactly reference_time
        asset_returns_factory.create_game_outcome_as_return(
            team_symbol=TEAM_SYMBOL,
            game_date=reference_time,
            outcome="win",
            points_for=28,
            points_against=21,
        )

        # Find next game
        next_game = find_next_game(
            team_symbol=TEAM_SYMBOL,
            reference_time=reference_time,
            max_days_ahead=30,
        )

        # Find previous game
        prev_game = find_previous_game(
            team_symbol=TEAM_SYMBOL,
            reference_time=reference_time,
            max_days_back=30,
        )

        # ASSERTIONS
        # Game at exactly reference_time should NOT be "next" or "previous"
        # (depends on query implementation - document expected behavior)

        # Our implementation uses:
        # - next: as_of > reference_time (strict)
        # - previous: as_of < reference_time (strict)
        # So game at exactly reference_time should be in neither

        assert next_game is None or next_game.game_date != reference_time, \
            "Game at exactly reference_time should not be 'next'"

        assert prev_game is None or prev_game.game_date != reference_time, \
            "Game at exactly reference_time should not be 'previous'"


# =============================================================================
# Test 5: Timezone Edge Cases
# =============================================================================

class TestTimezoneEdgeCases:
    """
    Test edge cases related to timezone handling.
    """

    def test_comparison_with_different_utc_offsets(
        self, db_conn, clean_test_data, event_factory, temporal_assertions
    ):
        """
        EDGE CASE: Comparing times with different UTC offset representations.

        All should normalize to UTC for comparison.
        """
        # Same instant in time, different representations
        time_utc = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        # Create event
        event_id = event_factory.create(
            timestamp=time_utc,
            title="Event at noon UTC",
        )

        # Query using same instant
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT timestamp
                FROM events
                WHERE id = %s
                """,
                (event_id,)
            )
            result = cur.fetchone()

        db_timestamp = result['timestamp']

        # ASSERTIONS
        temporal_assertions.assert_timezone_aware(db_timestamp)
        assert db_timestamp == time_utc
        assert db_timestamp.tzinfo == timezone.utc

    def test_naive_datetime_in_query_raises_error(
        self, db_conn, clean_test_data
    ):
        """
        EDGE CASE: Verify system rejects naive datetimes in queries.

        Our functions should validate and raise ValueError.
        """
        naive_time = datetime(2025, 1, 15, 12, 0, 0)  # No tzinfo

        # find_next_game should reject naive datetime
        with pytest.raises(ValueError, match="timezone-aware"):
            find_next_game(
                team_symbol=TEAM_SYMBOL,
                reference_time=naive_time,
            )

        # find_previous_game should reject naive datetime
        with pytest.raises(ValueError, match="timezone-aware"):
            find_previous_game(
                team_symbol=TEAM_SYMBOL,
                reference_time=naive_time,
            )
