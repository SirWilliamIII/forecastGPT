"""
Test Suite 2: Forecast Snapshot Integrity

Tests for forecast snapshot storage and retrieval.
When we backfill historical forecasts, they should be stored in a way that:
1. Prevents duplicates
2. Maintains referential integrity
3. Uses timezone-aware timestamps
4. Can be queried efficiently for timeline views

This suite assumes a forecast_snapshots table with schema:
    CREATE TABLE forecast_snapshots (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        symbol TEXT NOT NULL,
        forecast_type TEXT NOT NULL,  -- 'baseline', 'event_conditioned', 'nfl_event'
        timestamp TIMESTAMPTZ NOT NULL,
        event_id UUID REFERENCES events(id) ON DELETE CASCADE,

        -- Forecast outputs
        win_probability FLOAT,
        expected_return FLOAT,
        confidence FLOAT,
        sample_size INT,

        -- Metadata
        created_at TIMESTAMPTZ DEFAULT NOW(),
        metadata JSONB,

        UNIQUE(symbol, forecast_type, timestamp, event_id)
    );

Note: If this table doesn't exist yet, these tests document the required behavior.
"""

import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from typing import Optional

from tests.conftest import TEAM_SYMBOL


# =============================================================================
# Snapshot Table Schema (for reference)
# =============================================================================

# This documents the expected schema. Tests will skip if table doesn't exist yet.

SNAPSHOT_TABLE_EXISTS_QUERY = """
SELECT EXISTS (
    SELECT FROM information_schema.tables
    WHERE table_schema = 'public'
    AND table_name = 'forecast_snapshots'
);
"""


