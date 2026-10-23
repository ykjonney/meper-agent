"""LLM + compress graph nodes for the node-based agent graph.

These replace the monolithic ``react_node`` for循环 with two independent
nodes wired by LangGraph edges:

* ``compress_node`` — context-window compression (runs before each LLM call).
* ``llm_node`` — single LLM invocation (binds tools, runs middleware hooks).

Tool execution is handled by the native ``langgraph.prebuilt.ToolNode``;
this module only owns the LLM-side and compression-side nodes.
"""

from typing import TYPE_CHECKING, Any, cast

import structlog
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from agent_flow_harness.context_engineering.interruption import annotate_interruptions
from agent_flow_harness.context_engineering.pairing import ensure_tool_pairing
from agent_flow_harness.engine.context import extract_model_name
from agent_flow_harness.engine.depth_guard import check_depth
from agent_flow_harness.middleware.chain import MiddlewareChain

if TYPE_CHECKING:
    from agent_flow_harness.state import AgentState

logger = structlog.get_logger(__name__)

# 输出截断的 finish_reason 取值：OpenAI 兼容端点为 "length"，Anthropic 为
# "max_tokens"（落在 response_metadata.stop_reason）。
_TRUNCATED_FINISH_REASONS = frozenset({"length", "max_tokens"})

# 「有进展」判定：同步摘要后 token 降幅至少要达到其一（绝对值或比例），
# 否则计为无进展（固定占用过大导致摘要压不动 → 计数熔断防 thrashing）。
_MIN_SUMMARY_PROGRESS_TOKENS = 2000
_MIN_SUMMARY_PROGRESS_RATIO = 0.05


def _finish_reason(response: AIMessage) -> str | None:
    """提取本次调用的结束原因（OpenAI finish_reason / Anthropic stop_reason）。"""
    meta = getattr(response, "response_metadata", None) or {}
    reason = meta.get("finish_reason") or meta.get("stop_reason")
    return str(reason) if reason else None


def _is_output_truncated(response: AIMessage) -> bool:
    """输出是否因达到 max_tokens 上限被截断。"""
    return _finish_reason(response) in _TRUNCATED_FINISH_REASONS


def _configurable(config: RunnableConfig | None) -> dict[str, Any]:
    """Return ``config["configurable"]`` as a dict, raising a clear error."""
    if config is None:
        msg = "node requires a RunnableConfig with a 'configurable' mapping."
        raise ValueError(msg)
    configurable = config.get("configurable")
    if not isinstance(configurable, dict):
        msg = "config['configurable'] must be a dict."
        raise ValueError(msg)
    return configurable


