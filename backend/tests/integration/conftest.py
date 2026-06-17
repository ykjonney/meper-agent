"""Pytest fixtures for MongoDB integration tests.

All tests in this directory require a running MongoDB instance
(default: mongodb://localhost:27017). Tests use a dedicated database
``agent_flow_test`` that is wiped clean before each test.
"""
from collections.abc import AsyncGenerator, Generator
from unittest.mock import patch

import pytest
import pytest_asyncio
from app.services.agent_service import AgentService
from app.services.user_service import UserService
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection

INTEGRATION_DB = "agent_flow_test"
MONGO_URI = "mongodb://localhost:27017"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--skip-integration",
        action="store_true",
        default=False,
        help="Skip tests that require a real MongoDB connection",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Skip integration tests when ``--skip-integration`` is passed."""
    if config.getoption("--skip-integration"):
        skip_integration = pytest.mark.skip(reason="Skipped via --skip-integration")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_integration)


@pytest_asyncio.fixture(scope="function")
async def mongo_client() -> AsyncGenerator[AsyncIOMotorClient, None]:
    """Provide a client to the test database."""
    client = AsyncIOMotorClient(MONGO_URI)
    yield client
    client.close()


@pytest_asyncio.fixture
async def users_collection(
    mongo_client: AsyncIOMotorClient,
) -> AsyncGenerator[AsyncIOMotorCollection, None]:
    """Provide a clean users collection before each test."""
    db = mongo_client[INTEGRATION_DB]
    col = db["users"]

    await col.create_index("username", unique=True, name="idx_users_username")
    await col.create_index("email", unique=True, name="idx_users_email")

    await col.delete_many({})

    yield col

    await col.delete_many({})


@pytest.fixture
def mock_collection(
    users_collection: AsyncIOMotorCollection,
) -> Generator[None, None, None]:
    """Patch ``UserService._collection`` to return the test collection."""
    with patch.object(UserService, "_collection", return_value=users_collection):
        yield


@pytest_asyncio.fixture
async def agents_collection(
    mongo_client: AsyncIOMotorClient,
) -> AsyncGenerator[AsyncIOMotorCollection, None]:
    """Provide a clean agents collection before each test."""
    db = mongo_client[INTEGRATION_DB]
    col = db["agents"]

    await col.create_index("name", unique=True, name="idx_agents_name")
    await col.create_index("status", name="idx_agents_status")

    await col.delete_many({})

    yield col

    await col.delete_many({})


@pytest.fixture
def mock_agent_collection(
    agents_collection: AsyncIOMotorCollection,
) -> Generator[None, None, None]:
    """Patch ``AgentService._collection`` to return the test collection."""
    with patch.object(AgentService, "_collection", return_value=agents_collection):
        yield
