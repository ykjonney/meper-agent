"""Tests for the AppError exception hierarchy."""
import pytest
from app.core.errors import (
    AppError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)


def test_app_error_basic() -> None:
    """AppError stores code, message, status_code, and details correctly."""
    err = AppError(code="AGENT_NOT_FOUND", message="Agent does not exist", status_code=404)
    assert err.code == "AGENT_NOT_FOUND"
    assert err.message == "Agent does not exist"
    assert err.status_code == 404
    assert err.details == {}
    assert str(err) == "Agent does not exist"


def test_app_error_with_details() -> None:
    """AppError accepts a details dict and forwards it."""
    err = AppError(
        code="AGENT_INVALID",
        message="bad",
        status_code=400,
        details={"agent_id": "agent_abc"},
    )
    assert err.details == {"agent_id": "agent_abc"}


def test_not_found_error_default_status() -> None:
    """NotFoundError defaults to status_code 404."""
    err = NotFoundError(code="X_NOT_FOUND", message="x")
    assert err.status_code == 404


def test_unauthorized_error_default_status() -> None:
    """UnauthorizedError defaults to status_code 401."""
    err = UnauthorizedError(code="AUTH_REQUIRED", message="login first")
    assert err.status_code == 401


def test_forbidden_error_default_status() -> None:
    """ForbiddenError defaults to status_code 403."""
    err = ForbiddenError(code="FORBIDDEN", message="no")
    assert err.status_code == 403


def test_validation_error_default_status() -> None:
    """ValidationError defaults to status_code 422."""
    err = ValidationError(code="VALIDATION_FAILED", message="bad input")
    assert err.status_code == 422


def test_app_error_is_exception() -> None:
    """AppError is catchable as a regular Exception."""
    with pytest.raises(Exception):  # noqa: B017 - intentional: testing inheritance
        raise AppError(code="X", message="y")


def test_app_error_can_be_caught_specifically() -> None:
    """AppError is catchable as its own type."""
    with pytest.raises(AppError):
        raise NotFoundError(code="X", message="y")