async def compress_node(
    state: "AgentState",
    config: RunnableConfig,
) -> dict[str, Any]:
    """Compress conversation history when approaching the context-window limit.

    Runs before every LLM call so the model never exceeds its token budget.

    Cancel gate: when an optional ``cancel_checker`` async callable is provided
    in ``configurable`` and returns ``True``, this node calls LangGraph
    ``interrupt()`` to gracefully suspend the REACT loop. The full
    conversation context (messages, tool results, step_count) is persisted
    by the checkpointer; resuming with ``Command(resume=...)`` replays this
    node, ``interrupt()`` returns the resume value, and the loop continues
    with full context continuity.
    """
    configurable = _configurable(config)

    # ── Cancel gate — runs at the top of every REACT iteration ──
    cancel_checker = configurable.get("cancel_checker")
    if cancel_checker is not None and await cancel_checker():
        from langgraph.types import interrupt

        interrupt({"reason": "cancelled"})
        # interrupt() returns the resume value on resume; fall through to
        # normal compression (the REACT loop continues with full context).

    context_window: int | None = configurable.get("context_window")
    llm = configurable.get("llm")
    # 压缩配置(全局可配,有默认值)。
    protected_turns: int = configurable.get("protected_turns", 5)
    compression_threshold: float = configurable.get("compression_threshold", 0.7)
    hard_limit_ratio: float = configurable.get("hard_limit_ratio", 0.9)
    session_id: str = state.get("session_id", "")

    current_messages: list[Any] = list(state.get("messages", []))

    # ── system 收敛：同 thread 跨 invoke（chat 多轮 / loop continue）时，
    #    每次 invoke 都新传一条 SystemMessage，add_messages 按 id 追加 →
    #    thread 内累积 N 条重复 system，而 system 永不压缩（契约约束），
    #    N 轮即 N 倍 system 开销。收敛规则：保留最后一条（最新 invoke
    #    传入——内容变化时也拿到最新），RemoveMessage 移除更早的。
    #    豁免 id=llm_summary/summary 的旧版摘要消息——它们是语义内容
    #    （走下方 B.3-3 迁移为 HumanMessage），不是重复 system。
    #    单条时零操作（幂等，每次 REACT 迭代仅首个循环生效）。──
    _SUMMARY_MSG_IDS = ("llm_summary", "summary")
    system_ids = [
        m.id
        for m in current_messages
        if isinstance(m, SystemMessage)
        and getattr(m, "id", None)
        and m.id not in _SUMMARY_MSG_IDS
    ]
    if len(system_ids) > 1:
        stale_system_ids = set(system_ids[:-1])
        current_messages = [
            m for m in current_messages
            if not (
                isinstance(m, SystemMessage)
                and getattr(m, "id", None) in stale_system_ids
            )
        ]
        logger.info(
            "duplicate_system_messages_deduped",
            agent_id=state.get("agent_id"),
            request_id=state.get("request_id"),
            removed=len(stale_system_ids),
        )
        return _pack_replace(current_messages)

    # ── token 评估:优先用 input_tokens(模型真实值),fallback len//4 ──
    from agent_flow_harness.engine.context import (
        estimate_context_tokens,
        get_context_window,
    )

    model_name = extract_model_name(llm) if llm is not None else ""
    window = context_window or get_context_window(model_name)
    threshold_tokens = int(window * compression_threshold)
    before_tokens = estimate_context_tokens(current_messages)

    # ── 中断标注：新一轮开始时检测上一轮是否被中断，注入显式标记。
    #    在所有路径分叉之前执行；标注变更必须强制产生替换补丁，
    #    否则未达压缩阈值时标记不会写入 thread。──
    annotate_changed = False
    current_messages, intr = annotate_interruptions(current_messages)
    if intr.get("changed"):
        annotate_changed = True
        logger.info(
            "interruption_annotated",
            agent_id=state.get("agent_id"),
            request_id=state.get("request_id"),
            case=intr.get("case", ""),
        )

    # ── 内置路径:分级工具压缩 + 同步LLM摘要(熔断) + 丢弃兜底 ──
    result, detail = await _compress_by_turns(
        current_messages,
        window,
        protected_turns,
        compression_threshold,
        hard_limit_ratio,
        llm,
        session_id,
        config,
        state,
    )

    # ── 固定占用检查:system + 任务指令是压缩管线永不动不了的部分,
    #    超窗时 ③④⑤ 全做完也放不下 → 明确报错(取代含混的 provider 400)。
    #    必须在压缩【之后】:先压历史,仍放不下才是真放不下。
    history_mutated = bool(detail.get("changed")) or annotate_changed
    _check_oversized_prompt(
        result, window, state, compression_threshold=compression_threshold,
    )
    # ── 单个工具结果超过窗口 → 报错。必须在压缩【之后】判定:先压已消费
    # 历史,budget 转正即放行;此时仍放不下才是真放不下(未消费结果无法
    # 压缩)。此前检查在压缩前执行,压缩明明救得回来却直接报错。
    # 压缩改写过历史 → 旧 usage 基准失效,估算需全量重算(prefer_usage=False)。
    _check_oversized_tool_result(
        result, window, state, prefer_usage=not history_mutated
    )

    if detail["changed"] or annotate_changed:
        logger.info(
            "compress_done",
            agent_id=state.get("agent_id"),
            request_id=state.get("request_id"),
            actions=detail.get("actions", ""),
            tokens_before=before_tokens,
            tokens_after=estimate_context_tokens(
                result, prefer_usage=not history_mutated
            ),
            threshold_tokens=threshold_tokens,
            messages_before=len(current_messages),
            messages_after=len(result),
            compact_count=detail.get("compact_count", 0),
        )
        return _pack_replace(result)

    logger.info(
        "compress_skipped",
        agent_id=state.get("agent_id"),
        request_id=state.get("request_id"),
        tokens=before_tokens,
        threshold_tokens=threshold_tokens,
        messages=len(current_messages),
    )
    return {}


