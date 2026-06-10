"""Smoke tests for the /api/v1/health endpoint."""
from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    """The health endpoint must return 200 and a status of ok."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_no_auth_required(client: TestClient) -> None:
    """The health endpoint must work without any auth headers."""
    response = client.get("/api/v1/health", headers={})
    assert response.status_code == 200


def test_root_returns_welcome(client: TestClient) -> None:
    """The root endpoint returns a welcome payload pointing to docs."""
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert "message" in body
    assert body["docs"] == "/api/v1/docs"
