"""Trigger CRUD repository — MongoDB persistence layer."""
from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.trigger import Trigger

COLLECTION = "triggers"


class TriggerRepository:
    """MongoDB repository for Trigger documents."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db

    def _collection(self):
        return self._db[COLLECTION]

    async def ensure_indexes(self) -> None:
        """Create required indexes (idempotent)."""
        # Same user can have multiple triggers for the same workflow
        await self._collection().create_index("workflow_id")
        await self._collection().create_index("user_id")

        # ── tasks collection: partial unique index on trigger placeholder ──
        # Guarantees at most ONE pending placeholder Task per trigger.
        # When a task transitions pending → running, it automatically leaves
        # the partial index (status no longer matches) so the *next* trigger
        # cycle can insert a fresh placeholder. Terminal tasks are never
        # indexed, so history accumulates without limit.
        # This is the DB-level guard against the race condition where
        # concurrent schedule_next() calls each saw "no placeholder exists"
        # and each inserted one.
        await self._db["tasks"].create_index(
            [("trigger_id", 1)],
            unique=True,
            name="uniq_trigger_pending_placeholder",
            partialFilterExpression={
                "source": "trigger",
                "status": "pending",
            },
        )

    async def insert(self, trigger: Trigger) -> Trigger:
        """Insert a new trigger and return it."""
        doc = trigger.model_dump(by_alias=True)
        await self._collection().insert_one(doc)
        return trigger

    async def find_by_id(self, trigger_id: str) -> Trigger | None:
        """Find a trigger by its ID."""
        doc = await self._collection().find_one({"_id": trigger_id})
        if doc is None:
            return None
        doc["_id"] = doc.pop("_id")  # already correct key
        return Trigger(**doc)

    async def find_by_user_and_workflow(
        self, user_id: str, workflow_id: str
    ) -> Trigger | None:
        """Find the unique trigger for a (user, workflow) pair."""
        doc = await self._collection().find_one(
            {"user_id": user_id, "workflow_id": workflow_id}
        )
        if doc is None:
            return None
        return Trigger(**doc)

    async def update(self, trigger_id: str, **fields) -> Trigger | None:
        """Update a trigger with the given fields and return the updated doc."""
        result = await self._collection().find_one_and_update(
            {"_id": trigger_id},
            {"$set": fields},
            return_document=True,
        )
        if result is None:
            return None
        return Trigger(**result)

    async def delete(self, trigger_id: str) -> bool:
        """Delete a trigger. Returns True if a document was deleted."""
        result = await self._collection().delete_one({"_id": trigger_id})
        return result.deleted_count > 0

    async def find_enabled(self) -> list[Trigger]:
        """Return all enabled triggers (used for rescan on startup)."""
        cursor = self._collection().find({"enabled": True})
        triggers: list[Trigger] = []
        async for doc in cursor:
            triggers.append(Trigger(**doc))
        return triggers