def table_exists(db_conn, table_name: str) -> bool:
    """Helper to check if a table exists."""
    with db_conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = %s
            )
            """,
            (table_name,)
        )
        return cur.fetchone()[0]


# =============================================================================
# Helper Functions
# =============================================================================

def insert_snapshot(
    db_conn,
    symbol: str,
    forecast_type: str,
    timestamp: datetime,
    event_id: Optional[uuid4] = None,
    win_probability: Optional[float] = None,
    expected_return: Optional[float] = None,
    confidence: float = 0.5,
    sample_size: int = 10,
    metadata: Optional[dict] = None,
) -> uuid4:
    """Insert a forecast snapshot and return its ID."""
    if timestamp.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")

    snapshot_id = uuid4()

    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO forecast_snapshots (
                id, symbol, forecast_type, timestamp, event_id,
                win_probability, expected_return, confidence, sample_size, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                snapshot_id, symbol, forecast_type, timestamp, event_id,
                win_probability, expected_return, confidence, sample_size, metadata
            )
        )

    db_conn.commit()
    return snapshot_id


# =============================================================================
# Test 1: Unique Constraints
# =============================================================================

class TestSnapshotUniqueConstraints:
    """
    Verify that duplicate snapshots are prevented by unique constraints.
    """

    @pytest.fixture(autouse=True)
    def skip_if_table_missing(self, db_conn):
        """Skip tests if forecast_snapshots table doesn't exist yet."""
        if not table_exists(db_conn, 'forecast_snapshots'):
            pytest.skip("forecast_snapshots table not implemented yet")

    def test_prevents_duplicate_snapshots(self, db_conn, clean_test_data, event_factory, reference_time):
        """
        CRITICAL: Prevent duplicate snapshots with same (symbol, forecast_type, timestamp, event_id).

        Without this constraint, backfilling could create duplicate entries.
        """
        event_id = event_factory.create(
            timestamp=reference_time - timedelta(days=1),
            title="Test event for snapshot",
        )

        # Insert first snapshot
        snapshot_1 = insert_snapshot(
            db_conn=db_conn,
            symbol=TEAM_SYMBOL,
            forecast_type="event_conditioned",
            timestamp=reference_time,
            event_id=event_id,
            win_probability=0.65,
            confidence=0.8,
        )

        # Try to insert duplicate (should fail with unique constraint violation)
        with pytest.raises(Exception) as exc_info:
            insert_snapshot(
                db_conn=db_conn,
                symbol=TEAM_SYMBOL,
                forecast_type="event_conditioned",
                timestamp=reference_time,
                event_id=event_id,
                win_probability=0.70,  # Different value
                confidence=0.9,  # Different value
            )

        # Verify it's a unique constraint error
        assert "unique" in str(exc_info.value).lower() or "duplicate" in str(exc_info.value).lower(), \
            f"Expected unique constraint violation, got: {exc_info.value}"

    def test_allows_different_forecast_types_same_time(
        self, db_conn, clean_test_data, event_factory, reference_time
    ):
        """
        Allow multiple forecast types for the same (symbol, timestamp, event).

        Example: Both 'baseline' and 'event_conditioned' forecasts at the same time.
        """
        event_id = event_factory.create(
            timestamp=reference_time - timedelta(days=1),
            title="Test event",
        )

        # Insert baseline forecast
        snapshot_baseline = insert_snapshot(
            db_conn=db_conn,
            symbol=TEAM_SYMBOL,
            forecast_type="baseline",
            timestamp=reference_time,
            event_id=None,  # Baseline doesn't use event
            expected_return=0.05,
        )

        # Insert event-conditioned forecast (same time, different type)
        snapshot_event = insert_snapshot(
            db_conn=db_conn,
            symbol=TEAM_SYMBOL,
            forecast_type="event_conditioned",
            timestamp=reference_time,
            event_id=event_id,
            expected_return=0.08,
        )

        # Both should succeed
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT forecast_type
                FROM forecast_snapshots
                WHERE symbol = %s AND timestamp = %s
                ORDER BY forecast_type
                """,
                (TEAM_SYMBOL, reference_time)
            )
            results = cur.fetchall()

        forecast_types = [r['forecast_type'] for r in results]

        assert len(forecast_types) == 2
        assert 'baseline' in forecast_types
        assert 'event_conditioned' in forecast_types

    def test_allows_different_events_same_time(
        self, db_conn, clean_test_data, event_factory, reference_time
    ):
        """
        Allow multiple event-conditioned forecasts at the same time (different events).
        """
        event_1 = event_factory.create(
            timestamp=reference_time - timedelta(days=2),
            title="Event 1",
        )

        event_2 = event_factory.create(
            timestamp=reference_time - timedelta(days=1),
            title="Event 2",
        )

        # Insert forecasts for both events at same timestamp
        snapshot_1 = insert_snapshot(
            db_conn=db_conn,
            symbol=TEAM_SYMBOL,
            forecast_type="event_conditioned",
            timestamp=reference_time,
            event_id=event_1,
            win_probability=0.60,
        )

        snapshot_2 = insert_snapshot(
            db_conn=db_conn,
            symbol=TEAM_SYMBOL,
            forecast_type="event_conditioned",
            timestamp=reference_time,
            event_id=event_2,
            win_probability=0.75,
        )

        # Both should succeed
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT event_id, win_probability
                FROM forecast_snapshots
                WHERE symbol = %s
                  AND forecast_type = 'event_conditioned'
                  AND timestamp = %s
                ORDER BY win_probability
                """,
                (TEAM_SYMBOL, reference_time)
            )
            results = cur.fetchall()

        assert len(results) == 2
        assert str(results[0]['event_id']) == str(event_1)
        assert str(results[1]['event_id']) == str(event_2)


# =============================================================================
# Test 2: Timezone Awareness
# =============================================================================

class TestSnapshotTimezoneCorrectness:
    """
    Verify all snapshot timestamps are timezone-aware UTC.
    """

    @pytest.fixture(autouse=True)
    def skip_if_table_missing(self, db_conn):
        if not table_exists(db_conn, 'forecast_snapshots'):
            pytest.skip("forecast_snapshots table not implemented yet")

    def test_snapshot_timestamps_are_utc(
        self, db_conn, clean_test_data, reference_time, temporal_assertions
    ):
        """
        All snapshot timestamps must be stored as TIMESTAMPTZ (timezone-aware UTC).
        """
        snapshot_id = insert_snapshot(
            db_conn=db_conn,
            symbol=TEAM_SYMBOL,
            forecast_type="baseline",
            timestamp=reference_time,
            expected_return=0.05,
        )

        # Fetch from database
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT timestamp, created_at FROM forecast_snapshots WHERE id = %s",
                (snapshot_id,)
            )
            row = cur.fetchone()

        # ASSERTIONS
        temporal_assertions.assert_timezone_aware(
            row['timestamp'],
            msg="Snapshot timestamp is timezone-naive"
        )

        temporal_assertions.assert_timezone_aware(
            row['created_at'],
            msg="Snapshot created_at is timezone-naive"
        )

        assert row['timestamp'].tzinfo == timezone.utc
        assert row['created_at'].tzinfo == timezone.utc

    def test_rejects_naive_timestamps(self, db_conn, clean_test_data):
        """
        Verify that inserting naive timestamps fails or gets converted to UTC.

        PostgreSQL TIMESTAMPTZ should handle this, but we test it.
        """
        naive_time = datetime(2025, 1, 15, 12, 0, 0)  # No tzinfo

        # This should either:
        # 1. Raise an error (strict mode)
        # 2. Auto-convert to UTC (permissive mode)

        # Our helper function enforces awareness, so this will raise
        with pytest.raises(ValueError, match="timezone-aware"):
            insert_snapshot(
                db_conn=db_conn,
                symbol=TEAM_SYMBOL,
                forecast_type="baseline",
                timestamp=naive_time,
                expected_return=0.05,
            )


