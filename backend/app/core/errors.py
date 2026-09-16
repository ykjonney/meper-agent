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


class SessionBudgetExceededError(AppError):
    """会话累计 token 预算耗尽（TokenBudgetGuard Block）。

    guard 的 Block 不抛异常——LangGraph 分支静默终止、state["error"] 携带
    原因。引擎入口把它映射为该类型化异常，让调用方能感知并自动轮换会话
    （IM 渠道开新 session 重试），而不是拿到空输出。
    """

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            code="SESSION_BUDGET_EXCEEDED", message=message,
            status_code=429, details=details,
        )


class ConflictError(AppError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(code=code, message=message, status_code=409, details=details)
