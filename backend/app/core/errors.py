"""Application business exception hierarchy.

All business errors MUST inherit from AppError. Never raise bare `Exception`.
"""
from typing import Any


class AppError(Exception):
    """Base business exception.

    Args:
        code: Business error code, e.g. "AGENT_NOT_FOUND". Format: {MODULE}_{ACTION}_{REASON}.
        message: User-visible error message.
        status_code: HTTP status code (default 400).
        details: Optional dict with additional context for the client.
    """

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


# Common business error subclasses for convenience
class NotFoundError(AppError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(code=code, message=message, status_code=404, details=details)


class UnauthorizedError(AppError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(code=code, message=message, status_code=401, details=details)


class ForbiddenError(AppError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(code=code, message=message, status_code=403, details=details)


class ValidationError(AppError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(code=code, message=message, status_code=422, details=details)


class ConflictError(AppError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(code=code, message=message, status_code=409, details=details)
