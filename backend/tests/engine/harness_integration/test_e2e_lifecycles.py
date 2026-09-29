"""执行层 E2E 全链路 — Plan 生命周期 / Spawn 繁殖链 / resume 上下文推断。

与单测的区别：走真实 resolve_harness_context（真工具装配、真 recorder、
真 spawn 上下文）+ 真 LangGraph 图（真 interrupt 挂起/恢复），只把
LLM（FakeLLM 脚本化）与 DB 访问（context window / agent CRUD）打桩。
"""
from __future__ import annotations

import uuid
from typing import Any

import agent_flow_harness as harness_pkg
import pytest
from app.engine.harness_integration import execution as harness_exec
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver


class RecordingFakeLLM:
    """脚本化 chat model：按序吐 AIMessage，并记录每次 bind_tools 的工具名。

    bind_tools 记录是 resume 上下文推断断言的关键——工具集在图构建时
    绑定，record 到的名字即该 run 的真实工具集。
    """

    def __init__(self, responses: list[AIMessage]):
        self._responses = list(responses)
        self.bound_tools: list[list[str]] = []
        self.calls: list[Any] = []

    @property
    def model_name(self) -> str:
        return "fake-e2e"

    def bind_tools(self, tools):
        self.bound_tools.append(sorted(
            getattr(t, "name", str(t)) for t in tools
        ))
        return self

    async def ainvoke(self, messages, _config=None):
        self.calls.append(list(messages))
        if not self._responses:
            raise RuntimeError("FakeLLM exhausted")
        return self._responses.pop(0)


def _tool_call(name: str, args: dict) -> AIMessage:
    return AIMessage(content="", tool_calls=[
        {"id": f"call_{name}", "name": name, "args": args},
    ])


PLAN_TEXT = (
    "# 目标\n把示例仓库的测试跑通\n"
    "# 背景与约束\nPython 3.12，不得改业务代码\n"
    "# 步骤\n- [ ] 安装依赖\n- [ ] 跑 pytest\n"
    "# 验收标准\npytest -q 全绿\n"
    "# 完成时交付\n通过的报告"
)


def _agent_doc(**extra) -> dict:
    agent = {
        "_id": "agent_e2e_01",
        "name": "E2E Agent",
        "model": "gpt-test",
        "skill_ids": [],
        "knowledge_base_ids": [],
        "mcp_connection_ids": [],
        "workflow_ids": [],
        "builtin_config": ["bash"],
    }
    agent.update(extra)
    return agent


def _state(session_id: str, user_text: str = "请帮我跑通测试") -> dict:
    from langchain_core.messages import HumanMessage

    return {
        "messages": [HumanMessage(content=user_text)],
        "session_id": session_id,
        "user_id": "",
        "request_id": f"req_{uuid.uuid4().hex[:8]}",
    }


@pytest.fixture
async def memory_checkpointer():
    """图挂起需要跨 stream/resume 调用共享的 checkpointer。"""
    saver = MemorySaver()
    old = harness_pkg.get_checkpointer()
    harness_pkg.configure_checkpointer(saver, overwrite=True)
    yield saver
    harness_pkg.configure_checkpointer(old, overwrite=True)


@pytest.fixture
def patch_resolve_deps(monkeypatch):
    """打掉 resolve 链上的外部依赖：LLM 构造 / context window 查询。"""
    created: dict[str, RecordingFakeLLM] = {}

    async def fake_get_llm_client(agent, enable_thinking=False, **_kw):
        llm = RecordingFakeLLM(created.pop("responses"))
        created["llm"] = llm
        return llm

    async def fake_window(_model_ref, **_kw):
        return 131_072

    monkeypatch.setattr(
        "app.engine.llm_factory.get_llm_client", fake_get_llm_client,
    )
    monkeypatch.setattr(
        "app.engine.agent.context.get_context_window_async", fake_window,
    )
    return created


async def _sink_into(events: list[dict]):
    async def _on(e: dict) -> None:
        events.append(e)
    return _on


async def _noop_on_event(_e: dict) -> None:
    """on_event 必须是协程（execution 层直接 await）。"""


