"""Shared pytest fixtures for the backend test suite."""
import os

# Ensure tests don't require a real DB / Redis during import-time config load
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-prod")

import pytest
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    """A FastAPI TestClient that bypasses real network IO."""
    return TestClient(app)
