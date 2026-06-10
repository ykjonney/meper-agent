"""loguru-based structured logging with file rotation."""
import sys

from loguru import logger

from app.core.config import settings


def setup_logging() -> None:
    """Configure loguru with stdout (colorized) and file (JSON) sinks."""
    logger.remove()

    # Stdout sink - human-readable for dev, JSON for prod
    logger.add(
        sys.stdout,
        level=settings.LOG_LEVEL,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{extra[request_id]}</cyan> | "
            "<magenta>{name}:{function}:{line}</magenta> - "
            "<level>{message}</level>"
        ),
        serialize=settings.LOG_JSON_FORMAT,
        filter=lambda record: "request_id" in record["extra"],
    )

    # Stdout sink for non-request contexts (CLI, background tasks)
    logger.add(
        sys.stdout,
        level=settings.LOG_LEVEL,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<magenta>{name}:{function}:{line}</magenta> - "
            "<level>{message}</level>"
        ),
        serialize=settings.LOG_JSON_FORMAT,
        filter=lambda record: "request_id" not in record["extra"],
    )

    # File sink - always JSON for log aggregation
    logger.add(
        "logs/app.log",
        level=settings.LOG_LEVEL,
        serialize=True,
        rotation="100 MB",
        retention="30 days",
        compression="zip",
    )


__all__ = ["logger", "setup_logging"]