async def llm_node(
    state: "AgentState",
    config: RunnableConfig,
) -> dict[str, Any]:
    """Single LLM invocation with tool-binding and middleware hooks.

    Reads ``llm`` / ``tools`` / ``middlewares`` from ``config["configurable"]``
    (never from global state) so the non-serialisable LLM object stays out of
    the checkpointer. Returns a state patch that appends the AIMessage and
    increments ``step_count``.

    Depth / cycle guard is checked *after* the LLM call; if the guard trips,
    ``error`` is set and the graph routes to END via ``tools_condition`` (no
    tool calls → END).
    """
    configurable = _configurable(config)
    llm = configurable["llm"]
    tools = configurable.get("tools") or []
    chain = MiddlewareChain(configurable.get("middlewares") or [])

    # Bind tools to the LLM.
    tool_list = list(tools.values()) if isinstance(tools, dict) else list(tools)
    llm_with_tools = llm.bind_tools(tool_list) if tool_list else llm

    # Middleware: before_llm (may rewrite messages).
    call_state: AgentState = cast("AgentState", {**state})
    call_state = await chain.run_before_llm(call_state)

    # Defence-in-depth: guarantee all SystemMessages are contiguous at the
    # front before hitting the model. langchain-anthropic rejects any
    # message list whose system messages are split by non-system turns
    # ("Received multiple non-consecutive system messages."). Compression,
    # middleware, or future system-injection points could otherwise scatter
    # them; normalise here as a final guarantee. Only reorders when needed.
    call_state["messages"] = _system_messages_first(call_state["messages"])

    # LLM call.
    response: AIMessage = await llm_with_tools.ainvoke(call_state["messages"])
    step_count: int = state.get("step_count", 0) + 1

    # Middleware: after_llm.
    await chain.run_after_llm(
        cast("AgentState", {**call_state, "step_count": step_count}),
        response,
    )

    # ── Output truncation: detect + bounded feedback retry ─────────────
    # finish_reason=length 且无有效 tool_calls 时（思考/正文被截断，或工具
    # 参数截断落进 invalid_tool_calls），tools_condition 视为"无工具调用"
    # 直接路由 END——对话静默死亡且模型毫无反馈。工具参数截断在流式路径
    # 会被 parse_partial_json 宽松救活（工具照常执行、ToolMessage 反馈兜
    # 底），但严格解析路径的 invalid_tool_calls 还会随消息持久化，下一轮
    # 被序列化回请求触发 400。这里统一补上反馈通道：
    #   ① invalid 调用 → 合成错误 ToolMessage（给模型反馈 + 补齐配对防 400）；
    #   ② 死路（无有效工具调用可走 ToolMessage 通道）→ 注入反馈后原地重调
    #      一次（上限 1 次，防死循环），让模型带着"你被截断了"的信号重试；
    #   ③ 截断但带有效 tool_calls → 放行执行（反馈通道已存在，模型下一轮
    #      可自我补救），仅告警。
    extra_messages: list[Any] = []
    invalid_calls = list(getattr(response, "invalid_tool_calls", None) or [])
    truncated = _is_output_truncated(response)
    if truncated or invalid_calls:
        for call in invalid_calls:
            call_id = call.get("id") if isinstance(call, dict) else None
            if call_id:
                extra_messages.append(
                    ToolMessage(
                        content=(
                            "Error: 该工具调用因输出达到最大长度限制被截断，"
                            "参数不完整，未被执行。请重新发起该调用并精简参数。"
                        ),
                        tool_call_id=call_id,
                    )
                )
        if not response.tool_calls:
            logger.warning(
                "llm_output_truncated",
                agent_id=state.get("agent_id"),
                request_id=state.get("request_id"),
                finish_reason=_finish_reason(response),
                invalid_tool_calls=len(invalid_calls),
                action="retry_with_feedback",
            )
            feedback = HumanMessage(
                content=(
                    "你上一轮输出因达到最大输出长度（max_tokens）限制被截断，没有"
                    "产生完整内容。请压缩思考过程、直接给出完整回复；若需调用工具，"
                    "请大幅精简工具参数后再发起。"
                )
            )
            # 截断响应本身只有在携带信息（正文 / invalid 调用）时才进重试上下
            # 文：空 content 的 AIMessage 对模型无价值，且部分 provider（如
            # Anthropic 空 content / 未签名 thinking 块）会直接 400。
            retry_messages = list(call_state["messages"])
            if invalid_calls or response.content:
                retry_messages.append(response)
            retry_messages.extend(extra_messages)
            retry_messages.append(feedback)
            try:
                retry_response = await llm_with_tools.ainvoke(retry_messages)
            except Exception as exc:
                # 重试本身失败（如 provider 拒绝请求）→ 退化为原行为：保留已
                # 合成的配对 ToolMessage 与反馈，本轮照旧结束，绝不让修复引入
                # 新的硬失败。
                logger.warning(
                    "llm_output_truncation_retry_failed",
                    agent_id=state.get("agent_id"),
                    request_id=state.get("request_id"),
                    error=str(exc),
                )
                return {
                    "messages": [response, *extra_messages, feedback],
                    "step_count": step_count,
                }
            await chain.run_after_llm(
                cast("AgentState", {**call_state, "step_count": step_count}),
                retry_response,
            )
            if _is_output_truncated(retry_response):
                logger.warning(
                    "llm_output_truncated_retry_exhausted",
                    agent_id=state.get("agent_id"),
                    request_id=state.get("request_id"),
                    finish_reason=_finish_reason(retry_response),
                )
            extra_messages.extend([feedback, retry_response])
        else:
            logger.warning(
                "llm_output_truncated",
                agent_id=state.get("agent_id"),
                request_id=state.get("request_id"),
                finish_reason=_finish_reason(response),
                invalid_tool_calls=len(invalid_calls),
                action="pass_through_with_tool_calls",
            )

    # Depth / cycle guard — checked after the call so the AIMessage is still
    # appended (the graph will route to END because there are no tool_calls
    # on the error path... actually we set error and route explicitly).
    depth_result = check_depth(state)
    if not depth_result.allowed:
        logger.warning(
            "circular_call_detected" if depth_result.cycle is not None else "depth_limit_exceeded",
            agent_id=state.get("agent_id"),
            request_id=state.get("request_id"),
            current_depth=depth_result.current_depth,
            max_depth=depth_result.max_depth,
            call_chain=state.get("call_chain", []),
            reason=depth_result.reason,
            cycle=depth_result.cycle,
        )
        return {
            "messages": [response, *extra_messages],
            "step_count": step_count,
            "error": depth_result.reason,
        }

    return {"messages": [response, *extra_messages], "step_count": step_count}


