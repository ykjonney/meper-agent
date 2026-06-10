"""Tests that verify the X-Request-ID header is present on every response."""
from fastapi.testclient import TestClient


def test_response_includes_request_id_header(client: TestClient) -> None:
    """Every response must carry an X-Request-ID header."""
    response = client.get("/api/v1/health")
    assert "X-Request-ID" in response.headers
    # 8-char hex UUID short form
    assert len(response.headers["X-Request-ID"]) >= 8


def test_request_id_propagated_when_provided(client: TestClient) -> None:
    """If the client supplies X-Request-ID, the server reuses it."""
    rid = "deadbeef"
    response = client.get("/api/v1/health", headers={"X-Request-ID": rid})
    assert response.headers["X-Request-ID"] == rid


def test_request_id_generated_when_absent(client: TestClient) -> None:
    """Without an inbound X-Request-ID, a fresh one is generated."""
    response = client.get("/api/v1/health")
    rid = response.headers["X-Request-ID"]
    assert rid and rid != "-"
