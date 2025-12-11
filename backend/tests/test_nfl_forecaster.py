# backend/tests/test_nfl_forecaster.py

import pytest
from uuid import uuid4, UUID
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from models.nfl_event_forecaster import forecast_nfl_event
from db import get_conn
from vector_store import VectorSearchResult

# Mock data
TEAM_SYMBOL = "NFL:DAL_COWBOYS"

@pytest.fixture(scope="module")
def db_conn():
    """Fixture to manage database connection."""
    with get_conn() as conn:
        yield conn

@pytest.fixture(scope="module")
def setup_test_data(db_conn):
    """Fixture to insert a test event and a test game outcome."""
    event_id = uuid4()
    neighbor_event_id = uuid4()
    
    event_time = datetime(2025, 12, 1, 12, 0, 0, tzinfo=timezone.utc)
    neighbor_event_time = event_time - timedelta(days=10)
    game_time = datetime(2025, 12, 5, 18, 0, 0, tzinfo=timezone.utc)
    neighbor_game_time = neighbor_event_time + timedelta(days=3)

    game_id = "test_game_123"
    neighbor_game_id = "neighbor_game_456"
    
    dummy_embedding = [0.1] * 3072

    with db_conn.cursor() as cur:
        # Clean up previous test data if any
        cur.execute("DELETE FROM events WHERE id IN (%s, %s)", (event_id, neighbor_event_id))
        cur.execute("DELETE FROM game_outcomes WHERE game_id IN (%s, %s)", (game_id, neighbor_game_id))

        # Insert test data
        cur.execute(
            """
            INSERT INTO events (id, timestamp, source, title, summary, raw_text, clean_text, categories, embed)
            VALUES (%s, %s, 'test_source', 'Test Cowboys Event', 'A test event for the Cowboys', 'A test event for the Cowboys', 'A test event for the Cowboys', ARRAY['sports'], %s)
            """,
            (event_id, event_time, dummy_embedding)
        )
        cur.execute(
            """
            INSERT INTO events (id, timestamp, source, title, summary, raw_text, clean_text, categories, embed)
            VALUES (%s, %s, 'test_source', 'Similar Cowboys Event', 'Another test event for the Cowboys', 'Another test event for the Cowboys', 'Another test event for the Cowboys', ARRAY['sports'], %s)
            """,
            (neighbor_event_id, neighbor_event_time, dummy_embedding)
        )
        cur.execute(
            """
            INSERT INTO game_outcomes (game_id, game_date, team_symbol, opponent_symbol, outcome, points_for, points_against, point_differential, is_home)
            VALUES (%s, %s, %s, 'NFL:PHI_EAGLES', 'win', 35, 17, 18, true)
            """,
            (game_id, game_time, TEAM_SYMBOL)
        )
        cur.execute(
            """
            INSERT INTO game_outcomes (game_id, game_date, team_symbol, opponent_symbol, outcome, points_for, points_against, point_differential, is_home)
            VALUES (%s, %s, %s, 'NFL:NY_GIANTS', 'loss', 10, 24, -14, false)
            """,
            (neighbor_game_id, neighbor_game_time, TEAM_SYMBOL)
        )
    db_conn.commit()

    return event_id, neighbor_event_id, event_time, neighbor_event_time, game_time

@patch('signals.feature_extractor.get_vector_store')
def test_forecast_nfl_event_finds_game(mock_get_vector_store, setup_test_data):
    """
    Test that forecast_nfl_event successfully finds an upcoming game
    from the game_outcomes table.
    """
    event_id, neighbor_event_id, event_time, neighbor_event_time, game_time = setup_test_data
    
    mock_get_vector_store.return_value.get_vector.return_value = [0.1] * 3072
    mock_get_vector_store.return_value.search.return_value = [
        VectorSearchResult(event_id=str(neighbor_event_id), distance=0.5)
    ]

    forecast = forecast_nfl_event(
        event_id=event_id,
        team_symbol=TEAM_SYMBOL,
        event_timestamp=event_time
    )

    assert forecast.forecast_available is True
    assert forecast.next_game_date is not None
    assert abs((forecast.next_game_date - game_time).total_seconds()) < 60
    assert forecast.sample_size > 0

def test_forecast_nfl_event_no_game():
    """
    Test that forecast_nfl_event returns a clean "no game" result
    when no upcoming game is found.
    """
    event_id = uuid4()
    
    forecast = forecast_nfl_event(
        event_id=event_id,
        team_symbol=TEAM_SYMBOL,
        event_timestamp=datetime.now(tz=timezone.utc) - timedelta(days=1000)
    )

    assert forecast.forecast_available is False
    assert forecast.no_game_reason == "No upcoming game found within 30 days"