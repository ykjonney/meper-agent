"""Integration test: trigger placeholder race is prevented by the partial
unique index.

This is the regression test for the bug that caused 5 duplicate pending
tasks to be created at 09:00:00. It uses a REAL MongoDB (so the partial
unique index actually enforces uniqueness) and fires N concurrent
placeholder insertions for the same trigger — exactly what the previous
check-then-act code allowed through.

Without the index + DuplicateKeyError handling, all N inserts would
succeed. With the fix, only ONE succeeds; the rest raise DuplicateKeyError.
"""
import asyncio
from datetime import UTC, datetime

import pytest
from pymongo.errors import DuplicateKeyError

pytestmark = pytest.mark.integration

INTEGRATION_DB = "agent_flow_test"
MONGO_URI = "mongodb://localhost:27017"


@pytest.mark.asyncio
async def test_partial_unique_index_blocks_duplicate_placeholder(mongo_client):
    """The partial unique index must reject a 2nd pending placeholder
    for the same trigger_id."""
    db = mongo_client[INTEGRATION_DB]
    col = db["tasks"]

    # Recreate the partial unique index exactly as ensure_indexes does.
    await col.drop_indexes()
    await col.create_index(
        [("trigger_id", 1)],
        unique=True,
        name="uniq_trigger_pending_placeholder",
        partialFilterExpression={"source": "trigger", "status": "pending"},
    )
    await col.delete_many({"trigger_id": "trig_race"})

    now = datetime.now(UTC)
    base = {
        "trigger_id": "trig_race",
        "source": "trigger",
        "status": "pending",
        "scheduled_at": now,
    }

    # First insert succeeds
    await col.insert_one({"_id": "task_a", **base})
    # Second insert for same trigger (still pending) must fail
    with pytest.raises(DuplicateKeyError):
        await col.insert_one({"_id": "task_b", **base})

    # But once task_a moves to running, a NEW pending placeholder is allowed
    # (it leaves the partial index).
    await col.update_one({"_id": "task_a"}, {"$set": {"status": "running"}})
    await col.insert_one({"_id": "task_c", **base})  # succeeds now

    await col.delete_many({"trigger_id": "trig_race"})


@pytest.mark.asyncio
async def test_concurrent_placeholder_creation_only_one_wins(mongo_client):
    """Concurrent insertions for the same trigger: exactly one succeeds,
    the rest get DuplicateKeyError. This reproduces the 5-task race."""
    db = mongo_client[INTEGRATION_DB]
    col = db["tasks"]

    await col.drop_indexes()
    await col.create_index(
        [("trigger_id", 1)],
        unique=True,
        name="uniq_trigger_pending_placeholder",
        partialFilterExpression={"source": "trigger", "status": "pending"},
    )
    await col.delete_many({"trigger_id": "trig_concurrent"})

    now = datetime.now(UTC)
    n = 8  # simulate 8 concurrent "winners" racing to create the placeholder

    async def try_insert(i: int) -> bool:
        try:
            await col.insert_one(
                {
                    "_id": f"task_conc_{i}",
                    "trigger_id": "trig_concurrent",
                    "source": "trigger",
                    "status": "pending",
                    "scheduled_at": now,
                }
            )
            return True
        except DuplicateKeyError:
            return False

    results = await asyncio.gather(*[try_insert(i) for i in range(n)])
    wins = sum(1 for r in results if r)

    assert wins == 1, f"Expected exactly 1 winner, got {wins}: {results}"

    # Confirm only one pending placeholder exists
    count = await col.count_documents(
        {"trigger_id": "trig_concurrent", "status": "pending", "source": "trigger"}
    )
    assert count == 1

    await col.delete_many({"trigger_id": "trig_concurrent"})
