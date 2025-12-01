# backend/tests/conftest.py

import os
import sys

import pytest
from fastapi.testclient import TestClient

# Ensure backend is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app


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