def _system_messages_first(messages: list[Any]) -> list[Any]:
    """Move every SystemMessage to the front, keeping relative order.

    Returns the original list unchanged when the system messages are already
    leading and contiguous (the common case), avoiding a needless copy on the
    hot path.
    """
    from langchain_core.messages import SystemMessage

    from agent_flow_harness.context_engineering.split import split_system_history

    system_msgs, history = split_system_history(messages)
    n = len(system_msgs)
    if n == 0:
        return messages
    # Already leading and contiguous? Skip the rebuild.
    if n <= len(messages) and all(isinstance(m, SystemMessage) for m in messages[:n]):
        return messages
    return [*system_msgs, *history]


def _pack_replace(messages: list[Any]) -> dict[str, Any]:
    """Build a state patch that *replaces* the whole message history.

    Uses ``RemoveMessage(REMOVE_ALL_MESSAGES)`` so the ``add_messages`` reducer
    discards the old history and installs ``messages`` verbatim. Returns ``{}``
    (no-op) when there is nothing to change.
    """
    return {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *messages]}


def _trim_tool_outputs(
    messages: list[Any],
    config: RunnableConfig,
) -> list[Any]:
    """Shrink oversized ToolMessage contents, applying the app-supplied
    reference formatter (so truncated results hint how to recall the original).

    Returns the original list when nothing was trimmed.
    """
    formatter = _configurable(config).get("tool_output_reference_formatter")
    from agent_flow_harness.context_engineering.tool_output import compress_tool_outputs

    result: list[Any] = compress_tool_outputs(messages, reference_formatter=formatter)
    return result


