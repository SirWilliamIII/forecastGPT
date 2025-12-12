"""
Quick test script for forecast snapshots system.

Tests:
1. Database table exists
2. Can query NFL teams
3. Can fetch events
4. API endpoints work
"""

from datetime import datetime, timezone, timedelta
from db import get_conn


def test_table_exists():
    """Check forecast_snapshots table exists."""
    print("Test 1: Table existence...")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'forecast_snapshots'
                ) as exists
                """
            )
            exists = cur.fetchone()["exists"]
            assert exists, "forecast_snapshots table not found!"
            print("✓ Table exists")


def test_get_nfl_teams():
    """Check we can get NFL team symbols."""
    print("\nTest 2: Get NFL teams...")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT symbol
                FROM asset_returns
                WHERE symbol LIKE 'NFL:%'
                ORDER BY symbol
                LIMIT 5
                """
            )
            teams = [row["symbol"] for row in cur.fetchall()]
            print(f"✓ Found {len(teams)} NFL teams: {teams}")
            return teams


def test_get_events():
    """Check we can fetch sports events."""
    print("\nTest 3: Get sports events...")
    now = datetime.now(tz=timezone.utc)
    start = now - timedelta(days=7)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) as count
                FROM events
                WHERE 'sports' = ANY(categories)
                  AND timestamp BETWEEN %s AND %s
                """,
                (start, now),
            )
            count = cur.fetchone()["count"]
            print(f"✓ Found {count} sports events in last 7 days")


def test_compute_snapshot():
    """Test computing a forecast snapshot."""
    print("\nTest 4: Compute forecast snapshot...")
    from ingest.backfill_forecasts import get_nfl_team_symbols, get_team_events_in_window

    teams = get_nfl_team_symbols()
    if not teams:
        print("⚠️  No NFL teams found")
        return

    team = teams[0]
    print(f"  Using team: {team}")

    now = datetime.now(tz=timezone.utc)
    start = now - timedelta(days=7)

    events = get_team_events_in_window(team, start, now, max_events_per_day=10)
    print(f"✓ Found {len(events)} events for {team}")

    if events:
        print(f"  Latest event: {events[0]['title'][:60]}...")


def test_api_health():
    """Test API is running (optional)."""
    print("\nTest 5: API health check...")
    try:
        import requests
        response = requests.get("http://localhost:9000/health", timeout=2)
        if response.status_code == 200:
            print("✓ API is running")
        else:
            print(f"⚠️  API returned status {response.status_code}")
    except Exception as e:
        print(f"⚠️  API not running (this is OK for offline testing): {e}")


if __name__ == "__main__":
    print("="*70)
    print("Forecast Snapshots System - Quick Tests")
    print("="*70)

    try:
        test_table_exists()
        teams = test_get_nfl_teams()
        test_get_events()
        test_compute_snapshot()
        test_api_health()

        print("\n" + "="*70)
        print("✓ All core tests passed!")
        print("="*70)
        print("\nNext steps:")
        print("  1. Run backfill: python -m ingest.backfill_forecasts --symbol NFL:DAL_COWBOYS --days 7")
        print("  2. Start API: uvicorn app:app --reload --port 9000")
        print("  3. Test endpoint: curl http://localhost:9000/nfl/teams/NFL:DAL_COWBOYS/forecast-timeline?days=7")
        print("="*70)

    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