class TestPlanLifecycleE2E:
    """Plan 全链路：plan stream → propose_plan interrupt → resume(反馈/批准)。"""

    async def test_plan_run_interrupts_with_plan_card_and_resume_forces_plan(
        self, memory_checkpointer, patch_resolve_deps,
    ):
        sid = f"sess_plan_{uuid.uuid4().hex[:8]}"
        patch_resolve_deps["responses"] = [
            _tool_call("propose_plan", {"plan": PLAN_TEXT}),
        ]

        events: list[dict] = []
        await harness_exec.stream(
            _agent_doc(), _state(sid),
            on_event=await _sink_into(events),
            execution_context="plan",
        )

        # 1) 中断卡：type=interrupt + kind=plan + 完整计划文本
        intr = [e for e in events if e.get("type") == "interrupt"]
        assert intr, f"未产生 interrupt 事件: {events}"
        assert intr[0]["kind"] == "plan"
        assert "# 目标" in intr[0]["plan"]

        # 2) plan run 的工具集：含 propose_plan/ask_clarification/bash，
        #    不含 write/edit/run_code/dispatch_workflow（副作用与编排剥离）
        llm: RecordingFakeLLM = patch_resolve_deps["llm"]
        names0 = llm.bound_tools[0]
        assert "propose_plan" in names0
        assert "ask_clarification" in names0
        assert "bash" in names0
        for banned in ("write", "edit", "run_code", "dispatch_workflow"):
            assert banned not in names0, banned

        # 3) resume（反馈文本，客户端不带 plan_mode）→ 探针强制 plan 上下文：
        #    propose_plan 重放拿到 resume 值，LLM 收到后正常收尾
        patch_resolve_deps["responses"] = [
            AIMessage(content="已收到反馈，我会修改计划。"),
        ]
        resume_events: list[dict] = []
        await harness_exec.resume(
            _agent_doc(), _state(sid),
            on_event=await _sink_into(resume_events),
            answer="缩小范围到后端",
            execution_context="chat",  # 故意给 chat——探针应推翻它
        )
        names1 = llm.bound_tools[-1]
        assert "propose_plan" in names1, "resume 未强制 plan 上下文（探针失效）"
        assert "write" not in names1

        # resume 轮收尾：无 error 事件；反馈链闭环——反馈标记作为
        # ToolMessage 回到 LLM（FakeLLM 非 Runnable 不产生 text 事件，
        # 以调用快照断言循环真正回到模型）
        errs = [e for e in resume_events if e.get("type") == "error"]
        assert not errs, errs
        # fixture 每次 resolve 新建 FakeLLM——resume 后取最新实例断言
        llm_resume: RecordingFakeLLM = patch_resolve_deps["llm"]
        assert llm_resume is not llm, "resume 未重新装配上下文"
        assert llm_resume.calls, "resume 后未回到 LLM"
        assert any(
            "用户对计划的反馈" in str(m) for m in llm_resume.calls[-1]
        ), llm_resume.calls[-1]

    async def test_approval_marker_resume_closes_card(
        self, memory_checkpointer, patch_resolve_deps,
    ):
        """批准标记 resume：propose_plan 返回批准文案，图自然收尾。"""
        sid = f"sess_approve_{uuid.uuid4().hex[:8]}"
        patch_resolve_deps["responses"] = [
            _tool_call("propose_plan", {"plan": PLAN_TEXT}),
        ]
        first: list[dict] = []
        await harness_exec.stream(
            _agent_doc(), _state(sid), on_event=await _sink_into(first),
            execution_context="plan",
        )
        assert any(
            e.get("type") == "interrupt" and e.get("kind") == "plan"
            for e in first
        )

        from app.engine.agent.plan_tool import PLAN_APPROVED_MARKER
        patch_resolve_deps["responses"] = [
            AIMessage(content="计划已批准，准备开始执行。"),
        ]
        second: list[dict] = []
        await harness_exec.resume(
            _agent_doc(), _state(sid),
            on_event=await _sink_into(second),
            answer=PLAN_APPROVED_MARKER,
            execution_context="plan",
        )
        assert not [e for e in second if e.get("type") == "error"]
        # 批准标记 → propose_plan 返回批准文案 → 回到 LLM 收尾
        llm2: RecordingFakeLLM = patch_resolve_deps["llm"]
        assert llm2.calls, "批准 resume 后未回到 LLM"
        assert any(
            "用户已批准" in str(m) for m in llm2.calls[-1]
        ), llm2.calls[-1]