def _check_oversized_tool_result(
    messages: list[Any],
    window: int,
    state: "AgentState",
    *,
    prefer_usage: bool = True,
) -> None:
    """「未消费的」单个工具结果放不下模型窗口时抛 ValueError(转 ErrorEvent 发前端)。

    只检测**未消费**的工具结果。用实际剩余预算判断:
      剩余 = window - 其它消息占用 - 预留回复(4000)
    如果工具结果 > 剩余 → 即使不压缩也放不下 → 报错。

    比之前用固定 70% 阈值更准确:一个占 75% 窗口的工具,如果其它消息很少,
    可能完全放得下,不该报错。

    ``prefer_usage=False``:历史已被压缩改写,旧 usage 基准失效,需全量
    估算(见 estimate_context_tokens)。budget<0 说明其它消息本身就已超窗,
    与本条工具结果大小无关——文案按"上下文超窗"归因,不再误导性地
    指责工具返回过大。
    """
    from langchain_core.messages import ToolMessage

    from agent_flow_harness.context_engineering.tool_output import (
        find_unconsumed_tool_call_ids,
    )
    from agent_flow_harness.engine.context import (
        estimate_context_tokens,
        estimate_message_tokens,
    )

    RESERVED_RESPONSE = 4000
    unconsumed = find_unconsumed_tool_call_ids(messages)
    for m in messages:
        if isinstance(m, ToolMessage) and (m.tool_call_id or "") in unconsumed:
            tool_tokens = estimate_message_tokens(m)
            # 其它消息的 token(排除这个工具结果本身)。
            other_tokens = estimate_context_tokens(
                messages, prefer_usage=prefer_usage
            ) - tool_tokens
            budget = window - other_tokens - RESERVED_RESPONSE
            if tool_tokens > budget:
                tcid = m.tool_call_id or "?"
                tool_name = getattr(m, "name", "") or "未知工具"
                if budget <= 0:
                    msg = (
                        f"会话上下文已超出模型窗口(窗口 {window} tokens,"
                        f"当前历史约 {other_tokens} tokens,已超出 {-budget})。"
                        f"请精简系统提示与工具、开启/等待历史压缩生效,"
                        f"或更换上下文窗口更大的模型。(tool_call_id={tcid})"
                    )
                else:
                    msg = (
                        f"工具 {tool_name} 的返回结果过大(约 {tool_tokens} tokens),"
                        f"剩余上下文空间不足以容纳(剩余约 {budget} tokens)。"
                        f"该工具结果尚未被处理、无法压缩,请减少返回内容"
                        f"(如调小 top_k、缩小查询范围),或使用上下文窗口更大的模型。"
                        f"(tool_call_id={tcid})"
                    )
                logger.error(
                    "compress_tool_result_oversized",
                    agent_id=state.get("agent_id"),
                    request_id=state.get("request_id"),
                    tool_name=tool_name,
                    tool_call_id=tcid,
                    tool_tokens=tool_tokens,
                    budget=budget,
                    window=window,
                    other_tokens=other_tokens,
                )
                raise ValueError(msg)


