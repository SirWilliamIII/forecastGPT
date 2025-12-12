# backend/tests/conftest.py
"""
Shared test fixtures for all backend tests.

Includes:
- FastAPI test client
- Database connections
- Test data factories (events, games, asset returns)
- Temporal test utilities
"""

import os
import sys

import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timezone, timedelta
from uuid import uuid4, UUID
from typing import List, Tuple, Optional
import numpy as np

# Ensure backend is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from db import get_conn


# =============================================================================
# API Test Fixtures
# =============================================================================

@pytest.fixture
def client():
    """FastAPI test client fixture."""
    return TestClient(app)


@pytest.fixture
def sample_event():
    """Sample event payload for testing."""
    return {
        "timestamp": "2024-01-15T12:00:00Z",
        "source": "test_source",
        "url": "https://example.com/test-article",
        "title": "Test AI Headline",
        "summary": "This is a test summary about artificial intelligence.",
        "raw_text": "Test AI Headline\n\nThis is a test summary about artificial intelligence.",
        "categories": ["ai", "tech"],
        "tags": ["artificial intelligence", "test"],
    }


# =============================================================================
# Test Data Constants
# =============================================================================

TEAM_SYMBOL = "NFL:DAL_COWBOYS"
OPPONENT_SYMBOL = "NFL:PHI_EAGLES"


def get_test_embedding() -> List[float]:
    """Generate a deterministic test embedding vector (3072 dimensions)."""
    np.random.seed(42)
    return np.random.randn(3072).tolist()


# =============================================================================
# Database Fixtures
# =============================================================================

@pytest.fixture(scope="function")
def db_conn():
    """
    Fixture providing a database connection with automatic cleanup.

    Scope: function - new connection per test for isolation.
    """
    with get_conn() as conn:
        yield conn


@pytest.fixture(scope="function")
def clean_test_data(db_conn):
    """
    Fixture that ensures test data is cleaned up before and after each test.

    Use this when you want to start with a clean slate.
    """
    def cleanup():
        with db_conn.cursor() as cur:
            # Delete test events (those with 'test_' prefix in source)
            cur.execute("DELETE FROM events WHERE source LIKE %s", ('test_%',))

            # Delete test game outcomes
            cur.execute("DELETE FROM game_outcomes WHERE game_id LIKE %s", ('test_%',))

            # Delete test asset returns
            cur.execute("""
                DELETE FROM asset_returns
                WHERE symbol LIKE %s OR symbol = %s
            """, ('TEST:%', TEAM_SYMBOL))

        db_conn.commit()

    # Cleanup before test
    cleanup()

    yield

    # Cleanup after test
    cleanup()


# =============================================================================
# Time Management Fixtures
# =============================================================================

@pytest.fixture
def reference_time() -> datetime:
    """
    Standard reference time for tests: 2025-01-15 12:00:00 UTC

    This is the "as_of" time for most backfill scenarios.
    """
    return datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def time_factory():
    """
    Factory fixture for creating timezone-aware datetimes relative to a base time.

    Usage:
        times = time_factory(base=datetime(2025, 1, 15, tzinfo=timezone.utc))
        past_event = times.offset(days=-7)
        future_event = times.offset(days=3)
    """
    class TimeFactory:
        def __init__(self, base: Optional[datetime] = None):
            if base is None:
                base = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
            elif base.tzinfo is None:
                raise ValueError("base must be timezone-aware")

            self.base = base

        def offset(self, days=0, hours=0, minutes=0, seconds=0) -> datetime:
            """Create a datetime offset from the base time."""
            delta = timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
            return self.base + delta

        def range(self, start_days: int, end_days: int, step_days: int = 1) -> List[datetime]:
            """Generate a range of datetimes."""
            return [
                self.offset(days=d)
                for d in range(start_days, end_days, step_days)
            ]

    return TimeFactory


# =============================================================================
# Event Fixtures
# =============================================================================

