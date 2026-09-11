"""WorkflowEngine._is_external_task 判定 — MCP 凭证 fail-closed 的依据。

任务文档是外部来源判定的事实源，三种外部来源与内部来源的边界
（studio 手动 / 定时触发 / studio 聊天内 agent 派发均不得误判）。
"""
from __future__ import annotations

from app.engine.workflow.engine import WorkflowEngine


class TestIsExternalTask:
    def test_api_key_direct_invoke(self) -> None:
        """ext invoke 直接触发（created_by_type=api_key）→ 外部。"""
        assert WorkflowEngine._is_external_task({"created_by_type": "api_key"}) is True

    def test_ext_origin_marker(self) -> None:
        """外部 chat 内 agent dispatch_workflow（ext_origin=external）→ 外部。"""
        assert WorkflowEngine._is_external_task({"ext_origin": "external"}) is True

    def test_ext_token_only(self) -> None:
        """任务文档携带终端用户 token（含 subflow 继承）→ 外部。"""
        assert WorkflowEngine._is_external_task({"ext_user_token": "tok"}) is True

    def test_subflow_inherited_token(self) -> None:
        """subflow 子任务（created_by_type=system 但继承了 token）→ 外部。"""
        assert (
            WorkflowEngine._is_external_task(
                {"created_by_type": "system", "ext_user_token": "tok"}
            )
            is True
        )

    def test_studio_manual_is_internal(self) -> None:
        """studio 手动建任务 → 内部。"""
        assert WorkflowEngine._is_external_task({"created_by_type": "user"}) is False

    def test_scheduled_trigger_is_internal(self) -> None:
        """定时触发（created_by_type=system 无 token）→ 内部。"""
        assert WorkflowEngine._is_external_task({"created_by_type": "system"}) is False

    def test_empty_doc_is_internal(self) -> None:
        """空文档 / 缺字段 → 内部（fail-open 仅限无任何外部痕迹的任务）。"""
        assert WorkflowEngine._is_external_task({}) is False