async def _compress_by_turns(
    messages: list[Any],
    window: int,
    protected_turns: int,
    threshold_ratio: float,
    hard_limit_ratio: float,
    llm: Any,
    session_id: str,
    config: RunnableConfig,
    state: "AgentState",
) -> "tuple[list[Any], dict[str, Any]]":
    """分级工具压缩 + 同步LLM摘要(熔断) + 丢弃兜底。

    返回 (结果消息列表, 详情 dict)。详情字段: changed / actions /
    compact_count (该 session 累计成功摘要次数)。

    规则:
      ② 未达阈值 → 什么都不做。
      ③ 达阈值 → 工具压缩(同步,快):
         第1级: outer(保护窗之外)已消费工具狠截(500字符,有recall兜底,
                老结果回取价值低——对齐 Claude Code microcompact);
         第2级: recent(保护窗内)已消费工具截(1500字符,模型可能马上要用)。
         压完够了就停。
      ④ 工具压完仍超阈值 → 同步LLM摘要(业界对齐:Codex/Gemini CLI/Claude
         Code 全部同步,触发是低频事件不值得为省几秒引入缓存/竞态/持久化
         整套复杂度):当轮 await、当轮回填,outer 整体替换为一条
         HumanMessage(id=llm_summary)。三态熔断器防 thrashing:连续3次
         失败/无进展 → 冷却期内跳过摘要(降级为③+⑤);冷却期满试探恢复。
      ⑤ 逼近硬上限(hard_limit_ratio) → 丢弃最早原始消息防崩溃(最后防线):
         病灶在摘要够不着的(recent+固定占用)或熔断冷却期时才触发。
         跳过锚定任务指令;被丢 HumanMessage 合成占位;保底最后2条。

    绝不生成机械摘要 → 无累积退化。
    """
    from agent_flow_harness.context_engineering.compact_circuit import (
        compact_circuit,
    )
    from agent_flow_harness.context_engineering.llm_summary import (
        build_summary_message,
        run_summary,
    )
    from agent_flow_harness.context_engineering.split import split_system_history
    from agent_flow_harness.context_engineering.tool_output import (
        OUTER_MAX_TOOL_OUTPUT,
        compress_tool_outputs,
        find_unconsumed_tool_call_ids,
    )
    from agent_flow_harness.context_engineering.turns import (
        DEFAULT_MIN_BATCHES,
        DEFAULT_PROTECTED_RATIO,
        split_for_compression,
    )
    from agent_flow_harness.engine.context import estimate_context_tokens

    conf = _configurable(config)
    formatter = conf.get("tool_output_reference_formatter")
    protected_ratio = float(conf.get("protected_ratio") or DEFAULT_PROTECTED_RATIO)
    min_batches = int(conf.get("min_batches") or DEFAULT_MIN_BATCHES)
    threshold = int(window * threshold_ratio)
    hard_limit = int(window * hard_limit_ratio)
    changed = False
    actions_parts: list[str] = []

    # ⓪ 防御性配对安全网：compress_node 入口的中断标注已把尾部孤儿转为
    # "被取消"的 ToolMessage（完整配对）；此处再无条件跑一遍 ensure_tool_pairing，
    # 兜住压缩路径自身可能引入的孤儿（正常对话零改动）。
    paired = ensure_tool_pairing(messages)
    if len(paired) != len(messages):
        logger.info(
            "orphan_tool_calls_stripped",
            session_id=session_id,
            before=len(messages),
            after=len(paired),
            note="state contained unanswered tool_calls (mid-stream cancel / crash)",
        )
        messages = paired
        changed = True
        actions_parts.append("孤儿tool_call清理")
    else:
        messages = paired

    # ⓪-b 旧图降级:protected_turns 外的 image 块换成可回取占位。独立于
    # token 阈值——图片按张计费视觉 token,每轮 LLM 调用都在烧钱,尽早回收。
    # formatter 由应用层注入(harness 不硬编码回看工具名);未注入=功能关闭。
    image_formatter = conf.get("image_reference_formatter")
    if image_formatter is not None:
        from agent_flow_harness.context_engineering.images import (
            downgrade_stale_images,
        )

        keep_recent = int(conf.get("image_keep_recent", 0) or 0)
        messages, degraded_images = downgrade_stale_images(
            messages,
            protected_turns=protected_turns,
            keep_recent=keep_recent,
            formatter=image_formatter,
        )
        if degraded_images:
            changed = True
            actions_parts.append(f"旧图降级×{degraded_images}")
            logger.info(
                "stale_images_downgraded",
                session_id=session_id,
                count=degraded_images,
                keep_recent=keep_recent,
            )

    current = estimate_context_tokens(messages)

    # ② 未达阈值 → 什么都不做。
    if current <= threshold:
        return messages, {"changed": changed, "actions": "+".join(actions_parts)}

    # ③ 达阈值 → 分级工具压缩(同步)。
    system_msgs, history = split_system_history(messages)

    # 摘要迁移（B.3-3）：新的 llm_summary 是 HumanMessage——天然在历史区，
    # 下次压缩自然重吸收（render 以 [此前摘要] 分支喂给摘要 LLM，不再硬丢失）。
    # 存量 SystemMessage 形态的旧摘要仍会被 split_system_history 收进 system 区
    # ——在此迁移为 HumanMessage（保留 id 与内容），交还历史区参与再压缩。
    from langchain_core.messages import HumanMessage as _HumanMessage

    migrated: list[Any] = []
    kept_system: list[Any] = []
    for m in system_msgs:
        if getattr(m, "id", "") in ("llm_summary", "summary"):
            migrated.append(
                _HumanMessage(
                    content=str(m.content),
                    id=getattr(m, "id", "") or "llm_summary",
                )
            )
        else:
            kept_system.append(m)
    if migrated:
        system_msgs = kept_system
        history = [*migrated, *history]

    # 锚定标记:任务指令 = history[0](若为 HumanMessage)。split_for_compression
    # 保证它必在 recent[0],⑤ 丢弃时据此跳过(丢了=失忆,原实现在此丢掉它)。
    anchor_msg = history[0] if history and isinstance(history[0], _HumanMessage) else None

    outer, recent = split_for_compression(
        history,
        protected_turns=protected_turns,
        protected_ratio=protected_ratio,
        min_batches=min_batches,
        context_window=window,
    )

    # 在完整 history 上算一次 unconsumed_ids,传给后续切片的 compress_tool_outputs
    # (切片后 find_unconsumed_tool_call_ids 丢失全局上下文会误判,见 B2 修复)。
    unconsumed_ids = find_unconsumed_tool_call_ids(history)

    # 估算基准管理:usage 基准(last AIMessage.input_tokens)只在历史未被改写
    # 时有效。任何一级压缩实际改动了内容 → 后续估算切换为全量重算
    # (prefer_usage=False),否则旧的大基准会持续虚高预算判断。
    mutated = changed

    # 第1级:outer 内已消费工具狠截(500,老结果回取价值低)。
    outer_orig = list(outer)
    outer = compress_tool_outputs(
        outer,
        max_output=OUTER_MAX_TOOL_OUTPUT,
        reference_formatter=formatter,
        unconsumed_ids=unconsumed_ids,
    )
    mutated = mutated or outer != outer_orig
    combined = [*system_msgs, *outer, *recent]
    if estimate_context_tokens(combined, prefer_usage=not mutated) <= threshold:
        return ensure_tool_pairing(combined), {
            "changed": True, "actions": "outer工具压缩",
            "compact_count": compact_circuit.success_count(session_id),
        }

    # 第2级:recent 内已消费工具压(1500,未消费保护内置)。
    recent_orig = list(recent)
    recent = compress_tool_outputs(
        recent,
        reference_formatter=formatter,
        unconsumed_ids=unconsumed_ids,
    )
    mutated = mutated or recent != recent_orig
    combined = [*system_msgs, *outer, *recent]
    after_tools = estimate_context_tokens(combined, prefer_usage=not mutated)
    if after_tools <= threshold:
        return ensure_tool_pairing(combined), {
            "changed": True, "actions": "recent工具压缩",
            "compact_count": compact_circuit.success_count(session_id),
        }

    # ④ 工具压完仍超阈值 → 同步LLM摘要(三态熔断器门闸:冷却期内跳过)。
    if llm is not None and session_id and outer and compact_circuit.should_try(session_id):
        summary_text = await run_summary(
            llm, outer, reference_formatter=formatter,
        )
        if summary_text is not None:
            # outer 整体替换为一条摘要消息(HumanMessage,历史区,下次可再压缩)。
            outer = [build_summary_message(summary_text)]
            combined = [*system_msgs, *outer, *recent]
            after_summary = estimate_context_tokens(combined, prefer_usage=False)
            progress = after_tools - after_summary
            if (
                progress >= _MIN_SUMMARY_PROGRESS_TOKENS
                or progress >= after_tools * _MIN_SUMMARY_PROGRESS_RATIO
            ):
                compact_circuit.record_success(session_id)
                actions_parts.append(f"LLM摘要(降{progress}tok)")
                if after_summary <= threshold:
                    return ensure_tool_pairing(combined), {
                        "changed": True,
                        "actions": "+".join(actions_parts),
                        "compact_count": compact_circuit.success_count(session_id),
                    }
                # 有进展但未到阈值(固定占用大)→ 带病运行,继续 ⑤ 判定。
            else:
                # 无进展:摘要救不动(固定占用/占用结构问题),计数熔断;
                # 替换结果仍保留(消息更少,能省一点)。
                compact_circuit.record_failure(session_id)
                actions_parts.append("LLM摘要无进展")
        else:
            compact_circuit.record_failure(session_id)
            actions_parts.append("LLM摘要失败")

    # ⑤ 逼近硬上限 → 丢弃最早原始消息防崩溃(最后防线)。
    current_final = estimate_context_tokens(combined, prefer_usage=False)
    if current_final > hard_limit:
        safe_limit = int(window * 0.85)
        # 差量计算:base = system + recent(不可头部丢的部分),循环只减 outer 的 token。
        # 子列表的 usage 基准描述的是完整列表的调用,天然失真 → 全量估算。
        from agent_flow_harness.engine.context import estimate_message_tokens

        def _is_note(m: Any) -> bool:
            # 摘要/占位消息不算"被丢的用户消息"(它们不是用户发言)。
            return getattr(m, "id", "") in ("llm_summary", "llm_discarded_note")

        # 第一步:丢 outer(差量:base 不动,只减 outer)。
        base_tokens = estimate_context_tokens(
            [*system_msgs, *recent], prefer_usage=False
        )
        discard_outer = list(outer)
        outer_tokens = sum(estimate_message_tokens(m) for m in discard_outer)
        while base_tokens + outer_tokens > safe_limit and discard_outer:
            outer_tokens -= estimate_message_tokens(discard_outer.pop(0))
        dropped_humans = sum(
            1
            for m in outer[: len(outer) - len(discard_outer)]
            if isinstance(m, _HumanMessage) and not _is_note(m)
        )
        discarded_count = len(outer) - len(discard_outer)

        body: list[Any] = [*discard_outer, *recent]

        # 第二步:outer 耗尽仍超 → recent 最早的消息也丢弃。安全网(原实现缺失):
        #   ① 锚定任务指令永不丢(原实现从 recent 头部丢,第一个丢的就是它);
        #   ② 保底最后 2 条不丢(未消费的 tool_call/结果对就在尾部,绝不能丢)。
        # 孤儿由收口处 ensure_tool_pairing 清理;仍放不下则由压缩后的
        # oversized 检查报错。
        if not discard_outer and base_tokens > safe_limit and len(recent) > 2:
            sys_tokens = estimate_context_tokens(system_msgs, prefer_usage=False)
            anchor_head: list[Any] = []
            rest = list(recent)
            if anchor_msg is not None and rest and rest[0] is anchor_msg:
                anchor_head.append(rest.pop(0))
            kept = list(rest)
            recent_tokens = base_tokens - sys_tokens
            while len(kept) > 2 and sys_tokens + recent_tokens > safe_limit:
                victim = kept.pop(0)
                recent_tokens -= estimate_message_tokens(victim)
                if isinstance(victim, _HumanMessage) and not _is_note(victim):
                    dropped_humans += 1
            discarded_count += len(recent) - len(anchor_head) - len(kept)
            body = [*anchor_head, *kept]

        # 第三步:被丢 HumanMessage 合成占位(不做纯丢失),插在锚定指令之后。
        if dropped_humans:
            note = _HumanMessage(
                content=(
                    f"[系统提示：{dropped_humans} 条历史用户消息因上下文"
                    f"压力被压缩丢弃]"
                ),
                id="llm_discarded_note",
            )
            insert_at = 0
            if anchor_msg is not None:
                for i, m in enumerate(body):
                    if m is anchor_msg:
                        insert_at = i + 1
                        break
            body.insert(insert_at, note)

        combined = [*system_msgs, *body]
        logger.warning(
            "compress_discard_emergency",
            agent_id=state.get("agent_id"),
            request_id=state.get("request_id"),
            discarded=discarded_count,
            dropped_humans=dropped_humans,
            kept_anchor=anchor_msg is not None,
            note="逼近硬上限,丢弃早期历史防崩溃(最后防线)",
        )
        actions_parts.append("丢弃早期历史(防崩溃)")
        return ensure_tool_pairing(combined), {
            "changed": True,
            "actions": "+".join(actions_parts),
            "compact_count": compact_circuit.success_count(session_id),
        }

    # 压完仍超阈值但没到硬上限:带病运行(固定占用大,prompt_fixed_occupancy_high
    # 告警可观测),本轮用当前消息正常答。
    return ensure_tool_pairing(combined), {
        "changed": True,
        "actions": "+".join(actions_parts),
        "compact_count": compact_circuit.success_count(session_id),
    }