# =============================================================================
# Test 3: Foreign Key Integrity
# =============================================================================

class TestSnapshotReferentialIntegrity:
    """
    Test foreign key relationships and cascade behavior.
    """

    @pytest.fixture(autouse=True)
    def skip_if_table_missing(self, db_conn):
        if not table_exists(db_conn, 'forecast_snapshots'):
            pytest.skip("forecast_snapshots table not implemented yet")

    def test_event_fk_cascade_on_delete(
        self, db_conn, clean_test_data, event_factory, reference_time
    ):
        """
        When an event is deleted, associated snapshots should cascade delete.

        This prevents orphaned forecast snapshots.
        """
        event_id = event_factory.create(
            timestamp=reference_time - timedelta(days=1),
            title="Event to be deleted",
        )

        # Create snapshot referencing this event
        snapshot_id = insert_snapshot(
            db_conn=db_conn,
            symbol=TEAM_SYMBOL,
            forecast_type="event_conditioned",
            timestamp=reference_time,
            event_id=event_id,
            win_probability=0.70,
        )

        # Verify snapshot exists
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM forecast_snapshots WHERE id = %s",
                (snapshot_id,)
            )
            assert cur.fetchone() is not None

        # Delete the event
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM events WHERE id = %s", (event_id,))
        db_conn.commit()

        # Verify snapshot was cascade deleted
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM forecast_snapshots WHERE id = %s",
                (snapshot_id,)
            )
            result = cur.fetchone()

        assert result is None, \
            "Snapshot should have been cascade deleted when event was deleted"

    def test_baseline_snapshots_no_event_fk(
        self, db_conn, clean_test_data, reference_time
    ):
        """
        Baseline forecasts don't reference events (event_id NULL).
        """
        snapshot_id = insert_snapshot(
            db_conn=db_conn,
            symbol=TEAM_SYMBOL,
            forecast_type="baseline",
            timestamp=reference_time,
            event_id=None,  # No event for baseline
            expected_return=0.05,
        )

        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT event_id FROM forecast_snapshots WHERE id = %s",
                (snapshot_id,)
            )
            row = cur.fetchone()

        assert row['event_id'] is None


# =============================================================================
# Test 4: Query Performance
# =============================================================================

