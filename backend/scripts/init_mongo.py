"""Initialize MongoDB with required users, databases, and indexes.

Run as a one-off before first deployment. Idempotent.
"""
from app.db.indexes import create_indexes
from app.db.mongodb import close_mongodb_client, get_database
from loguru import logger


def main() -> None:
    """Create database, collections (implicit), and indexes."""
    db = get_database()
    logger.info("Initializing MongoDB database: {}", db.name)
    create_indexes()
    close_mongodb_client()
    logger.info("MongoDB initialization complete")


if __name__ == "__main__":
    main()