def _check_oversized_prompt(
    messages: list[Any],
    window: int,
    state: "AgentState",
    *,
    compression_threshold: float,
) -> None:
    """「固定占用」检查:system prompt + 锚定任务指令(首条 HumanMessage)。

    这两部分是压缩管线**永不动不了**的固定契约层(system 不参与压缩是
    split.py 的核心安全约束;任务指令锚定见 split_for_compression)——
    超大模板注入(如 {{upstream.response}} 全量引用几万字)没有摘要降级
    出路。此处把问题显性化:

      - 固定占用 + 回复预留超窗 → ValueError,明确归因(精简模板大引用/
        换更大窗口模型),取代含混的 provider 400;
      - 超过压缩阈值但未超窗 → 告警事件(含剩余可支配预算,可观测定位
        是哪个节点的模板注入过大)。

    窗口本身 ≤ 预留(极端小窗测试场景)时跳过——那种情况由
    _check_oversized_tool_result 的超窗归因兜底。
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    from agent_flow_harness.engine.context import estimate_context_tokens

    reserved = 4000  # 与 _check_oversized_tool_result 的 RESERVED_RESPONSE 一致
    if window <= reserved:
        return

    system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
    history = [m for m in messages if not isinstance(m, SystemMessage)]
    fixed: list[Any] = list(system_msgs)
    if history and isinstance(history[0], HumanMessage):
        fixed.append(history[0])

    occupied = estimate_context_tokens(fixed, prefer_usage=False)
    budget = window - reserved
    if occupied > budget:
        msg = (
            f"系统提示与任务指令的固定占用约 {occupied} tokens,加上模型回复"
            f"预留({reserved})后已超过模型上下文窗口({window} tokens)。"
            f"请精简 input_query / input_prompt 模板中对上游大输出的全量引用"
            f"(改用摘要或文件外置),或更换上下文窗口更大的模型。"
        )
        logger.error(
            "prompt_fixed_occupancy_exceeded",
            agent_id=state.get("agent_id"),
            request_id=state.get("request_id"),
            occupied=occupied,
            window=window,
        )
        raise ValueError(msg)

    threshold = int(window * compression_threshold)
    if occupied > threshold:
        logger.warning(
            "prompt_fixed_occupancy_high",
            agent_id=state.get("agent_id"),
            request_id=state.get("request_id"),
            occupied=occupied,
            threshold=threshold,
            window=window,
            dispensable=budget - occupied,
            note="固定占用已超压缩阈值,压缩空间不足,建议精简模板大引用",
        )


__all__ = ["compress_node", "llm_node"]
