"""Tests for TriggerSchedulerService."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.trigger_scheduler_service import TriggerSchedulerService


async def _async_iter(items):
    """Helper: async iterator over a list of items."""
    for item in items:
        yield item


@pytest.fixture
def service() -> TriggerSchedulerService:
    """Return a fresh TriggerSchedulerService instance."""
    return TriggerSchedulerService()


def _make_mock_db(find_result=None, find_one_result=None) -> MagicMock:
    """Build a mocked ``get_database()`` return value."""
    mock_db = MagicMock()
    mock_col = MagicMock()
    if find_result is not None:
        mock_col.find = MagicMock(return_value=_async_iter(find_result))
    if find_one_result is not None or find_result is None:
        mock_col.find_one = AsyncMock(return_value=find_one_result)
    mock_db.__getitem__.return_value = mock_col
    return mock_db


class TestTriggerSchedulerServiceLifecycle:
    """Tests for service lifecycle."""

    @patch("app.services.trigger_scheduler_service.get_database")
    async def test_start_initializes_scheduler(self, mock_db: MagicMock) -> None:
        """Should start the scheduler and load triggers."""
        mock_db.return_value = _make_mock_db(find_result=[])

        service = TriggerSchedulerService()
        await service.start()
        assert service._started is True

        await service.stop()
        assert service._started is False

    @patch("app.services.trigger_scheduler_service.get_database")
    async def test_start_loads_enabled_workflows(self, mock_db: MagicMock) -> None:
        """Should register all workflows whose trigger_config is enabled."""
        wf1 = {"_id": "wf_1", "trigger_config": {"enabled": True, "type": "cron"}}
        wf2 = {"_id": "wf_2", "trigger_config": {"enabled": True, "type": "interval"}}
        mock_db.return_value = _make_mock_db(find_result=[wf1, wf2])

        service = TriggerSchedulerService()
        await service.start()

        assert service._workflows.keys() == {"wf_1", "wf_2"}
        assert service._workflows["wf_1"]["trigger_config"]["type"] == "cron"

        await service.stop()

    @patch("app.services.trigger_scheduler_service.get_database")
    async def test_start_is_idempotent(self, mock_db: MagicMock) -> None:
        """Should not restart if already started."""
        mock_db.return_value = _make_mock_db(find_result=[])

        service = TriggerSchedulerService()
        await service.start()
        await service.start()  # Should not raise
        assert service._started is True

        await service.stop()

    async def test_stop_clears_workflows(self) -> None:
        """Should clear registered workflows on stop."""
        service = TriggerSchedulerService()
        service._workflows["wf_x"] = {"_id": "wf_x"}
        service._started = True

        await service.stop()

        assert service._workflows == {}
        assert service._started is False


class TestRegisterTrigger:
    """Tests for register_trigger."""

    @patch("app.services.trigger_scheduler_service.get_database")
    async def test_register_enabled_workflow(self, mock_db: MagicMock) -> None:
        """Should register an enabled workflow trigger."""
        workflow_doc = {
            "_id": "wf_xxx",
            "trigger_config": {"enabled": True, "type": "cron"},
        }
        mock_db.return_value = _make_mock_db(find_one_result=workflow_doc)

        service = TriggerSchedulerService()
        await service.register_trigger("wf_xxx")

        assert "wf_xxx" in service._workflows
        assert service._workflows["wf_xxx"]["trigger_config"]["type"] == "cron"

    @patch("app.services.trigger_scheduler_service.get_database")
    async def test_register_disabled_workflow(self, mock_db: MagicMock) -> None:
        """Should not register a disabled workflow trigger."""
        workflow_doc = {
            "_id": "wf_xxx",
            "trigger_config": {"enabled": False, "type": "cron"},
        }
        mock_db.return_value = _make_mock_db(find_one_result=workflow_doc)

        service = TriggerSchedulerService()
        await service.register_trigger("wf_xxx")

        assert "wf_xxx" not in service._workflows

    @patch("app.services.trigger_scheduler_service.get_database")
    async def test_register_nonexistent_workflow(self, mock_db: MagicMock) -> None:
        """Should not register if workflow does not exist."""
        mock_db.return_value = _make_mock_db(find_one_result=None)

        service = TriggerSchedulerService()
        await service.register_trigger("wf_not_exist")

        assert "wf_not_exist" not in service._workflows


class TestUnregisterTrigger:
    """Tests for unregister_trigger."""

    async def test_unregister_existing(self) -> None:
        """Should remove an existing workflow from scheduler."""
        service = TriggerSchedulerService()
        service._workflows["wf_xxx"] = {"_id": "wf_xxx"}

        await service.unregister_trigger("wf_xxx")

        assert "wf_xxx" not in service._workflows

    async def test_unregister_nonexistent(self) -> None:
        """Should not raise if workflow is not registered."""
        service = TriggerSchedulerService()

        await service.unregister_trigger("wf_not_exist")
        # Should not raise


class TestUpdateTrigger:
    """Tests for update_trigger."""

    @patch("app.services.trigger_scheduler_service.get_database")
    async def test_update_trigger_replaces_doc(self, mock_db: MagicMock) -> None:
        """Should unregister then register the trigger with fresh data."""
        new_doc = {
            "_id": "wf_xxx",
            "trigger_config": {"enabled": True, "type": "cron"},
        }
        mock_db.return_value = _make_mock_db(find_one_result=new_doc)

        service = TriggerSchedulerService()
        service._workflows["wf_xxx"] = {"_id": "wf_xxx", "old": True}

        await service.update_trigger("wf_xxx")

        assert "wf_xxx" in service._workflows
        assert "old" not in service._workflows["wf_xxx"]
        assert service._workflows["wf_xxx"]["trigger_config"]["type"] == "cron"

    @patch("app.services.trigger_scheduler_service.get_database")
    async def test_update_trigger_disabled_removes(self, mock_db: MagicMock) -> None:
        """Should remove the workflow if trigger is now disabled."""
        disabled_doc = {
            "_id": "wf_xxx",
            "trigger_config": {"enabled": False, "type": "cron"},
        }
        mock_db.return_value = _make_mock_db(find_one_result=disabled_doc)

        service = TriggerSchedulerService()
        service._workflows["wf_xxx"] = {"_id": "wf_xxx"}

        await service.update_trigger("wf_xxx")

        assert "wf_xxx" not in service._workflows
