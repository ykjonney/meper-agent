"""loguru-based structured logging with file rotation."""
import sys

from loguru import logger

from app.core.config import settings


def setup_logging() -> None:
    """Configure loguru with stdout (concise) and file (JSON, today-only) sinks."""
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


__all__ = ["logger", "setup_logging"]