class TestSpawnChainE2E:
    """Spawn 全链路：list_capabilities 盘点 → create_agent（治理断言）。"""

    async def test_full_chain_creates_audited_draft(
        self, memory_checkpointer, patch_resolve_deps, monkeypatch,
    ):

        sid = f"sess_spawn_{uuid.uuid4().hex[:8]}"
        agent = _agent_doc(can_spawn_agents=True)

        # 盘点与创建的服务层打桩（DB 访问隔离）：
        # list_capabilities 直接查 tools 集合 → fake get_database；
        # create_agent 走 AgentService → 打桩类方法捕获治理参数。

        class _FakeCursor:
            def __init__(self, docs):
                self._docs = docs

            def limit(self, _n):
                return self

            async def to_list(self, _length=None):
                return self._docs

        class _FakeColl:
            def __init__(self, docs):
                self._docs = docs

            def find(self, _q, _proj=None):
                return _FakeCursor(self._docs)

            async def find_one(self, _q, _proj=None):
                return None

        class _FakeDB:
            def __getitem__(self, name):
                if name == "tools":
                    return _FakeColl([
                        {"_id": "t_wx", "name": "查天气", "description": "查天气",
                         "source": "openapi", "status": "active"},
                    ])
                return _FakeColl([])

        monkeypatch.setattr(
            "app.db.mongodb.get_database", lambda: _FakeDB(),
        )

        create_calls: list[dict] = []

        async def fake_create_agent(*_a, **kw):
            create_calls.append(kw)
            return {"_id": "child_01", "name": kw.get("name", ""), "status": "draft"}

        from app.services.agent_service import AgentService
        monkeypatch.setattr(
            AgentService, "create_agent", staticmethod(fake_create_agent),
        )
        # 平台用户守卫依赖 workspace 上下文（E2E 无登录态）——打桩放行；
        # 守卫逻辑本身在 test_spawn_tools 有独立单测。
        async def fake_platform_user() -> bool:
            return True

        monkeypatch.setattr(
            "app.engine.agent.spawn_tools._is_platform_user", fake_platform_user,
        )

        # 技能列表（SkillManager 走文件系统，测试环境无官方技能根也返回空）
        patch_resolve_deps["responses"] = [
            _tool_call("list_capabilities", {}),
            _tool_call("create_agent", {
                "name": "报表助手",
                "description": "生成周报",
                "system_prompt": "你是报表专家",
            }),
            AIMessage(content="已创建草稿 Agent「报表助手」。"),
        ]

        events: list[dict] = []
        state = _state(sid)
        state["user_id"] = "user_e2e"  # workspace 审计上下文需要平台用户
        await harness_exec.stream(
            agent, state, on_event=await _sink_into(events),
        )

        # 1) spawn 工具确实注入（can_spawn_agents=True + chat 上下文）
        llm: RecordingFakeLLM = patch_resolve_deps["llm"]
        names = llm.bound_tools[0]
        for t in ("list_capabilities", "create_agent", "test_agent"):
            assert t in names, t

        # 2) create_agent 走了服务层，且治理不变量成立：
        #    工具不传 status（草稿态由服务层默认施加——工具侧无从越权
        #    直接发布）、不继承繁殖能力、审计字段指向父 agent（ContextVar 注入）
        assert create_calls, "create_agent 未被调用"
        kw = create_calls[0]
        assert kw.get("status") in (None, "draft"), kw.get("status")
        assert kw.get("can_spawn_agents") is False, "权限放大：子代继承了繁殖能力"
        assert kw.get("spawned_by_agent_id") == "agent_e2e_01", kw.get("spawned_by_agent_id")
        assert kw.get("spawned_by_session_id") == sid

        # 3) 链路收尾正常（无 error；三轮 LLM：盘点→创建→总结）
        assert not [e for e in events if e.get("type") == "error"]
        spawn_llm: RecordingFakeLLM = patch_resolve_deps["llm"]
        assert len(spawn_llm.calls) == 3, len(spawn_llm.calls)

    async def test_spawn_gate_off_by_default(
        self, memory_checkpointer, patch_resolve_deps,
    ):
        """can_spawn_agents 未开启 → 三件 spawn 工具一个都不注入。"""
        sid = f"sess_nospawn_{uuid.uuid4().hex[:8]}"
        patch_resolve_deps["responses"] = [AIMessage(content="好的。")]
        await harness_exec.stream(
            _agent_doc(), _state(sid), on_event=_noop_on_event,
        )
        names = patch_resolve_deps["llm"].bound_tools[0]
        for t in ("list_capabilities", "create_agent", "test_agent"):
            assert t not in names, t


class TestResumeContextInferenceE2E:
    """resume 上下文推断：探针读 checkpoint，不信调用方参数。"""

    async def test_chat_interrupt_resume_stays_chat(
        self, memory_checkpointer, patch_resolve_deps,
    ):
        """对照组：挂起的是 ask_clarification（chat 工具集），resume 后
        工具集仍是 chat 语义（有 write/dispatch，无 propose_plan）——
        探针只对 plan 挂起强制 plan，不误伤普通澄清。"""
        sid = f"sess_clarify_{uuid.uuid4().hex[:8]}"
        patch_resolve_deps["responses"] = [
            _tool_call("ask_clarification", {
                "question": "用哪个数据源？",
                "options": ["A", "B"], "type": "single_choice",
            }),
        ]
        await harness_exec.stream(
            _agent_doc(), _state(sid), on_event=_noop_on_event,
        )
        llm: RecordingFakeLLM = patch_resolve_deps["llm"]
        assert "ask_clarification" in llm.bound_tools[0]

        patch_resolve_deps["responses"] = [AIMessage(content="用 A。")]
        await harness_exec.resume(
            _agent_doc(), _state(sid),
            on_event=_noop_on_event, answer="A",
        )
        names = llm.bound_tools[-1]
        assert "propose_plan" not in names, "普通澄清被误判为 plan 挂起"
        assert "write" in names, "chat 上下文工具集被意外裁剪"
