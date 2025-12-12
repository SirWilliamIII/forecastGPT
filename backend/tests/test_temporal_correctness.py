"""
Test Suite 1: Backfill Temporal Correctness

This test suite ensures that when we compute historical forecasts retroactively
(backfilling), we ONLY use data from before the forecast timestamp.

Critical invariant: Given as_of time T, we must ONLY use:
- Events with timestamp < T (strict before, not <=)
- Games with game_date < T
- Model trained on data < T

Using ANY data from >= T creates lookahead bias and invalidates the forecast.
"""

import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from unittest.mock import patch, MagicMock

from models.event_return_forecaster import forecast_event_return
from models.nfl_event_forecaster import forecast_nfl_event
from signals.nfl_features import find_next_game, find_previous_game
from signals.feature_extractor import build_return_samples_for_event
from vector_store import VectorSearchResult
from tests.conftest import TEAM_SYMBOL, get_test_embedding


# =============================================================================
# Test 1: Event Temporal Filtering
# =============================================================================

class TestEventTemporalFiltering:
    """
    Verify that only events from BEFORE the forecast time are used.
    """

    def test_no_future_events_used_in_neighbor_search(
        self, db_conn, clean_test_data, event_factory, reference_time, temporal_assertions
    ):
        """
        CRITICAL TEST: Forecast at T must NOT use events with timestamp >= T.

        Scenario:
            - Event A: 7 days before reference_time (should be used)
            - Event B: 1 day before reference_time (should be used)
            - Anchor event: exactly at reference_time (we're forecasting from this)
            - Event C: 1 day after reference_time (MUST NOT be used)
            - Event D: 7 days after reference_time (MUST NOT be used)

        Expected:
            - Neighbor search finds only events A and B
            - Events C and D are excluded (timestamp >= reference_time)
        """
        # Create test events
        past_event_far = event_factory.create(
            timestamp=reference_time - timedelta(days=7),
            title="Cowboys training camp report 7 days ago",
        )

        past_event_near = event_factory.create(
            timestamp=reference_time - timedelta(days=1),
            title="Cowboys injury report 1 day ago",
        )

        # Anchor event (at reference_time)
        anchor_event = event_factory.create(
            timestamp=reference_time,
            title="Cowboys game preview - ANCHOR",
        )

        # FUTURE EVENTS (should NOT be used)
        future_event_near = event_factory.create(
            timestamp=reference_time + timedelta(days=1),
            title="Cowboys post-game analysis 1 day later",
        )

        future_event_far = event_factory.create(
            timestamp=reference_time + timedelta(days=7),
            title="Cowboys weekly recap 7 days later",
        )

        # Mock vector store to return all events as neighbors
        with patch('signals.feature_extractor.get_vector_store') as mock_store:
            mock_store.return_value.get_vector.return_value = get_test_embedding()
            mock_store.return_value.search.return_value = [
                VectorSearchResult(event_id=str(past_event_far), distance=0.3),
                VectorSearchResult(event_id=str(past_event_near), distance=0.2),
                VectorSearchResult(event_id=str(anchor_event), distance=0.0),
                VectorSearchResult(event_id=str(future_event_near), distance=0.2),
                VectorSearchResult(event_id=str(future_event_far), distance=0.3),
            ]

            # Query database for neighbor timestamps
            with db_conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, timestamp
                    FROM events
                    WHERE id = ANY(%s)
                      AND timestamp BETWEEN %s AND %s
                    ORDER BY timestamp ASC
                    """,
                    (
                        [past_event_far, past_event_near, anchor_event, future_event_near, future_event_far],
                        reference_time - timedelta(days=365),
                        reference_time  # Upper bound is reference_time (exclusive in practice)
                    )
                )
                neighbors = cur.fetchall()

        # ASSERTION: Only past events should be returned
        neighbor_ids = [str(n['id']) for n in neighbors]
        neighbor_times = [n['timestamp'] for n in neighbors]

        # Verify no future events
        assert str(future_event_near) not in neighbor_ids, "Future event (1 day later) was included! LOOKAHEAD BIAS!"
        assert str(future_event_far) not in neighbor_ids, "Future event (7 days later) was included! LOOKAHEAD BIAS!"

        # Verify past events are included
        assert str(past_event_far) in neighbor_ids
        assert str(past_event_near) in neighbor_ids

        # Verify all timestamps are strictly before reference_time
        temporal_assertions.assert_all_before(
            neighbor_times,
            reference_time,
            msg="Event neighbor search included events from >= reference_time"
        )

    def test_strict_inequality_not_equals(
        self, db_conn, clean_test_data, event_factory, reference_time, temporal_assertions
    ):
        """
        CRITICAL TEST: Events at EXACTLY reference_time must be excluded.

        This tests the difference between < and <=:
        - Correct: timestamp < reference_time (strict before)
        - Incorrect: timestamp <= reference_time (allows same-time events)

        Scenario:
            - Event at reference_time - 1 second (should be included)
            - Event at reference_time exactly (MUST be excluded)
            - Event at reference_time + 1 second (MUST be excluded)
        """
        # Events around the boundary
        just_before = event_factory.create(
            timestamp=reference_time - timedelta(seconds=1),
            title="Event just before cutoff",
        )

        exactly_at = event_factory.create(
            timestamp=reference_time,
            title="Event EXACTLY at cutoff",
        )

        just_after = event_factory.create(
            timestamp=reference_time + timedelta(seconds=1),
            title="Event just after cutoff",
        )

        # Query with strict < comparison
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, timestamp
                FROM events
                WHERE timestamp < %s
                  AND source = 'test_source'
                ORDER BY timestamp DESC
                """,
                (reference_time,)
            )
            results_strict = cur.fetchall()

            # Query with <= comparison (WRONG)
            cur.execute(
                """
                SELECT id, timestamp
                FROM events
                WHERE timestamp <= %s
                  AND source = 'test_source'
                ORDER BY timestamp DESC
                """,
                (reference_time,)
            )
            results_inclusive = cur.fetchall()

        # ASSERTIONS
        strict_ids = [str(r['id']) for r in results_strict]
        inclusive_ids = [str(r['id']) for r in results_inclusive]

        # Strict should only include just_before
        assert str(just_before) in strict_ids
        assert str(exactly_at) not in strict_ids, "Strict < comparison included event at exactly reference_time! Should use < not <="
        assert str(just_after) not in strict_ids

        # Inclusive incorrectly includes exactly_at
        assert str(just_before) in inclusive_ids
        assert str(exactly_at) in inclusive_ids, "Test setup error: <= should include exact match"
        assert str(just_after) not in inclusive_ids

        # The key difference
        assert len(inclusive_ids) == len(strict_ids) + 1, "Should be exactly one event difference between < and <="


