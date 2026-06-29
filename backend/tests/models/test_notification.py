"""Tests for Notification model."""
from app.models.notification import Notification, NotificationKind


class TestNotificationModel:
    def test_create_notification_with_defaults(self):
        n = Notification(
            user_id="user_abc",
            kind=NotificationKind.TASK_COMPLETED,
            title="任务完成",
            body="Workflow「测试」已完成",
        )
        assert n.id.startswith("notif_")
        assert n.read is False
        assert n.related_task_id is None
        assert n.related_workflow_id is None

    def test_create_notification_with_all_fields(self):
        n = Notification(
            user_id="user_abc",
            kind=NotificationKind.TASK_FAILED,
            title="任务失败",
            body="节点 LLM 超时",
            related_task_id="task_xxx",
            related_workflow_id="wf_yyy",
        )
        assert n.kind == NotificationKind.TASK_FAILED
        assert n.related_task_id == "task_xxx"

    def test_notification_kind_values(self):
        assert NotificationKind.TASK_FAILED == "task_failed"
        assert NotificationKind.TASK_WAITING_HUMAN == "task_waiting_human"
        assert NotificationKind.TASK_COMPLETED == "task_completed"

    def test_to_mongo_dict(self):
        n = Notification(
            user_id="user_abc",
            kind=NotificationKind.TASK_COMPLETED,
            title="任务完成",
            body="test",
        )
        d = n.model_dump(by_alias=True)
        assert "_id" in d
        assert d["user_id"] == "user_abc"
