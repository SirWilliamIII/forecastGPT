# backend/tests/test_api.py

"""
Smoke tests for the BloombergGPT API.

These tests verify:
- Health endpoint works
- Event endpoints return expected shapes
- Forecast endpoints return expected shapes

Note: Some tests require a running database with data.
Use @pytest.mark.integration for those.
"""

import pytest


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    def test_health_returns_200(self, client):
        """Health endpoint should return 200."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_response_shape(self, client):
        """Health response should have expected fields."""
        response = client.get("/health")
        data = response.json()

        assert "status" in data
        assert "database" in data
        assert "pgvector" in data
        assert data["status"] in ("healthy", "unhealthy")


class TestEventsEndpoints:
    """Tests for /events endpoints."""

    def test_recent_events_returns_200(self, client):
        """Recent events endpoint should return 200."""
        response = client.get("/events/recent")
        assert response.status_code == 200

    def test_recent_events_returns_list(self, client):
        """Recent events should return a list."""
        response = client.get("/events/recent")
        data = response.json()
        assert isinstance(data, list)

    def test_recent_events_respects_limit(self, client):
        """Recent events should respect limit parameter."""
        response = client.get("/events/recent?limit=5")
        data = response.json()
        assert len(data) <= 5

    def test_recent_events_with_source_filter(self, client):
        """Recent events should accept source filter."""
        response = client.get("/events/recent?source=wired_ai")
        assert response.status_code == 200


class TestForecastEndpoints:
    """Tests for /forecast endpoints."""

    def test_asset_forecast_returns_200(self, client):
        """Asset forecast should return 200 (even with no data)."""
        response = client.get("/forecast/asset?symbol=BTC-USD")
        assert response.status_code == 200

    def test_asset_forecast_response_shape(self, client):
        """Asset forecast should have expected fields."""
        response = client.get("/forecast/asset?symbol=BTC-USD")
        data = response.json()

        expected_fields = [
            "symbol",
            "as_of",
            "horizon_minutes",
            "expected_return",
            "direction",
            "confidence",
            "lookback_days",
            "n_points",
            "mean_return",
            "vol_return",
            "features",
        ]

        for field in expected_fields:
            assert field in data, f"Missing field: {field}"

    def test_asset_forecast_custom_params(self, client):
        """Asset forecast should accept custom parameters."""
        response = client.get(
            "/forecast/asset?symbol=ETH-USD&horizon_minutes=60&lookback_days=30"
        )
        data = response.json()

        assert data["symbol"] == "ETH-USD"
        assert data["horizon_minutes"] == 60
        assert data["lookback_days"] == 30


@pytest.mark.integration
class TestIntegrationWithData:
    """
    Integration tests that require a running database with data.
    
    Run with: pytest -m integration
    """

    def test_event_creation_and_retrieval(self, client, sample_event):
        """Test creating an event and fetching it."""
        # This would require mocking embeddings or having OPENAI_API_KEY set
        pass

    def test_event_similarity_search(self, client):
        """Test semantic similarity search."""
        # Requires existing events in DB
        pass

    def test_event_forecast(self, client):
        """Test event-conditioned forecast."""
        # Requires existing events + asset_returns
        pass