class TestSnapshotQueryPerformance:
    """
    Test that common queries are efficient.
    """

    @pytest.fixture(autouse=True)
    def skip_if_table_missing(self, db_conn):
        if not table_exists(db_conn, 'forecast_snapshots'):
            pytest.skip("forecast_snapshots table not implemented yet")

    def test_timeline_query_by_symbol_and_date_range(
        self, db_conn, clean_test_data, reference_time, event_factory
    ):
        """
        Test efficient querying of snapshots for timeline view.

        Common query: Get all forecasts for a symbol in a date range.
        """
        # Create events
        events = [
            event_factory.create(
                timestamp=reference_time - timedelta(days=d),
                title=f"Event {d} days ago",
            )
            for d in range(1, 31)
        ]

        # Create snapshots for 30 days
        for i, event_id in enumerate(events):
            insert_snapshot(
                db_conn=db_conn,
                symbol=TEAM_SYMBOL,
                forecast_type="event_conditioned",
                timestamp=reference_time - timedelta(days=i),
                event_id=event_id,
                win_probability=0.5 + (i % 10) * 0.05,
            )

        # Query for last 7 days
        start_date = reference_time - timedelta(days=7)

        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT timestamp, win_probability, event_id
                FROM forecast_snapshots
                WHERE symbol = %s
                  AND timestamp >= %s
                  AND timestamp <= %s
                ORDER BY timestamp DESC
                """,
                (TEAM_SYMBOL, start_date, reference_time)
            )
            results = cur.fetchall()

        # Should return 7 or 8 snapshots (depending on boundary)
        assert len(results) >= 7, f"Expected at least 7 results, got {len(results)}"

        # Verify chronological order
        timestamps = [r['timestamp'] for r in results]
        assert timestamps == sorted(timestamps, reverse=True), \
            "Results should be in descending chronological order"

    def test_latest_snapshot_per_symbol_query(
        self, db_conn, clean_test_data, reference_time
    ):
        """
        Test efficient query for latest forecast per symbol.

        Common use case: Dashboard showing current forecasts.
        """
        symbols = [f"NFL:TEAM_{i}" for i in range(5)]

        # Create snapshots at different times for each symbol
        for symbol in symbols:
            for days_ago in [7, 3, 1]:
                insert_snapshot(
                    db_conn=db_conn,
                    symbol=symbol,
                    forecast_type="baseline",
                    timestamp=reference_time - timedelta(days=days_ago),
                    expected_return=0.05,
                )

        # Query for latest snapshot per symbol
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (symbol)
                    symbol, timestamp, expected_return
                FROM forecast_snapshots
                WHERE forecast_type = 'baseline'
                ORDER BY symbol, timestamp DESC
                """
            )
            results = cur.fetchall()

        # Should return 5 results (one per symbol)
        assert len(results) == 5

        # Each should be from 1 day ago (most recent)
        expected_time = reference_time - timedelta(days=1)
        for row in results:
            assert row['timestamp'] == expected_time


# =============================================================================
# Test 5: Metadata Storage
# =============================================================================

class TestSnapshotMetadataStorage:
    """
    Test JSONB metadata field for additional forecast information.
    """

    @pytest.fixture(autouse=True)
    def skip_if_table_missing(self, db_conn):
        if not table_exists(db_conn, 'forecast_snapshots'):
            pytest.skip("forecast_snapshots table not implemented yet")

    def test_store_and_retrieve_metadata(
        self, db_conn, clean_test_data, reference_time
    ):
        """
        Verify JSONB metadata can store arbitrary forecast context.
        """
        metadata = {
            "model_version": "v2.0",
            "features_used": ["win_pct", "point_diff", "home_advantage"],
            "training_samples": 850,
            "similar_events_count": 15,
            "lookback_days": 365,
        }

        snapshot_id = insert_snapshot(
            db_conn=db_conn,
            symbol=TEAM_SYMBOL,
            forecast_type="nfl_event",
            timestamp=reference_time,
            win_probability=0.68,
            metadata=metadata,
        )

        # Retrieve and verify
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT metadata FROM forecast_snapshots WHERE id = %s",
                (snapshot_id,)
            )
            row = cur.fetchone()

        retrieved_metadata = row['metadata']

        assert retrieved_metadata == metadata
        assert retrieved_metadata['model_version'] == "v2.0"
        assert retrieved_metadata['training_samples'] == 850

    def test_query_by_metadata_field(
        self, db_conn, clean_test_data, reference_time
    ):
        """
        Test JSONB querying capabilities (find forecasts by metadata).
        """
        # Create snapshots with different model versions
        for i, version in enumerate(["v1.0", "v2.0", "v2.0", "v3.0"]):
            insert_snapshot(
                db_conn=db_conn,
                symbol=TEAM_SYMBOL,
                forecast_type="baseline",
                timestamp=reference_time - timedelta(days=i),
                expected_return=0.05,
                metadata={"model_version": version},
            )

        # Query for v2.0 forecasts only
        with db_conn.cursor() as cur:
            cur.execute(
                """
                SELECT timestamp
                FROM forecast_snapshots
                WHERE symbol = %s
                  AND metadata->>'model_version' = 'v2.0'
                ORDER BY timestamp DESC
                """,
                (TEAM_SYMBOL,)
            )
            results = cur.fetchall()

        assert len(results) == 2, f"Expected 2 v2.0 forecasts, got {len(results)}"
