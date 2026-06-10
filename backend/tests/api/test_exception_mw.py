"""Tests that AppError raised inside a route becomes a unified error envelope."""
from app.api.middleware.exception_mw import ExceptionMiddleware
from app.core.errors import NotFoundError
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _build_app_with_failing_route() -> FastAPI:
    """Spin up a tiny FastAPI app with one route that raises AppError."""
    app = FastAPI()
    app.add_middleware(ExceptionMiddleware)

    @app.get("/api/v1/_test/notfound")
    def _boom():
        raise NotFoundError(code="TEST_NOT_FOUND", message="thing missing", details={"id": "x_1"})

    @app.get("/api/v1/_test/internal")
    def _boom_internal():
        raise RuntimeError("kaboom")

    return app


def test_app_error_response_envelope() -> None:
    """An AppError is caught and rendered in the unified error envelope."""
    app = _build_app_with_failing_route()
    with TestClient(app) as client:
        response = client.get("/api/v1/_test/notfound")
        assert response.status_code == 404
        body = response.json()
        assert "error" in body
        assert body["error"]["code"] == "TEST_NOT_FOUND"
        assert body["error"]["message"] == "thing missing"
        assert body["error"]["details"] == {"id": "x_1"}
        assert body["error"]["request_id"]
        assert body["error"]["timestamp"]


def test_unhandled_exception_returns_500() -> None:
    """An unhandled exception produces a 500 with code=INTERNAL_ERROR."""
    app = _build_app_with_failing_route()
    with TestClient(app) as client:
        response = client.get("/api/v1/_test/internal")
        assert response.status_code == 500
        body = response.json()
        assert body["error"]["code"] == "INTERNAL_ERROR"
        assert "An unexpected error" in body["error"]["message"]
