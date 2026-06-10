"""MongoDB index management.

Creates indexes for all collections. Called during app startup or via scripts.
"""
from loguru import logger

from app.db.mongodb import get_database


async def create_indexes() -> None:
    """Create all MongoDB indexes required by the application."""
    db = get_database()
    logger.info("Creating MongoDB indexes on database: {}", db.name)

    # Users collection (Story 1.2)
    # _id is auto-indexed by MongoDB (stores our ULID IDs)
    await db.users.create_index("username", unique=True, name="idx_users_username")
    await db.users.create_index("email", unique=True, name="idx_users_email")
    logger.info("Created indexes: idx_users_username, idx_users_email")

    # Agents collection (Story 2.1)
    await db.agents.create_index("name", unique=True, name="idx_agents_name")
    await db.agents.create_index("status", name="idx_agents_status")
    logger.info("Created indexes: idx_agents_name, idx_agents_status")

    # Models collection (Model management)
    await db.models.create_index(
        "model_id", unique=True, name="idx_models_model_id"
    )
    await db.models.create_index("status", name="idx_models_status")
    logger.info("Created indexes: idx_models_model_id, idx_models_status")

    # Tools collection (Story 5.1 — Skill data model)
    await db.tools.create_index("name", unique=True, name="idx_tools_name")
    await db.tools.create_index("status", name="idx_tools_status")
    await db.tools.create_index("source", name="idx_tools_source")
    await db.tools.create_index("mcp_connection_id", name="idx_tools_mcp_conn_id")
    logger.info("Created indexes: idx_tools_name, idx_tools_status, idx_tools_source, idx_tools_mcp_conn_id")

    # MCP connections collection (Story 5.3 — MCP connection management)
    await db.mcp_connections.create_index("name", unique=True, name="idx_mcp_conn_name")
    await db.mcp_connections.create_index("status", name="idx_mcp_conn_status")
    logger.info("Created indexes: idx_mcp_conn_name, idx_mcp_conn_status")


if __name__ == "__main__":
    import asyncio

    asyncio.run(create_indexes())
