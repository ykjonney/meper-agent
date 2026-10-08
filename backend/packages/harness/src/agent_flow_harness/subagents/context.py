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
        tools_provider: 可选,宿主预解析工具集的注入通道(spec -> 工具列表)。
            app 层工具(MCP/KB/skill/自定义)是动态解析的,静态 tool_registry
            取不到;宿主在装配期预解析后经此注入,优先于 tool_registry。
        llm_provider: 可选,宿主预构建 LLM 的注入通道(spec -> LLM)。同上,
            优先于 build_llm/parent_llm。
        usage_totals: 委派子图 usage 的累计器。delegate 每次执行后把子图
            UsageMiddleware.summary 累加进来,宿主在父 graph 执行结束后读取
            并入父级 usage——子图消耗不冒泡则 token 账本有缺口。
    """

    def __init__(
        self,
        registry: "SubAgentRegistry",
        tool_registry: "ToolRegistry",
        build_llm: "Callable[[dict[str, Any]], BaseChatModel]",
        parent_llm: "BaseChatModel | None",
        *,
        tools_provider: "Callable[[SubAgentSpec], list[BaseTool]] | None" = None,
        llm_provider: "Callable[[SubAgentSpec], BaseChatModel] | None" = None,
    ) -> None:
        self.registry = registry
        self.tool_registry = tool_registry
        self.build_llm = build_llm
        self.parent_llm = parent_llm
        self.tools_provider = tools_provider
        self.llm_provider = llm_provider
        # 累计器 key 与 UsageMiddleware.metrics 同构(total_tokens 等),
        # 数值型累加、计数型累加,由 accumulate_usage 归一。
        self.usage_totals: dict[str, Any] = {}

    def accumulate_usage(self, summary: dict[str, Any]) -> None:
        """把一次委派子图的 usage summary 累加进 totals(数值相加)。"""
        for key, value in summary.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            self.usage_totals[key] = self.usage_totals.get(key, 0) + value

    def resolve_llm(self, spec: "SubAgentSpec") -> "BaseChatModel":
        """解析子 Agent 的 LLM。宿主 llm_provider 优先;model='inherit' 复用 parent_llm。"""
        if self.llm_provider is not None:
            return self.llm_provider(spec)
        model = spec.llm_config.get("model", "inherit")
        if model == "inherit":
            if self.parent_llm is None:
                msg = "llm_config model='inherit' but no parent_llm injected."
                raise RuntimeError(msg)
            return self.parent_llm
        return self.build_llm(spec.llm_config)

    def resolve_tools(self, spec: "SubAgentSpec") -> "list[BaseTool]":
        """解析 spec.tools 为 BaseTool 实例，排除 delegate_to_subagent (AC7)。

        宿主 tools_provider 优先(app 层动态工具集);否则构造临时 agent_doc
        走 TOOL_REGISTRY.resolve。两种路径都过滤 delegate——子 Agent 物理上
        无法递归(深度=1)。
        """
        if self.tools_provider is not None:
            resolved = self.tools_provider(spec)
        else:
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
