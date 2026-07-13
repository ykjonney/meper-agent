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
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


def _configure_structlog() -> None:
    """Route harness structlog logs through loguru for unified formatting."""

    def _loguru_processor(logger, method_name, event_dict):  # noqa: ANN001
        """Final structlog processor: forward to loguru with structured message."""
        event = event_dict.pop("event", method_name)
        # Attach remaining kv pairs as extra for loguru's message
        parts = [f"{k}={v}" for k, v in event_dict.items() if k not in ("level",)]
        msg = event if not parts else f"{event} {' '.join(parts)}"
        logger.opt(depth=6).log(method_name, msg)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
            _loguru_processor,
        ],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.LOG_LEVEL, logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


def setup_logging() -> None:
    """Configure loguru with stdout (concise) and file (JSON, today-only) sinks.

    Also configures structlog (harness) and stdlib logging to route through loguru.
    """
    # Enable LangSmith tracing if API key is configured.
    # Must be set before LangChain/LangGraph import their tracing machinery.
    if settings.LANGSMITH_API_KEY:
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
        os.environ.setdefault("LANGCHAIN_API_KEY", settings.LANGSMITH_API_KEY)
        os.environ.setdefault("LANGCHAIN_PROJECT", settings.LANGSMITH_PROJECT)
        os.environ.setdefault("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")

    logger.remove()

    # Stdout sink — concise but keeps request_id and source location
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
        serialize=settings.LOG_JSON_FORMAT,
        filter=lambda record: "request_id" in record["extra"],
    )

    # Stdout sink for non-request contexts
    logger.add(
        sys.stdout,
        level=settings.LOG_LEVEL,
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <5}</level> | "
            "<magenta>{name}:{function}:{line}</magenta> - "
            "<level>{message}</level>"
        ),
        serialize=settings.LOG_JSON_FORMAT,
        filter=lambda record: "request_id" not in record["extra"],
    )

    # File sink — JSON, only keep today's logs
    logger.add(
        "logs/app.log",
        level=settings.LOG_LEVEL,
        serialize=True,
        rotation="50 MB",
        retention="1 day",
        compression="zip",
    )

    # Route stdlib logging (uvicorn, etc.) through loguru
    logging.basicConfig(handlers=[_LoguruHandler()], level=0, force=True)

    # Route harness structlog through loguru
    _configure_structlog()


__all__ = ["logger", "setup_logging"]