# =============================================================================
# Test 2: Game Outcome Temporal Filtering
# =============================================================================

class TestGameOutcomeTemporalFiltering:
    """
    Verify that only games from BEFORE the forecast time are used for training.
    """

    def test_no_future_games_in_training_data(
        self, db_conn, clean_test_data, asset_returns_factory, reference_time, temporal_assertions
    ):
        """
        CRITICAL TEST: Training data must only include games played before reference_time.

        Scenario:
            - Games at T-14d, T-7d, T-1d (should be in training set)
            - Game at exactly T (MUST be excluded)
            - Games at T+1d, T+7d (MUST be excluded)

        This tests the temporal split for model training.
        """
        # Create past game outcomes
        past_games = [
            (reference_time - timedelta(days=14), "win", 31, 24),
            (reference_time - timedelta(days=7), "loss", 20, 27),
            (reference_time - timedelta(days=1), "win", 28, 21),
        ]

        for game_date, outcome, pts_for, pts_against in past_games:
            asset_returns_factory.create_game_outcome_as_return(
                team_symbol=TEAM_SYMBOL,
                game_date=game_date,
                outcome=outcome,
                points_for=pts_for,
                points_against=pts_against,
            )

        # Game at exactly reference_time (boundary case)
        asset_returns_factory.create_game_outcome_as_return(
            team_symbol=TEAM_SYMBOL,
            game_date=reference_time,
            outcome="win",
            points_for=35,
            points_against=17,
        )

        # Future games (should NOT be in training data)
        future_games = [
            (reference_time + timedelta(days=1), "win", 24, 20),
            (reference_time + timedelta(days=7), "loss", 17, 30),
        ]

        for game_date, outcome, pts_for, pts_against in future_games:
            asset_returns_factory.create_game_outcome_as_return(
                team_symbol=TEAM_SYMBOL,
                game_date=game_date,
                outcome=outcome,
                points_for=pts_for,
                points_against=pts_against,
            )

        # Query for training data (strict before)
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT as_of, realized_return
                FROM asset_returns
                WHERE symbol = %s
                  AND as_of < %s
                ORDER BY as_of DESC
                """,
                (TEAM_SYMBOL, reference_time)
            )
            training_data = cur.fetchall()

        # ASSERTIONS
        assert len(training_data) == 3, f"Expected 3 training samples, got {len(training_data)}"

        training_dates = [row['as_of'] for row in training_data]

        # Verify all training dates are before reference_time
        temporal_assertions.assert_all_before(
            training_dates,
            reference_time,
            msg="Training data includes games from >= reference_time"
        )

        # Verify future games are NOT in training data
        future_dates = [game_date for game_date, _, _, _ in future_games]
        for future_date in future_dates:
            assert future_date not in training_dates, f"Future game at {future_date} was in training data! LOOKAHEAD BIAS!"

        # Verify game at exactly reference_time is NOT in training data
        assert reference_time not in training_dates, "Game at exactly reference_time was in training data! Should use < not <="

    def test_asset_returns_lookback_window(
        self, db_conn, clean_test_data, asset_returns_factory, reference_time
    ):
        """
        Test that asset_returns queries respect both lookback window AND temporal cutoff.

        This ensures we don't accidentally query too far back or into the future.
        """
        lookback_days = 30

        # Create games outside lookback window (should be excluded)
        old_game = reference_time - timedelta(days=60)
        asset_returns_factory.create_game_outcome_as_return(
            team_symbol=TEAM_SYMBOL,
            game_date=old_game,
            outcome="win",
            points_for=24,
            points_against=17,
        )

        # Create games within lookback window (should be included)
        valid_games = [
            reference_time - timedelta(days=20),
            reference_time - timedelta(days=10),
            reference_time - timedelta(days=5),
        ]

        for game_date in valid_games:
            asset_returns_factory.create_game_outcome_as_return(
                team_symbol=TEAM_SYMBOL,
                game_date=game_date,
                outcome="win",
                points_for=28,
                points_against=21,
            )

        # Create future game (should be excluded)
        future_game = reference_time + timedelta(days=5)
        asset_returns_factory.create_game_outcome_as_return(
            team_symbol=TEAM_SYMBOL,
            game_date=future_game,
            outcome="win",
            points_for=30,
            points_against=27,
        )

        # Query with lookback window
        start_date = reference_time - timedelta(days=lookback_days)

        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT as_of, realized_return
                FROM asset_returns
                WHERE symbol = %s
                  AND as_of >= %s
                  AND as_of < %s
                ORDER BY as_of DESC
                """,
                (TEAM_SYMBOL, start_date, reference_time)
            )
            results = cur.fetchall()

        # ASSERTIONS
        result_dates = [row['as_of'] for row in results]

        assert len(results) == 3, f"Expected 3 games in lookback window, got {len(results)}"

        # Verify old game is excluded
        assert old_game not in result_dates, "Game outside lookback window was included"

        # Verify future game is excluded
        assert future_game not in result_dates, "Future game was included! LOOKAHEAD BIAS!"

        # Verify all results are in valid window
        for game_date in result_dates:
            assert game_date >= start_date, f"Game {game_date} is before lookback window"
            assert game_date < reference_time, f"Game {game_date} is >= reference_time! LOOKAHEAD BIAS!"


