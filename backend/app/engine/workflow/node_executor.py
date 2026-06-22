"""Node executor base class and implementations (Strategy pattern).

Each node type has a corresponding executor that implements ``execute()``.
The ``WorkflowEngine`` selects the appropriate executor based on node type.
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from loguru import logger


@dataclass
class NodeResult:
    """Result of executing a single workflow node."""

    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    error_message: str = ""
    error_code: str = ""
    # For gateway nodes: the selected branch target node ID
    selected_branch: str | None = None


class BaseNodeExecutor(ABC):
    """Abstract base for all workflow node executors.

    Subclasses must implement ``execute()``.
    """

    def __init__(self, node_id: str, node_config: dict[str, Any]) -> None:
        self.node_id = node_id
        self.node_config = node_config

    @abstractmethod
    async def execute(self, variables: dict[str, Any]) -> NodeResult:
        """Execute the node and return the result.

        Args:
            variables: Current variable pool (read-only snapshot).

        Returns:
            NodeResult with success/failure and output data.
        """
        ...


# ── Start ──


class StartNodeExecutor(BaseNodeExecutor):
    """Initialise variable pool with Task input.

    Config::

        {
            "output_variables": [
                {
                    "name": "query",
                    "type": "text",
                    "constraints": {"required": true, "default_value": ""},
                    ...
                },
                ...
            ],
            "input_mapping": { "var_name": "{{ input.field }}" }  # optional override
        }

    ``required`` / ``default_value`` are read from ``constraints``
    (matching the frontend ``VariableListEditor`` schema).  Top-level
    ``required`` / ``default`` keys are still accepted for backward
    compatibility with legacy data.
    """

    async def execute(self, variables: dict[str, Any]) -> NodeResult:
        logger.debug("node_start", node_id=self.node_id)

        output: dict[str, Any] = {}

        # 1. If input_mapping is explicitly configured, use it (takes precedence)
        input_mapping = self.node_config.get("input_mapping", {})
        if input_mapping:
            from app.engine.workflow.expression import ExpressionEngine

            engine = ExpressionEngine(variables)
            output = engine.resolve_dict(input_mapping)
            return NodeResult(success=True, output=output)

        # 2. Otherwise, initialize variables from output_variables definition
        output_variables = self.node_config.get("output_variables", [])
        task_input = variables.get("input")
        if not isinstance(task_input, dict):
            task_input = {}

        if isinstance(output_variables, list) and output_variables:
            missing_required: list[str] = []

            for var_def in output_variables:
                if not isinstance(var_def, dict):
                    continue
                name = var_def.get("name", "")
                if not name:
                    continue

                var_type = var_def.get("type", "text")

                # Read required/default from `constraints` (frontend schema)
                # with top-level fallback for legacy data.
                constraints = var_def.get("constraints") if isinstance(var_def.get("constraints"), dict) else {}
                raw_required = constraints.get("required", var_def.get("required"))
                is_required = bool(raw_required) if raw_required is not None else False
                default_val = constraints.get("default_value", var_def.get("default"))

                # Use input value if provided, else fall back to default.
                if name in task_input:
                    value = task_input[name]
                elif default_val not in (None, ""):
                    value = default_val
                else:
                    value = None

                # File type: delegate to file_validator for resolution.
                if var_type == "file":
                    if value in (None, ""):
                        # No file provided — handled by required check below
                        pass
                    else:
                        from app.engine.workflow.file_validator import validate_file_variable

                        resolved, ferror = await validate_file_variable(value, var_def)
                        if ferror:
                            return NodeResult(
                                success=False,
                                output={},
                                error_message=f"Start 节点文件变量 '{name}' 验证失败: {ferror}",
                            )
                        output[name] = resolved
                        continue

                # Required validation: None or empty string counts as missing.
                if is_required and value in (None, ""):
                    missing_required.append(name)
                else:
                    output[name] = value

            if missing_required:
                return NodeResult(
                    success=False,
                    output={},
                    error_message=(
                        f"Start 节点必填变量缺失: {', '.join(missing_required)}。"
                        f"请在 dispatch_workflow 的 params 中补充这些字段。"
                    ),
                )

            return NodeResult(success=True, output=output)

        # 3. Fallback: pass through all task input
        return NodeResult(success=True, output={"input": task_input})


# ── End ──


class EndNodeExecutor(BaseNodeExecutor):
    """Summarise output and signal completion.

    Config: ``{"output_mapping": { "result": "{{ node_id.field }}" }}``
    """

    async def execute(self, variables: dict[str, Any]) -> NodeResult:
        logger.debug("node_end", node_id=self.node_id)
        output_mapping = self.node_config.get("output_mapping", {})

        if output_mapping:
            from app.engine.workflow.expression import ExpressionEngine

            engine = ExpressionEngine(variables)
            resolved = engine.resolve_dict(output_mapping)
            return NodeResult(success=True, output=resolved)

        return NodeResult(success=True, output={"status": "completed"})


# ── Agent ──


class AgentNodeExecutor(BaseNodeExecutor):
    """Invoke an Agent to perform reasoning/actions.

    Config::

        {
            "agent_id": "agent_xxx",
            "system_prompt_override": "...",  # optional
            "input_prompt": "{{ ... }}",       # prompt template
            "temperature": 0.7                 # optional
        }
    """

    async def execute(self, variables: dict[str, Any]) -> NodeResult:
        agent_id = self.node_config.get("agent_id", "")
        if not agent_id:
            return NodeResult(success=False, output={}, error_message="agent_id 未配置")

        from app.engine.workflow.expression import ExpressionEngine

        engine = ExpressionEngine(variables)

        # input_query → user message（查询）
        input_query = self.node_config.get("input_query", "")
        resolved_query = engine.resolve(input_query) if input_query else ""

        # input_prompt → context 卡槽覆盖（注入系统提示，不作为 user message）
        # 向后兼容：也读取 slot_values.context
        input_prompt = self.node_config.get("input_prompt", "")
        resolved_context = engine.resolve(input_prompt) if input_prompt else ""
        if not resolved_context:
            legacy_slot_ctx = self.node_config.get("slot_values", {}).get("context", "")
            resolved_context = engine.resolve(legacy_slot_ctx) if legacy_slot_ctx else ""

        try:
            from langchain_core.messages import SystemMessage

            from app.db.mongodb import get_database
            from app.engine.agent.builder import build_agent_graph

            db = get_database()
            agent_doc = await db["agents"].find_one({"_id": agent_id})
            if agent_doc is None:
                return NodeResult(
                    success=False,
                    output={},
                    error_message=f"Agent {agent_id} 不存在",
                )

            # 仅允许覆盖 context 卡槽（role/task/constraints/output_format 由 Agent 自身决定）
            context_overrides = {"context": resolved_context} if resolved_context else None

            temperature = self.node_config.get("temperature")
            if temperature is not None:
                agent_doc["temperature_override"] = temperature

            graph = await build_agent_graph(agent_doc)

            # Build system prompt via slot renderer (context override + variable pool)
            from app.engine.agent.slot_renderer import render_system_prompt_full

            system_text = await render_system_prompt_full(
                agent_doc,
                node_slot_overrides=context_overrides,
                variable_pool=variables,
            )
        except Exception as exc:
            # 展开 ExceptionGroup 以显示真正原因
            detail = str(exc)
            if hasattr(exc, "exceptions"):
                sub_errors = "; ".join(str(e) for e in exc.exceptions)  # type: ignore[attr-defined]
                detail = f"{exc} — 子异常: {sub_errors}"
            logger.error("node_agent_setup_failed", node_id=self.node_id, error=detail)
            return NodeResult(
                success=False,
                output={},
                error_message=f"Agent 初始化失败: {detail}",
            )

        # Execute with timeout protection and retry
        timeout_ms = self.node_config.get("timeout_ms", 300000)
        max_retry = self.node_config.get("max_retry", 0)
        retry_delay_ms = self.node_config.get("retry_delay_ms", 2000)

        # thread_id 用于 LangGraph checkpointer（MongoDBSaver），每次执行业务 ID 不同
        import time as _time

        _thread_id = f"{self.node_id}_{int(_time.time() * 1000)}"

        # 组装初始消息：system prompt（含工具声明 + context 卡槽注入）+ 用户查询
        # 注意：input_prompt 已经通过 context 卡槽注入系统提示，不作为独立 user message
        # 只有 input_query 作为 user message
        # strip() 防止空白字符串逃过 truthiness 检查导致 LLM API 报
        # "messages: at least one message is required"（空 SystemMessage 不算有效消息）
        stripped_system = system_text.strip() if system_text else ""
        stripped_query = resolved_query.strip() if resolved_query else ""

        initial_messages: list = []
        if stripped_system:
            initial_messages.append(SystemMessage(content=stripped_system))

        if stripped_query:
            initial_messages.append({"role": "user", "content": stripped_query})

        # 兜底：没有任何有效消息时 LLM API 会报 "at least one message is required"
        if not initial_messages:
            logger.warning(
                "node_agent_empty_messages",
                node_id=self.node_id,
                agent_id=agent_id,
                input_query=input_query,
                variables=variables,
            )
            initial_messages.append({
                "role": "user",
                "content": f"请根据你的系统提示执行任务（input_query='{input_query}' 解析结果为空）",
            })

        last_error: str | None = None
        for attempt in range(1 + max_retry):
            try:
                result = await asyncio.wait_for(
                    graph.ainvoke(
                        {"messages": initial_messages},
                        config={"configurable": {"thread_id": _thread_id}},
                    ),
                    timeout=timeout_ms / 1000,
                )
                output_content = ""
                if result.get("messages"):
                    last_msg = result["messages"][-1]
                    # 兼容 LangChain AIMessage（.content）和 dict（["content"] / .get("content")）
                    if isinstance(last_msg, dict):
                        output_content = last_msg.get("content", str(last_msg))
                    elif hasattr(last_msg, "content"):
                        output_content = last_msg.content
                    else:
                        output_content = str(last_msg)
                return NodeResult(
                    success=True,
                    output={"response": output_content, "agent_id": agent_id},
                )
            except TimeoutError:
                last_error = f"Agent 执行超时 ({timeout_ms}ms)"
                logger.warning("node_agent_timeout", node_id=self.node_id, attempt=attempt + 1)
            except Exception as exc:
                last_error = f"Agent 执行失败: {exc}"
                logger.error("node_agent_failed", node_id=self.node_id, error=str(exc), attempt=attempt + 1)

            if attempt < max_retry:
                logger.info("agent_retry", node_id=self.node_id, attempt=attempt + 1, max_retry=max_retry)
                await asyncio.sleep(retry_delay_ms / 1000)

        return NodeResult(
            success=False,
            output={},
            error_message=last_error or "Agent 执行失败",
        )


# ── Tool ──


class ToolNodeExecutor(BaseNodeExecutor):
    """Invoke a registered tool from the tool pool.

    Config::

        {
            "tool_id": "tool_xxx",
            "params": { "key": "{{ node.field }}" },  # resolved at runtime
            "timeout_ms": 30000,
            "retry_policy": { "max_retries": 3, "backoff_ms": 1000 }
        }
    """

    async def execute(self, variables: dict[str, Any]) -> NodeResult:
        tool_id = self.node_config.get("tool_id", "")
        if not tool_id:
            return NodeResult(success=False, output={}, error_message="tool_id 未配置")

        # Resolve params from variables
        from app.engine.workflow.expression import ExpressionEngine

        engine = ExpressionEngine(variables)
        raw_params = self.node_config.get("params", {})
        resolved_params = engine.resolve_dict(raw_params) if isinstance(raw_params, dict) else raw_params

        try:
            # Fetch tool from MongoDB
            from app.db.mongodb import get_database

            db = get_database()
            tool_doc = await db["tools"].find_one({"$or": [{"_id": tool_id}, {"name": tool_id}]})
            if tool_doc is None:
                return NodeResult(
                    success=False,
                    output={},
                    error_message=f"Tool {tool_id} 不存在",
                )

            # Execute based on tool source type
            source = tool_doc.get("source", "markdown")

            if source == "mcp":
                # MCP tool — invoke via MCP client
                return await self._execute_mcp_tool(tool_doc, resolved_params)
            else:
                # Markdown/Skill tool — return instructions as context
                return NodeResult(
                    success=True,
                    output={
                        "tool_name": tool_doc.get("name", ""),
                        "tool_description": tool_doc.get("description", ""),
                        "instructions": tool_doc.get("instructions", ""),
                        "params": resolved_params,
                        "note": "工具的完整执行由 Agent 推理循环处理",
                    },
                )
        except Exception as exc:
            logger.error("node_tool_failed", node_id=self.node_id, error=str(exc))
            return NodeResult(
                success=False,
                output={},
                error_message=f"Tool 调用失败: {exc}",
            )

    async def _execute_mcp_tool(
        self,
        tool_doc: dict[str, Any],
        params: dict[str, Any],
    ) -> NodeResult:
        """Execute an MCP-sourced tool with timeout protection and retry."""
        try:
            from app.engine.tool.mcp_tool_cache import get_mcp_tools_cached

            # Get connection ID from tool doc
            conn_id = tool_doc.get("mcp_connection_id", "")
            if not conn_id:
                return NodeResult(
                    success=False,
                    output={},
                    error_message="MCP 工具缺少 connection_id",
                )

            # Get tools for this connection
            tools = await get_mcp_tools_cached([conn_id])

            # Find the matching tool by name
            tool_name = tool_doc.get("name", "")
            matching = [t for t in tools if t.name == tool_name or t.name.endswith(f"__{tool_name}")]
            if not matching:
                return NodeResult(
                    success=False,
                    output={},
                    error_message=f"MCP 工具 {tool_name} 未在连接中找到",
                )

            tool = matching[0]

            # Retry and timeout configuration
            timeout_ms = self.node_config.get("timeout_ms", 30000)
            timeout_s = timeout_ms / 1000
            retry_policy = self.node_config.get("retry_policy", {})
            max_retries = retry_policy.get("max_retries", 0)
            backoff_ms = retry_policy.get("backoff_ms", 1000)

            last_error: str | None = None
            for attempt in range(1 + max_retries):
                try:
                    result = await asyncio.wait_for(tool.ainvoke(params), timeout=timeout_s)
                    return NodeResult(success=True, output={"result": result, "tool_id": tool_doc["_id"]})
                except TimeoutError:
                    last_error = f"MCP 工具执行超时 ({timeout_ms}ms)"
                    logger.warning("mcp_tool_timeout", node_id=self.node_id, attempt=attempt + 1)
                except Exception as exc:
                    last_error = f"MCP 工具执行失败: {exc}"
                    logger.error("mcp_tool_execution_failed", node_id=self.node_id, error=str(exc), attempt=attempt + 1)

                if attempt < max_retries:
                    logger.info("tool_retry", node_id=self.node_id, attempt=attempt + 1, max_retries=max_retries)
                    await asyncio.sleep(backoff_ms / 1000)

            return NodeResult(
                success=False,
                output={},
                error_message=last_error or "MCP 工具执行失败",
            )

        except Exception as exc:
            logger.error("mcp_tool_setup_failed", error=str(exc))
            return NodeResult(
                success=False,
                output={},
                error_message=f"MCP 工具执行失败: {exc}",
            )


# ── Gateway ──


class GatewayNodeExecutor(BaseNodeExecutor):
    """Evaluate conditions and select a branch.

    Config::

        {
            "conditions": [
                { "expression": "{{ node_1.result.status }}", "expected": "ok", "target": "node_3" },
                { "expression": "{{ node_1.result.status }}", "expected": "fail", "target": "node_4" }
            ],
            "default_branch": "node_5",
            "fallback_on_error": "node_5"
        }

    Conditions are evaluated in order; the first match wins.
    """

    async def execute(self, variables: dict[str, Any]) -> NodeResult:
        conditions = self.node_config.get("conditions", [])
        default_branch = self.node_config.get("default_branch", "")
        fallback = self.node_config.get("fallback_on_error", default_branch)

        from app.engine.workflow.expression import ExpressionEngine

        engine = ExpressionEngine(variables)

        for cond in conditions:
            expression = cond.get("expression", "")
            expected = cond.get("expected", True)
            target = cond.get("target", "")

            try:
                actual = engine.resolve(expression)
                if actual == expected or (isinstance(expected, bool) and bool(actual) == expected):
                    logger.debug(
                        "gateway_match",
                        node_id=self.node_id,
                        target=target,
                    )
                    return NodeResult(
                        success=True,
                        output={"selected_branch": target, "condition": expression},
                        selected_branch=target,
                    )
            except Exception as exc:
                logger.warning("gateway_condition_error", node_id=self.node_id, expression=expression, error=str(exc))
                continue

        # No condition matched — use fallback
        logger.debug("gateway_fallback", node_id=self.node_id, target=fallback)
        return NodeResult(
            success=True,
            output={"selected_branch": fallback, "condition": "default"},
            selected_branch=fallback,
        )


# ── Parallel ──


class ParallelNodeExecutor(BaseNodeExecutor):
    """Execute multiple branches in parallel and merge results.

    Config::

        {
            "branches": [
                { "id": "branch_1", "start_node": "node_a" },
                { "id": "branch_2", "start_node": "node_b" }
            ],
            "join_strategy": "all",      # all | any | n-of-m
            "join_count": null,           # for n-of-m strategy
            "scope": "shared"             # shared | isolated
        }

    The actual branch execution is handled by the WorkflowEngine.
    This executor only manages the parallel fan-out configuration.
    """

    async def execute(self, variables: dict[str, Any]) -> NodeResult:
        branches = self.node_config.get("branches", [])
        scope = self.node_config.get("scope", "shared")

        branch_ids = [b.get("id", f"branch_{i}") for i, b in enumerate(branches)]
        start_nodes = {
            b.get("id", f"branch_{i}"): b.get("start_node", "")
            for i, b in enumerate(branches)
        }

        return NodeResult(
            success=True,
            output={
                "branches": branch_ids,
                "start_nodes": start_nodes,
                "join_strategy": self.node_config.get("join_strategy", "all"),
                "join_count": self.node_config.get("join_count"),
                "scope": scope,
            },
        )


# ── Subflow ──


class SubflowNodeExecutor(BaseNodeExecutor):
    """Create a child Task from another Workflow and wait for results.

    Config::

        {
            "workflow_id": "wf_xxx",
            "input_mapping": { "var_1": "{{ node_1.result }}" },
            "result_mapping": { "output": "{{ result.field }}" },
            "timeout_ms": 600000
        }
    """

    async def execute(self, variables: dict[str, Any]) -> NodeResult:
        workflow_id = self.node_config.get("workflow_id", "")
        if not workflow_id:
            return NodeResult(success=False, output={}, error_message="workflow_id 未配置")

        # Resolve input from variables
        from app.engine.workflow.expression import ExpressionEngine

        engine = ExpressionEngine(variables)
        input_mapping = self.node_config.get("input_mapping", {})
        resolved_input = engine.resolve_dict(input_mapping) if isinstance(input_mapping, dict) else {}

        try:
            from app.db.mongodb import get_database
            from app.engine.workflow.engine import WorkflowEngine
            from app.models.task import Task

            db = get_database()

            # Fetch child workflow definition
            child_wf_doc = await db["workflows"].find_one({"_id": workflow_id})
            if child_wf_doc is None:
                return NodeResult(
                    success=False,
                    output={},
                    error_message=f"Workflow {workflow_id} 不存在",
                )

            # Build child task document (in-memory)
            child_task = Task(
                workflow_id=workflow_id,
                input=resolved_input,
                created_by="system",
                created_by_type="system",
                parent_task_id=variables.get("_task_id"),
                call_chain=variables.get("call_chain", []) + [self.node_id],
            )
            child_doc = child_task.model_dump(by_alias=True)

            # Execute child workflow with timeout
            timeout_ms = self.node_config.get("timeout_ms", 600000)
            child_engine = WorkflowEngine()
            try:
                child_output = await asyncio.wait_for(
                    child_engine.execute_task(child_doc, child_wf_doc),
                    timeout=timeout_ms / 1000,
                )
            except TimeoutError:
                return NodeResult(
                    success=False,
                    output={},
                    error_message=f"Subflow 执行超时 ({timeout_ms}ms)",
                )

            # Map results using result_mapping against child variable pool
            result_mapping = self.node_config.get("result_mapping", {})
            if result_mapping and child_engine._pool is not None:
                child_vars = child_engine._pool.get_all()
                child_expr_engine = ExpressionEngine(child_vars)
                resolved_result = child_expr_engine.resolve_dict(result_mapping)
            else:
                resolved_result = child_output

            return NodeResult(
                success=True,
                output={
                    "child_task_id": child_doc["_id"],
                    "child_output": resolved_result,
                    "workflow_id": workflow_id,
                },
            )
        except Exception as exc:
            logger.error("node_subflow_failed", node_id=self.node_id, error=str(exc))
            return NodeResult(
                success=False,
                output={},
                error_message=f"Subflow 执行失败: {exc}",
            )


# ── Factory ──

_NODE_EXECUTOR_MAP: dict[str, type[BaseNodeExecutor]] = {
    "start": StartNodeExecutor,
    "end": EndNodeExecutor,
    "agent": AgentNodeExecutor,
    "tool": ToolNodeExecutor,
    "gateway": GatewayNodeExecutor,
    "human": None,  # lazy-loaded in get_node_executor to avoid circular import
    "parallel": ParallelNodeExecutor,
    "subflow": SubflowNodeExecutor,
}

# Lazy import cache
_human_executor_cls: type[BaseNodeExecutor] | None = None


def get_node_executor(node_type: str, node_id: str, node_config: dict[str, Any]) -> BaseNodeExecutor:
    """Factory: return the appropriate executor for *node_type*.

    Raises ``ValueError`` for unknown node types.
    """
    cls = _NODE_EXECUTOR_MAP.get(node_type)
    if cls is None and node_type != "human":
        raise ValueError(f"未知的节点类型: {node_type}")

    if node_type == "human":
        global _human_executor_cls
        if _human_executor_cls is None:
            from app.engine.workflow.nodes.human import HumanNodeExecutor
            _human_executor_cls = HumanNodeExecutor
        return _human_executor_cls(node_id=node_id, node_config=node_config)

    return cls(node_id=node_id, node_config=node_config)  # type: ignore[return-value]
