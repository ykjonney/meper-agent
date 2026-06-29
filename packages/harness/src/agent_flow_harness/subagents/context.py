"""SubAgentContext + ContextVar — delegate 工具的依赖注入协议。

与 v0.1 workspace_context 同模式：宿主在每次主 Agent 执行前
set_subagent_context()，delegate_to_subagent 工具内部 get_subagent_context()
读取。ContextVar 保证异步任务隔离。

resolve_tools 实现 AC7 工具排除：解析 spec.tools 后过滤掉
delegate_to_subagent，使子 Agent 物理上无法递归。
"""
from __future__ import annotations

import contextvars
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.tools import BaseTool

    from agent_flow_harness.subagents.registry import SubAgentRegistry
    from agent_flow_harness.subagents.spec import SubAgentSpec
    from agent_flow_harness.tools.registry import ToolRegistry

# delegate 工具名——resolve_tools 排除它实现 AC7。
_DELEGATE_TOOL_NAME = "delegate_to_subagent"


class SubAgentContext:
    """宿主注入给 delegate 工具的依赖包。

    Attributes:
        registry: 子 Agent 配置注册中心。
        tool_registry: 解析子 agent tools 的工具注册中心。
        build_llm: 按 spec.llm_config 构建 LLM 的工厂。
        parent_llm: 主 Agent 的 LLM；model="inherit" 时复用。
    """

    def __init__(
        self,
        registry: "SubAgentRegistry",
        tool_registry: "ToolRegistry",
        build_llm: "Callable[[dict[str, Any]], BaseChatModel]",
        parent_llm: "BaseChatModel | None",
    ) -> None:
        self.registry = registry
        self.tool_registry = tool_registry
        self.build_llm = build_llm
        self.parent_llm = parent_llm

    def resolve_llm(self, spec: "SubAgentSpec") -> "BaseChatModel":
        """解析子 Agent 的 LLM。model='inherit' 复用 parent_llm。"""
        model = spec.llm_config.get("model", "inherit")
        if model == "inherit":
            if self.parent_llm is None:
                msg = "llm_config model='inherit' but no parent_llm injected."
                raise RuntimeError(msg)
            return self.parent_llm
        return self.build_llm(spec.llm_config)

    def resolve_tools(self, spec: "SubAgentSpec") -> "list[BaseTool]":
        """解析 spec.tools 为 BaseTool 实例，排除 delegate_to_subagent (AC7)。

        构造一个临时 agent_doc 走 TOOL_REGISTRY.resolve，再过滤掉 delegate。
        未知工具名被 silently skip（与 TOOL_REGISTRY 行为一致）。
        """
        agent_doc: dict[str, Any] = {
            "tools": [{"name": n, "enabled": True} for n in spec.tools]
        }
        resolved = self.tool_registry.resolve(agent_doc)
        # AC7: 工具排除——子 Agent 不能拿到 delegate 工具。
        return [t for t in resolved if t.name != _DELEGATE_TOOL_NAME]

    def build_subagent_state(self, spec: "SubAgentSpec", task: str) -> "dict[str, Any]":
        """构建子 Agent 的全新 AgentState（AC8 完全隔离 stateless）。

        只有 SystemMessage(system_prompt) + HumanMessage(task)，无主 agent 历史。
        """
        # 延迟 import 避免循环依赖。
        from langchain_core.messages import HumanMessage, SystemMessage

        return {
            "messages": [
                SystemMessage(content=spec.system_prompt),
                HumanMessage(content=task),
            ],
        }


# ---------------------------------------------------------------------------
# ContextVar plumbing (与 workspace_context.py 同构)
# ---------------------------------------------------------------------------

_subagent_ctx: contextvars.ContextVar[SubAgentContext | None] = contextvars.ContextVar(
    "subagent_ctx", default=None
)


def set_subagent_context(ctx: SubAgentContext) -> "contextvars.Token[SubAgentContext | None]":
    """为本异步任务设置 subagent 依赖，返回 reset token。"""
    return _subagent_ctx.set(ctx)


def reset_subagent_context(token: "contextvars.Token[SubAgentContext | None]") -> None:
    """恢复之前的 subagent context 状态。"""
    _subagent_ctx.reset(token)


def get_subagent_context() -> SubAgentContext:
    """读取当前 subagent 依赖。未设置 raise RuntimeError。"""
    ctx = _subagent_ctx.get()
    if ctx is None:
        msg = (
            "SubAgentContext not set: call set_subagent_context() before "
            "invoking an agent that uses delegate_to_subagent."
        )
        raise RuntimeError(msg)
    return ctx


__all__ = [
    "SubAgentContext",
    "set_subagent_context",
    "reset_subagent_context",
    "get_subagent_context",
]