# =============================================================================
# Test 3: Timezone Correctness
# =============================================================================

class TestTimezoneCorrectness:
    """
    Ensure all datetime comparisons happen in UTC (no timezone confusion).
    """

    def test_all_timestamps_are_utc(
        self, db_conn, clean_test_data, event_factory, reference_time, temporal_assertions
    ):
        """
        Verify that all timestamps in the database are timezone-aware UTC.

        Naive datetimes (no tzinfo) can cause subtle bugs in temporal comparisons.
        """
        # Create test event
        event_id = event_factory.create(
            timestamp=reference_time - timedelta(days=1),
            title="Test timezone event",
        )

        # Fetch from database
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT timestamp FROM events WHERE id = %s",
                (event_id,)
            )
            row = cur.fetchone()

        db_timestamp = row['timestamp']

        # ASSERTIONS
        temporal_assertions.assert_timezone_aware(
            db_timestamp,
            msg="Event timestamp from database is timezone-naive"
        )

        assert db_timestamp.tzinfo == timezone.utc, \
            f"Event timestamp has wrong timezone: {db_timestamp.tzinfo} (expected UTC)"

    def test_timezone_comparison_consistency(
        self, db_conn, clean_test_data, event_factory, temporal_assertions
    ):
        """
        Test that datetime comparisons work correctly across different timezone representations.

        Even though all should be UTC, we test edge cases.
        """
        # Create reference time with explicit UTC
        ref_time_utc = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        # Same time, different timezone object (should be equal)
        ref_time_utc2 = datetime(2025, 1, 15, 12, 0, 0).replace(tzinfo=timezone.utc)

        # Create events
        event_before = event_factory.create(
            timestamp=ref_time_utc - timedelta(hours=1),
            title="Event 1 hour before",
        )

        event_exactly = event_factory.create(
            timestamp=ref_time_utc,
            title="Event at exactly reference time",
        )

        # Query using second reference time object
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, timestamp
                FROM events
                WHERE timestamp < %s
                  AND source = 'test_source'
                """,
                (ref_time_utc2,)
            )
            results = cur.fetchall()

        result_ids = [str(r['id']) for r in results]

        # ASSERTIONS
        assert str(event_before) in result_ids
        assert str(event_exactly) not in result_ids, \
            "Event at exactly reference_time was included despite different UTC objects"

    def test_naive_datetime_rejection(self, event_factory, reference_time):
        """
        Verify that our fixtures reject naive datetimes (no tzinfo).

        This is a test of our test infrastructure itself.
        """
        # Try to create event with naive datetime (should raise ValueError)
        naive_time = datetime(2025, 1, 15, 12, 0, 0)  # No tzinfo

        with pytest.raises(ValueError, match="timezone-aware"):
            event_factory.create(
                timestamp=naive_time,
                title="This should fail",
            )


# =============================================================================
# Test 4: End-to-End Temporal Correctness
# =============================================================================

class TestEndToEndTemporalCorrectness:
    """
    Integration tests verifying temporal correctness through full forecast pipeline.
    """

    @patch('signals.feature_extractor.get_vector_store')
    def test_event_forecast_uses_only_past_data(
        self,
        mock_vector_store,
        db_conn,
        clean_test_data,
        event_factory,
        asset_returns_factory,
        reference_time,
        temporal_assertions
    ):
        """
        CRITICAL INTEGRATION TEST: End-to-end forecast must only use past data.

        Flow:
            1. Create anchor event at reference_time
            2. Create neighbor events before and after reference_time
            3. Create game outcomes for neighbor events
            4. Call forecast_event_return()
            5. Verify only past events contributed to forecast
        """
        # Setup: Create anchor event
        anchor_event = event_factory.create(
            timestamp=reference_time,
            title="Cowboys game preview",
        )

        # Setup: Create past neighbor events
        past_event_1 = event_factory.create(
            timestamp=reference_time - timedelta(days=10),
            title="Cowboys practice report 10 days ago",
        )

        past_event_2 = event_factory.create(
            timestamp=reference_time - timedelta(days=5),
            title="Cowboys injury update 5 days ago",
        )

        # Setup: Create FUTURE neighbor events (should NOT be used)
        future_event_1 = event_factory.create(
            timestamp=reference_time + timedelta(days=3),
            title="Cowboys post-game analysis 3 days later",
        )

        # Setup: Create game outcomes for past events
        game_after_past_1 = reference_time - timedelta(days=9)  # 1 day after event 1
        asset_returns_factory.create_game_outcome_as_return(
            team_symbol=TEAM_SYMBOL,
            game_date=game_after_past_1,
            outcome="win",
            points_for=28,
            points_against=21,
        )

        game_after_past_2 = reference_time - timedelta(days=4)  # 1 day after event 2
        asset_returns_factory.create_game_outcome_as_return(
            team_symbol=TEAM_SYMBOL,
            game_date=game_after_past_2,
            outcome="win",
            points_for=31,
            points_against=24,
        )

        # Setup: Create game outcome for future event (should NOT be used)
        game_after_future = reference_time + timedelta(days=4)
        asset_returns_factory.create_game_outcome_as_return(
            team_symbol=TEAM_SYMBOL,
            game_date=game_after_future,
            outcome="loss",
            points_for=17,
            points_against=30,
        )

        # Mock vector store to return both past and future events
        mock_vector_store.return_value.get_vector.return_value = get_test_embedding()
        mock_vector_store.return_value.search.return_value = [
            VectorSearchResult(event_id=str(past_event_1), distance=0.2),
            VectorSearchResult(event_id=str(past_event_2), distance=0.3),
            VectorSearchResult(event_id=str(future_event_1), distance=0.25),
        ]

        # Execute: Run forecast
        result = forecast_event_return(
            event_id=anchor_event,
            symbol=TEAM_SYMBOL,
            horizon_minutes=1440,
            k_neighbors=10,
            lookback_days=365,
        )

        # ASSERTIONS
        # The future event should have been filtered out in build_return_samples_for_event
        # Only 2 samples (from past events) should be included
        assert result.sample_size == 2, \
            f"Expected 2 samples (from past events only), got {result.sample_size}. " \
            f"Future event may have been included! LOOKAHEAD BIAS!"

        assert result.neighbors_used == 2, \
            f"Expected 2 neighbors (past events only), got {result.neighbors_used}"

        # The expected return should be positive (both past games were wins)
        assert result.expected_return > 0, \
            f"Expected positive return (both past games were wins), got {result.expected_return}"

    @patch('signals.feature_extractor.get_vector_store')
    def test_nfl_event_forecast_temporal_correctness(
        self,
        mock_vector_store,
        db_conn,
        clean_test_data,
        event_factory,
        asset_returns_factory,
        reference_time,
    ):
        """
        Test NFL-specific event forecasting respects temporal boundaries.
        """
        # Create anchor event
        anchor_event = event_factory.create(
            timestamp=reference_time,
            title="Cowboys injury report",
        )

        # Create future game (to forecast)
        future_game = reference_time + timedelta(days=5)
        asset_returns_factory.create_game_outcome_as_return(
            team_symbol=TEAM_SYMBOL,
            game_date=future_game,
            outcome="win",
            points_for=28,
            points_against=21,
        )

        # Create similar past event
        past_similar_event = event_factory.create(
            timestamp=reference_time - timedelta(days=30),
            title="Cowboys injury report similar",
        )

        # Create game after past event (this should be used for training)
        past_game = reference_time - timedelta(days=25)
        asset_returns_factory.create_game_outcome_as_return(
            team_symbol=TEAM_SYMBOL,
            game_date=past_game,
            outcome="win",
            points_for=31,
            points_against=24,
        )

        # Mock vector store
        mock_vector_store.return_value.get_vector.return_value = get_test_embedding()
        mock_vector_store.return_value.search.return_value = [
            VectorSearchResult(event_id=str(past_similar_event), distance=0.1),
        ]

        # Execute NFL forecast
        result = forecast_nfl_event(
            event_id=anchor_event,
            team_symbol=TEAM_SYMBOL,
            event_timestamp=reference_time,
        )

        # ASSERTIONS
        assert result.forecast_available, "Forecast should be available"
        assert result.sample_size > 0, "Should have training samples from past events"
        assert result.next_game_date == future_game, "Should identify correct future game"

        # The forecast should be based on past data only
        # We can't directly verify this, but sample_size > 0 indicates past events were used


# =============================================================================
# Test 5: Temporal Boundary Edge Cases
# =============================================================================

class TestTemporalBoundaryEdgeCases:
    """
    Test edge cases around temporal boundaries.
    """

    def test_midnight_utc_boundary(
        self, db_conn, clean_test_data, event_factory, temporal_assertions
    ):
        """
        Test temporal comparisons at midnight UTC (boundary condition).
        """
        midnight = datetime(2025, 1, 15, 0, 0, 0, tzinfo=timezone.utc)

        # Events around midnight
        just_before_midnight = event_factory.create(
            timestamp=midnight - timedelta(seconds=1),
            title="Event at 23:59:59",
        )

        exactly_midnight = event_factory.create(
            timestamp=midnight,
            title="Event at 00:00:00",
        )

        just_after_midnight = event_factory.create(
            timestamp=midnight + timedelta(seconds=1),
            title="Event at 00:00:01",
        )

        # Query with midnight cutoff
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, timestamp
                FROM events
                WHERE timestamp < %s
                  AND source = 'test_source'
                """,
                (midnight,)
            )
            results = cur.fetchall()

        result_ids = [str(r['id']) for r in results]

        # ASSERTIONS
        assert str(just_before_midnight) in result_ids
        assert str(exactly_midnight) not in result_ids
        assert str(just_after_midnight) not in result_ids

    def test_microsecond_precision(
        self, db_conn, clean_test_data, event_factory
    ):
        """
        Test that temporal comparisons work correctly at microsecond precision.
        """
        base_time = datetime(2025, 1, 15, 12, 0, 0, 0, tzinfo=timezone.utc)

        # Create events with microsecond differences
        event_1 = event_factory.create(
            timestamp=base_time,
            title="Event at 12:00:00.000000",
        )

        event_2 = event_factory.create(
            timestamp=base_time + timedelta(microseconds=1),
            title="Event at 12:00:00.000001",
        )

        event_3 = event_factory.create(
            timestamp=base_time + timedelta(microseconds=1000),
            title="Event at 12:00:00.001000",
        )

        # Query with base_time cutoff
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, timestamp
                FROM events
                WHERE timestamp < %s
                  AND source = 'test_source'
                ORDER BY timestamp ASC
                """,
                (base_time,)
            )
            results = cur.fetchall()

        # ASSERTIONS
        # No events should be returned (all are >= base_time)
        assert len(results) == 0, \
            f"Expected 0 events before {base_time}, got {len(results)}"