@pytest.fixture
def event_factory(db_conn):
    """
    Factory fixture for creating test events in the database.

    Usage:
        event_id = event_factory.create(
            timestamp=datetime(2025, 1, 10, tzinfo=timezone.utc),
            title="Cowboys win big",
            categories=["sports"]
        )
    """
    class EventFactory:
        def __init__(self, conn):
            self.conn = conn
            self.created_ids: List[UUID] = []

        def create(
            self,
            timestamp: datetime,
            title: str = "Test Event",
            summary: Optional[str] = None,
            categories: Optional[List[str]] = None,
            event_id: Optional[UUID] = None,
            source: str = "test_source",
            embed: Optional[List[float]] = None,
        ) -> UUID:
            """Create a test event and return its ID."""
            if timestamp.tzinfo is None:
                raise ValueError("timestamp must be timezone-aware")

            if event_id is None:
                event_id = uuid4()

            if categories is None:
                categories = ["sports"]

            if embed is None:
                embed = get_test_embedding()

            if summary is None:
                summary = title

            clean_text = f"{title}. {summary}"

            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO events (
                        id, timestamp, source, title, summary,
                        raw_text, clean_text, categories, embed
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        event_id, timestamp, source, title, summary,
                        clean_text, clean_text, categories, embed
                    )
                )

            self.conn.commit()
            self.created_ids.append(event_id)
            return event_id

        def create_many(
            self,
            timestamps: List[datetime],
            title_prefix: str = "Test Event",
            **kwargs
        ) -> List[UUID]:
            """Create multiple events with sequential timestamps."""
            return [
                self.create(
                    timestamp=ts,
                    title=f"{title_prefix} {i+1}",
                    **kwargs
                )
                for i, ts in enumerate(timestamps)
            ]

        def cleanup(self):
            """Delete all created events."""
            if self.created_ids:
                with self.conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM events WHERE id = ANY(%s)",
                        (self.created_ids,)
                    )
                self.conn.commit()
                self.created_ids.clear()

    factory = EventFactory(db_conn)
    yield factory
    factory.cleanup()


# =============================================================================
# Game Outcome Fixtures
# =============================================================================

