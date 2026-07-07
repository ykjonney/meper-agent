"""Trigger scheduler service for managing Celery Beat dynamic registration."""
from typing import Any

from loguru import logger

from app.db.mongodb import get_database


class TriggerSchedulerService:
    """Scheduled trigger scheduler service.

    Manages dynamic registration of workflow triggers with Celery Beat.
    """

    def __init__(self) -> None:
        self._workflows: dict[str, dict[str, Any]] = {}
        self._started: bool = False

    async def start(self) -> None:
        """Initialize scheduler on service startup."""
        if self._started:
            logger.warning("trigger_scheduler_already_started")
            return

        self._started = True
        logger.info("trigger_scheduler_started")

        # Scan all enabled trigger configs
        await self._load_and_register_triggers()

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._started = False
        self._workflows.clear()
        logger.info("trigger_scheduler_stopped")

    async def _load_and_register_triggers(self) -> None:
        """Scan and register all enabled trigger tasks."""
        db = get_database()
        cursor = db["workflows"].find({
            "trigger_config.enabled": True
        })

        async for doc in cursor:
            workflow_id = doc["_id"]
            self._workflows[workflow_id] = doc
            logger.info(
                "trigger_registered",
                workflow_id=workflow_id,
                trigger_type=doc.get("trigger_config", {}).get("type"),
            )

    async def register_trigger(self, workflow_id: str) -> None:
        """Register a single trigger task."""
        db = get_database()
        doc = await db["workflows"].find_one({"_id": workflow_id})
        if doc and doc.get("trigger_config", {}).get("enabled"):
            self._workflows[workflow_id] = doc
            logger.info("trigger_registered", workflow_id=workflow_id)

    async def unregister_trigger(self, workflow_id: str) -> None:
        """Remove a trigger task."""
        if workflow_id in self._workflows:
            del self._workflows[workflow_id]
            logger.info("trigger_unregistered", workflow_id=workflow_id)

    async def update_trigger(self, workflow_id: str) -> None:
        """Update trigger config (unregister then register)."""
        await self.unregister_trigger(workflow_id)
        await self.register_trigger(workflow_id)


# Module-level singleton
_scheduler: TriggerSchedulerService | None = None


def get_trigger_scheduler() -> TriggerSchedulerService:
    """Get the trigger scheduler singleton."""
    global _scheduler
    if _scheduler is None:
        _scheduler = TriggerSchedulerService()
    return _scheduler
