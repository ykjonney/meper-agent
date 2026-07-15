"""loguru-based structured logging with file rotation.

Also configures structlog (used by the harness package) to route through loguru,
so all logs share a unified format and the same file sink.
"""
import logging
import os
import sys

import structlog
from loguru import logger

from app.core.config import settings


class _LoguruHandler(logging.Handler):
    """Bridge stdlib logging → loguru so third-party libs (uvicorn, etc.) share one sink."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str = logger.level(record.levelname).name
        except ValueError:
            level = str(record.levelno)
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


def _configure_structlog() -> None:
    """Route harness structlog logs through loguru for unified formatting."""

    def _loguru_processor(_slog_logger, method_name, event_dict):  # noqa: ANN001
        """Final structlog processor: forward to loguru with structured message."""
        event = event_dict.pop("event", method_name)
        # Attach remaining kv pairs as extra for loguru's message
        parts = [f"{k}={v}" for k, v in event_dict.items() if k not in ("level",)]
        msg = event if not parts else f"{event} {' '.join(parts)}"
        # Use loguru's global logger, not the structlog PrintLogger
        level = method_name.upper() if method_name != "warn" else "WARNING"
        logger.opt(depth=6, capture=False).log(level, msg)
        # structlog requires the last processor to return a value
        return msg

    class _NilLogger:
        """No-op logger factory — actual output is done by _loguru_processor."""
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __getattr__(self, _name: str):
            return lambda *a, **kw: None

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            _loguru_processor,
        ],
        logger_factory=_NilLogger,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.LOG_LEVEL, logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


def setup_logging() -> None:
    """Configure loguru with stdout (concise) and file (JSON) sinks.

    - stdout: human-readable in dev, JSON in production (auto-detected from
      ``APP_ENV`` or explicitly via ``LOG_JSON_FORMAT``).
    - file: always JSON (``logs/app.log``), 50 MB rotation, 7-day retention.
    - structlog (harness) and stdlib logging are routed through loguru.
    """
    # Enable LangSmith tracing if API key is configured.
    # Must be set before LangChain/LangGraph import their tracing machinery.
    if settings.LANGSMITH_API_KEY:
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
        os.environ.setdefault("LANGCHAIN_API_KEY", settings.LANGSMITH_API_KEY)
        os.environ.setdefault("LANGCHAIN_PROJECT", settings.LANGSMITH_PROJECT)
        os.environ.setdefault("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")

    logger.remove()

    # In production (or when explicitly requested), stdout emits JSON for
    # log aggregation systems (ELK / Loki).  In dev, use human-readable color.
    use_json = settings.LOG_JSON_FORMAT or settings.APP_ENV == "production"

    if use_json:
        # JSON stdout — single sink covers both request and non-request logs.
        logger.add(
            sys.stdout,
            level=settings.LOG_LEVEL,
            serialize=True,
        )
    else:
        # Human-readable stdout — split by request_id presence for clean columns.
        logger.add(
            sys.stdout,
            level=settings.LOG_LEVEL,
            format=(
                "<green>{time:HH:mm:ss}</green> | "
                "<level>{level: <5}</level> | "
                "<cyan>{extra[request_id]}</cyan> | "
                "<magenta>{name}:{function}:{line}</magenta> - "
                "<level>{message}</level>"
            ),
            filter=lambda record: "request_id" in record["extra"],
        )
        logger.add(
            sys.stdout,
            level=settings.LOG_LEVEL,
            format=(
                "<green>{time:HH:mm:ss}</green> | "
                "<level>{level: <5}</level> | "
                "<magenta>{name}:{function}:{line}</magenta> - "
                "<level>{message}</level>"
            ),
            filter=lambda record: "request_id" not in record["extra"],
        )

    # File sink — JSON, 7-day retention for production debugging window.
    logger.add(
        "logs/app.log",
        level=settings.LOG_LEVEL,
        serialize=True,
        rotation="50 MB",
        retention="7 days",
        compression="zip",
    )

    # Route stdlib logging (uvicorn, etc.) through loguru
    logging.basicConfig(handlers=[_LoguruHandler()], level=0, force=True)

    # Route harness structlog through loguru
    _configure_structlog()


__all__ = ["logger", "setup_logging"]