@pytest.fixture
def game_factory(db_conn):
    """
    Factory fixture for creating test game outcomes in the database.

    Usage:
        game_factory.create(
            game_date=datetime(2025, 1, 12, 18, 0, tzinfo=timezone.utc),
            team_symbol="NFL:DAL_COWBOYS",
            outcome="win",
            points_for=28,
            points_against=21
        )
    """
    class GameFactory:
        def __init__(self, conn):
            self.conn = conn
            self.created_ids: List[str] = []

        def create(
            self,
            game_date: datetime,
            team_symbol: str = TEAM_SYMBOL,
            opponent_symbol: str = OPPONENT_SYMBOL,
            outcome: str = "win",
            points_for: int = 28,
            points_against: int = 21,
            is_home: bool = True,
            game_id: Optional[str] = None,
        ) -> str:
            """Create a test game outcome and return its game_id."""
            if game_date.tzinfo is None:
                raise ValueError("game_date must be timezone-aware")

            if game_id is None:
                game_id = f"test_game_{uuid4().hex[:8]}"

            point_differential = points_for - points_against

            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO game_outcomes (
                        game_id, game_date, team_symbol, opponent_symbol,
                        outcome, points_for, points_against, point_differential, is_home
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (game_id) DO NOTHING
                    """,
                    (
                        game_id, game_date, team_symbol, opponent_symbol,
                        outcome, points_for, points_against, point_differential, is_home
                    )
                )

            self.conn.commit()
            self.created_ids.append(game_id)
            return game_id

        def create_many(
            self,
            game_dates: List[datetime],
            outcomes: Optional[List[str]] = None,
            **kwargs
        ) -> List[str]:
            """Create multiple game outcomes."""
            if outcomes is None:
                outcomes = ["win"] * len(game_dates)

            return [
                self.create(game_date=gd, outcome=outcome, **kwargs)
                for gd, outcome in zip(game_dates, outcomes)
            ]

        def cleanup(self):
            """Delete all created game outcomes."""
            if self.created_ids:
                with self.conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM game_outcomes WHERE game_id = ANY(%s)",
                        (self.created_ids,)
                    )
                self.conn.commit()
                self.created_ids.clear()

    factory = GameFactory(db_conn)
    yield factory
    factory.cleanup()


# =============================================================================
# Asset Returns Fixtures
# =============================================================================

@pytest.fixture
def asset_returns_factory(db_conn):
    """
    Factory fixture for creating test asset returns.

    For NFL games, asset_returns stores the game outcomes as returns:
    - as_of: game datetime
    - realized_return: 1.0 for win, -1.0 for loss
    - price_start/price_end: points scored (for differential calculation)
    """
    class AssetReturnsFactory:
        def __init__(self, conn):
            self.conn = conn
            self.created_records: List[Tuple[str, datetime, int]] = []

        def create(
            self,
            symbol: str,
            as_of: datetime,
            horizon_minutes: int = 1440,
            realized_return: float = 1.0,
            price_start: float = 0.0,
            price_end: float = 1.0,
        ):
            """Create a test asset return record."""
            if as_of.tzinfo is None:
                raise ValueError("as_of must be timezone-aware")

            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO asset_returns (
                        symbol, as_of, horizon_minutes,
                        realized_return, price_start, price_end
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (symbol, as_of, horizon_minutes) DO NOTHING
                    """,
                    (symbol, as_of, horizon_minutes, realized_return, price_start, price_end)
                )

            self.conn.commit()
            self.created_records.append((symbol, as_of, horizon_minutes))

        def create_game_outcome_as_return(
            self,
            team_symbol: str,
            game_date: datetime,
            outcome: str,
            points_for: int,
            points_against: int,
            horizon_minutes: int = 1440,
        ):
            """
            Create an asset return representing a game outcome.

            Maps NFL game outcomes to the asset_returns schema:
            - realized_return: 1.0 for win, -1.0 for loss
            - price_start/price_end: points (for differential)
            """
            realized_return = 1.0 if outcome == "win" else -1.0

            self.create(
                symbol=team_symbol,
                as_of=game_date,
                horizon_minutes=horizon_minutes,
                realized_return=realized_return,
                price_start=float(points_against),  # Opponent score
                price_end=float(points_for),        # Team score
            )

        def cleanup(self):
            """Delete all created asset returns."""
            if self.created_records:
                with self.conn.cursor() as cur:
                    for symbol, as_of, horizon in self.created_records:
                        cur.execute(
                            """
                            DELETE FROM asset_returns
                            WHERE symbol = %s AND as_of = %s AND horizon_minutes = %s
                            """,
                            (symbol, as_of, horizon)
                        )
                self.conn.commit()
                self.created_records.clear()

    factory = AssetReturnsFactory(db_conn)
    yield factory
    factory.cleanup()


# =============================================================================
# Temporal Assertion Helpers
# =============================================================================

@pytest.fixture
def temporal_assertions():
    """
    Helper functions for temporal correctness assertions.
    """
    class TemporalAssertions:
        @staticmethod
        def assert_strictly_before(dt1: datetime, dt2: datetime, msg: str = ""):
            """Assert dt1 < dt2 (strict inequality)."""
            assert dt1 < dt2, (
                f"{msg}\n"
                f"Expected: {dt1} < {dt2}\n"
                f"Actual: {dt1} >= {dt2} (LOOKAHEAD BIAS!)"
            )

        @staticmethod
        def assert_timezone_aware(dt: datetime, msg: str = ""):
            """Assert datetime has timezone info."""
            assert dt.tzinfo is not None, (
                f"{msg}\n"
                f"Datetime {dt} is timezone-naive (must be UTC)"
            )

        @staticmethod
        def assert_all_before(dts: List[datetime], cutoff: datetime, msg: str = ""):
            """Assert all datetimes are strictly before cutoff."""
            for dt in dts:
                assert dt < cutoff, (
                    f"{msg}\n"
                    f"Found datetime {dt} >= {cutoff} (LOOKAHEAD BIAS!)"
                )

        @staticmethod
        def assert_no_duplicates(items: List, key=None, msg: str = ""):
            """Assert no duplicate items in list."""
            if key:
                seen = set()
                for item in items:
                    k = key(item)
                    assert k not in seen, f"{msg}\nDuplicate found: {k}"
                    seen.add(k)
            else:
                assert len(items) == len(set(items)), f"{msg}\nDuplicates found in list"

    return TemporalAssertions()
