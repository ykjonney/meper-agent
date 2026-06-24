"""REACT reasoning executor — reasoning + acting loop with tool calling.

The REACT executor implements the Reasoning + Acting pattern:
calls the LLM, checks for tool_calls, executes matching tools,
appends results as ToolMessages, and loops until the LLM produces
a final text response or the iteration limit is reached.
"""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_core.tools import StructuredTool
from loguru import logger

from app.engine.agent.context import (
    compress_messages,
    extract_model_name,
    should_compress,
)
from app.engine.agent.depth_guard import check_depth
from app.engine.state import AgentState

_MAX_ITERATIONS = 25


async def run(
    state: AgentState,
    llm: BaseChatModel,
    tools: list[Callable],
    context_window: int | None = None,
) -> dict:
    """Execute the Agent in REACT mode (reasoning + acting loop).

    Args:
        state: Current AgentState with messages to send to the LLM.
        llm: Configured LangChain chat model instance.
        tools: List of callables available for the LLM to invoke.
        context_window: Optional context window size override. When
            provided, used instead of the hardcoded table lookup.

    Returns:
        Updated state with accumulated messages, tool results, and
        step_count incremented for each LLM call.
    """
    # Set workspace context for tool isolation (read/write path guards)
    from app.engine.agent.builtin_tools import (
        reset_workspace_context,
    )

    ws_token = _setup_workspace_context(state)

    try:
        return await _run_react_inner(state, llm, tools, context_window)
    finally:
        if ws_token is not None:
            reset_workspace_context(ws_token)


async def _run_react_inner(
    state: AgentState,
    llm: BaseChatModel,
    tools: list[Callable],
    context_window: int | None = None,
) -> dict:
    """Inner REACT loop — workspace context is already set by the caller."""
    messages = state.get("messages", [])
    step_count = state.get("step_count", 0)

    # Normalise tools into a name-keyed map
    tool_map = _build_tool_map(tools)

    # Bind tools to LLM so the model can generate tool_calls
    llm_with_tools = llm.bind_tools(list(tool_map.values())) if tool_map else llm

    current_messages = list(messages)
    request_id = state.get("request_id")
    model_name = extract_model_name(llm)

    for iteration in range(_MAX_ITERATIONS):
        # Depth & cycle guard — terminate early when limits are exceeded
        depth_result = check_depth(state)
        if not depth_result.allowed:
            log_event = (
                "circular_call_detected"
                if depth_result.cycle is not None
                else "depth_limit_exceeded"
            )
            logger.warning(
                log_event,
                agent_id=state.get("agent_id"),
                request_id=request_id,
                current_depth=depth_result.current_depth,
                max_depth=depth_result.max_depth,
                call_chain=state.get("call_chain", []),
                reason=depth_result.reason,
                cycle=depth_result.cycle,
            )
            return {
                **state,
                "messages": current_messages,
                "step_count": step_count,
                "error": depth_result.reason,
            }

        # Compress if approaching the model's context window limit
        if should_compress(
            current_messages, model_name, context_window=context_window
        ):
            previous_count = len(current_messages)
            logger.bind(
                agent_id=state.get("agent_id"),
                request_id=request_id,
                iteration=iteration,
            ).info("react_compressing_context", before=previous_count)
            current_messages = compress_messages(
                current_messages, model_name, context_window=context_window
            )
            logger.bind(
                agent_id=state.get("agent_id"),
                request_id=request_id,
                iteration=iteration,
            ).info(
                "react_context_compressed",
                before=previous_count,
                after=len(current_messages),
            )

        response = await llm_with_tools.ainvoke(current_messages)
        step_count += 1

        # No tool calls → final answer
        if not _has_tool_calls(response):
            logger.bind(
                agent_id=state.get("agent_id"),
                request_id=request_id,
                iteration=iteration,
            ).info("react_executor_completed")
            current_messages.append(response)
            return _build_result(state, current_messages, step_count)

        # Tool call round
        current_messages.append(response)

        for tc in response.tool_calls:
            tool_name = tc.get("name", "")
            tool_args = _unwrap_raw_arguments(tc.get("args", {}))
            tool_call_id = tc.get("id", f"call_{iteration}_{tool_name}")

            tool_fn = tool_map.get(tool_name)
            if tool_fn is None:
                logger.warning(
                    "react_executor_tool_not_found",
                    tool_name=tool_name,
                    request_id=request_id,
                )
                result_content = f"Error: tool '{tool_name}' not found."
            else:
                try:
                    result_content = await _execute_tool(tool_fn, tool_args)
                except Exception as exc:
                    # Log full tool args for debugging (Pydantic validation
                    # errors often truncate the input value, hiding the real
                    # cause — e.g. malformed arguments from the LLM).
                    logger.error(
                        "react_executor_tool_error",
                        tool_name=tool_name,
                        tool_args=tool_args,
                        error=str(exc),
                        request_id=request_id,
                    )
                    result_content = f"Error executing tool '{tool_name}': {exc}"

            current_messages.append(
                ToolMessage(content=str(result_content), tool_call_id=tool_call_id)
            )

    # Max iterations reached without a final text response
    logger.warning(
        "react_executor_max_iterations",
        max_iterations=_MAX_ITERATIONS,
        request_id=request_id,
    )
    return _build_result(state, current_messages, step_count)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _setup_workspace_context(state: AgentState):
    """Set the workspace context var from AgentState, returning a reset token.

    Returns ``None`` if no workspace could be resolved.
    """
    session_id = state.get("session_id", "")
    user_id = state.get("user_id", "")
    if not session_id or not user_id:
        return None

    try:
        from app.engine.agent.builtin_tools import set_workspace_context
        from app.engine.tool.workspace import WorkspaceManager

        ws = WorkspaceManager.get_workspace(user_id, session_id)
        # Ensure workspace exists (idempotent)
        ws.input_dir.mkdir(parents=True, exist_ok=True)
        ws.output_dir.mkdir(parents=True, exist_ok=True)
        ws.tmp_dir.mkdir(parents=True, exist_ok=True)
        return set_workspace_context(ws)
    except Exception as exc:
        logger.warning("workspace_context_setup_failed", error=str(exc))
        return None


def _build_tool_map(tools: list[Callable]) -> dict[str, StructuredTool]:
    """Convert a list of callables into a name -> StructuredTool map."""
    return {fn.name: fn for fn in tools if isinstance(fn, StructuredTool)}


def _unwrap_raw_arguments(args: Any) -> Any:
    """Unwrap DashScope/Anthropic-compat ``raw_arguments`` wrapper.

    Some LLM providers (notably Qwen via DashScope's Anthropic-compatible
    endpoint) serialise tool-call arguments as a single ``raw_arguments``
    key containing a JSON string, e.g.::

        {"raw_arguments": '{"path": "report.csv", "content": "..."}'}

    instead of the expected structured dict.  This helper detects the
    pattern and parses the inner JSON string back into a proper dict.

    The inner string may contain literal newlines or other control
    characters that are invalid in strict JSON, so we sanitise them
    before parsing.

    Returns *args* unchanged when the pattern does not match or parsing
    fails.
    """
    if not isinstance(args, dict):
        return args
    if set(args.keys()) != {"raw_arguments"}:
        return args
    raw = args["raw_arguments"]
    if not isinstance(raw, str):
        return args

    parsed = _try_parse_raw_json(raw)
    if isinstance(parsed, dict):
        return parsed
    return args


def _try_parse_raw_json(raw: str) -> Any:
    """Try to parse *raw* as JSON, tolerating control chars and truncation.

    LLM-generated JSON strings may have:
    - Unescaped literal newlines / tabs inside string values
    - Truncation due to ``max_tokens`` being reached mid-generation,
      leaving strings and brackets unclosed

    We first sanitise control characters, then attempt to repair
    truncation by closing any open strings and brackets.
    """
    # Fast path: strict parse
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass

    # Step 1: escape literal control chars (walk char-by-char to preserve
    # valid backslash escape sequences).
    parts: list[str] = []
    i = 0
    while i < len(raw):
        c = raw[i]
        if c == "\\" and i + 1 < len(raw):
            parts.append(c)
            parts.append(raw[i + 1])
            i += 2
        elif ord(c) < 0x20:
            if c == "\n":
                parts.append("\\n")
            elif c == "\r":
                parts.append("\\r")
            elif c == "\t":
                parts.append("\\t")
            else:
                parts.append(f"\\u{ord(c):04x}")
            i += 1
        else:
            parts.append(c)
            i += 1

    sanitised = "".join(parts)

    # Step 2: try strict parse after control-char fix
    try:
        return json.loads(sanitised)
    except (json.JSONDecodeError, ValueError):
        pass

    # Step 3: repair truncated JSON — close unclosed strings and brackets.
    repaired = _repair_truncated_json(sanitised)
    try:
        return json.loads(repaired)
    except (json.JSONDecodeError, ValueError):
        return None


def _repair_truncated_json(s: str) -> str:
    """Close unclosed strings and brackets in a truncated JSON string.

    Walks *s* tracking the nesting stack.  If the string ends while
    inside an open string or object/array, we append the necessary
    closing characters to make it valid JSON.
    """
    stack: list[str] = []  # stack of '{', '[', '"'
    in_string = False
    i = 0
    while i < len(s):
        c = s[i]
        if in_string:
            if c == "\\":
                i += 2  # skip escape sequence
                continue
            if c == '"':
                in_string = False
                if stack and stack[-1] == '"':
                    stack.pop()
        else:
            if c == '"':
                in_string = True
                stack.append('"')
            elif c == "{":
                stack.append("{")
            elif c == "[":
                stack.append("[")
            elif c == "}":
                if stack and stack[-1] == "{":
                    stack.pop()
            elif c == "]":
                if stack and stack[-1] == "[":
                    stack.pop()
        i += 1

    # If we're still inside a string, close it
    suffix = ""
    if in_string:
        suffix += '"'
        if stack and stack[-1] == '"':
            stack.pop()

    # Close any open brackets (reverse order)
    for opener in reversed(stack):
        if opener == "{":
            suffix += "}"
        elif opener == "[":
            suffix += "]"
        elif opener == '"':
            suffix += '"'

    return s + suffix


def _has_tool_calls(response: AIMessage) -> bool:
    """Return True when the AIMessage carries at least one tool call."""
    return bool(hasattr(response, "tool_calls") and response.tool_calls)


def _chunk_has_tool_call(chunk: AIMessageChunk) -> bool:
    """Return True when the chunk contains tool call data (partial or complete)."""
    # LangChain's AIMessageChunk has tool_call_chunks for streaming tool calls
    if hasattr(chunk, "tool_call_chunks") and chunk.tool_call_chunks:
        return True
    # Some providers put tool calls in additional_kwargs
    if hasattr(chunk, "additional_kwargs"):
        kwargs = chunk.additional_kwargs or {}
        if "tool_calls" in kwargs and kwargs["tool_calls"]:
            return True
    return False


async def _execute_tool(tool_fn: StructuredTool, args: dict) -> str:
    """Invoke *tool_fn* with *args*; supports sync and async tools.

    Handles ``response_format="content_and_artifact"`` tools (used by
    ``langchain_mcp_adapters``) which return ``(content_list, artifact)``
    tuples instead of plain strings.
    """
    if hasattr(tool_fn, "ainvoke"):
        result = await tool_fn.ainvoke(args)
    else:
        result = tool_fn.invoke(args)

    # langchain_mcp_adapters returns (content_list, artifact) tuple
    if getattr(tool_fn, "response_format", "") == "content_and_artifact":
        return _extract_content_artifact_text(result)

    return str(result)


def _extract_content_artifact_text(result: Any) -> str:
    """Extract text from a ``(content_list, artifact)`` tuple.

    ``content_list`` is a list of content blocks, each either a dict
    with ``{"type": "text", "text": "..."}`` or a plain string.
    """
    content, _ = result
    if not isinstance(content, list):
        return str(content)

    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
        else:
            parts.append(str(block))
    return "\n".join(parts)


def _build_result(
    state: AgentState,
    messages: list,
    step_count: int,
) -> dict:
    """Build the output dict with accumulated messages."""
    return {
        **state,
        "messages": messages,
        "step_count": step_count,
    }


# ---------------------------------------------------------------------------
# Streaming executor — yields token-level events for SSE
# ---------------------------------------------------------------------------

# Type alias for the async callback that receives SSE-ready event dicts.
# The callback is invoked for every structured event (thinking, tool_call,
# tool_result, final_answer_delta, final_answer_done) so the caller can
# forward them to the SSE response immediately.
StreamCallback = Callable[[dict], Awaitable[None]]


async def run_streaming(
    state: AgentState,
    llm: BaseChatModel,
    tools: list[Callable],
    on_event: StreamCallback,
    enable_thinking: bool = False,
    context_window: int | None = None,
) -> dict:
    """Execute the REACT loop with token-level streaming.

    Unlike :func:`run`, this variant streams the LLM's final-answer
    text chunk-by-chunk through ``on_event`` so the caller can push
    incremental ``final_answer_delta`` events to an SSE response.
    Structured events (``thinking``, ``tool_call``, ``tool_result``)
    are also emitted via the callback.

    The overall REACT control flow (depth guard, context compression,
    iteration limit) mirrors :func:`run`.
    """
    # Set workspace context for tool isolation (read/write path guards)
    from app.engine.agent.builtin_tools import (
        reset_workspace_context,
    )

    ws_token = _setup_workspace_context(state)

    try:
        return await _run_streaming_inner(
            state, llm, tools, on_event, enable_thinking, context_window,
        )
    finally:
        if ws_token is not None:
            reset_workspace_context(ws_token)


async def _run_streaming_inner(
    state: AgentState,
    llm: BaseChatModel,
    tools: list[Callable],
    on_event: StreamCallback,
    enable_thinking: bool = False,
    context_window: int | None = None,
) -> dict:
    """Inner streaming REACT loop — workspace context is already set."""
    messages = state.get("messages", [])
    step_count = state.get("step_count", 0)
    tool_map = _build_tool_map(tools)

    # Bind tools to LLM so the model can generate tool_calls
    llm_with_tools = llm.bind_tools(list(tool_map.values())) if tool_map else llm

    current_messages = list(messages)
    request_id = state.get("request_id")
    model_name = extract_model_name(llm)

    for iteration in range(_MAX_ITERATIONS):
        # Depth & cycle guard
        depth_result = check_depth(state)
        if not depth_result.allowed:
            logger.warning(
                "react_stream_depth_blocked",
                agent_id=state.get("agent_id"),
                request_id=request_id,
                reason=depth_result.reason,
            )
            return {
                **state,
                "messages": current_messages,
                "step_count": step_count,
                "error": depth_result.reason,
            }

        # Compress if approaching the model's context window limit
        if should_compress(
            current_messages, model_name, context_window=context_window
        ):
            previous_count = len(current_messages)
            logger.info(
                "react_stream_compressing",
                request_id=request_id,
                before=previous_count,
            )
            current_messages = compress_messages(
                current_messages, model_name, context_window=context_window
            )

        # Stream LLM output token-by-token
        collected_chunks: list[AIMessageChunk] = []
        streaming_text_parts: list[str] = []
        streaming_thinking_parts: list[str] = []
        tool_call_started = False  # Track if we've emitted tool_call_start

        logger.info(
            "react_stream_llm_start",
            request_id=request_id,
            iteration=iteration,
            model=model_name,
            msg_count=len(current_messages),
            tool_map_keys=list(tool_map.keys()),
        )

        async for chunk in llm_with_tools.astream(current_messages):
            collected_chunks.append(chunk)

            # Detect tool call start — emit event immediately so frontend shows feedback
            if not tool_call_started and _chunk_has_tool_call(chunk):
                tool_call_started = True
                await on_event({"type": "tool_call_start"})

            # Emit thinking deltas when enabled
            if enable_thinking:
                for piece in _iter_chunk_blocks(chunk):
                    if piece.get("type") == "thinking":
                        delta = piece.get("thinking") or ""
                        if delta:
                            streaming_thinking_parts.append(delta)
                            await on_event({
                                "type": "thinking_delta",
                                "content": delta,
                            })
            # Text content delta
            text_delta = _extract_chunk_text(chunk)
            if text_delta:
                streaming_text_parts.append(text_delta)
                await on_event({
                    "type": "final_answer_delta",
                    "content": text_delta,
                })

        step_count += 1

        # Merge chunks into a single AIMessage for tool-call inspection
        if collected_chunks:
            merged: AIMessageChunk = collected_chunks[0]
            for c in collected_chunks[1:]:
                merged = merged + c
            response: AIMessage = AIMessage(
                content=merged.content,
                tool_calls=merged.tool_calls or [],
                additional_kwargs=merged.additional_kwargs or {},
            )
        else:
            response = AIMessage(content="")

        # ── DEBUG: inspect merged response ──
        logger.info(
            "react_stream_merged",
            request_id=request_id,
            iteration=iteration,
            chunks=len(collected_chunks),
            has_tool_calls=_has_tool_calls(response),
            tool_calls=response.tool_calls,
            additional_kwargs_keys=list((response.additional_kwargs or {}).keys()),
            content_preview=str(response.content)[:300] if response.content else "",
            text_parts=len(streaming_text_parts),
            thinking_parts=len(streaming_thinking_parts),
        )

        # Emit a consolidated thinking event if we captured any
        if enable_thinking and streaming_thinking_parts:
            await on_event({
                "type": "thinking",
                "content": "".join(streaming_thinking_parts),
            })

        # No tool calls → this is the final answer
        if not _has_tool_calls(response):
            final_text = "".join(streaming_text_parts)
            await on_event({
                "type": "final_answer",
                "content": final_text,
            })
            current_messages.append(response)
            logger.info(
                "react_stream_completed",
                request_id=request_id,
                iteration=iteration,
            )
            return _build_result(state, current_messages, step_count)

        # Tool call round — persist intermediate text so it survives history reload
        intermediate_text = "".join(streaming_text_parts)
        if intermediate_text:
            await on_event({
                "type": "final_answer",
                "content": intermediate_text,
            })

        current_messages.append(response)

        # Emit tool_call events for each call
        for tc in response.tool_calls:
            tool_name = tc.get("name", "")
            tool_args = _unwrap_raw_arguments(tc.get("args", {}))
            await on_event({
                "type": "tool_call",
                "tool_name": tool_name,
                "args": tool_args,
            })

            tool_call_id = tc.get("id", f"call_{iteration}_{tool_name}")
            tool_fn = tool_map.get(tool_name)
            if tool_fn is None:
                logger.warning(
                    "react_stream_tool_not_found",
                    tool_name=tool_name,
                    request_id=request_id,
                )
                result_content = f"Error: tool '{tool_name}' not found."
            else:
                try:
                    result_content = await _execute_tool(tool_fn, tool_args)
                except Exception as exc:
                    logger.error(
                        "react_stream_tool_error",
                        tool_name=tool_name,
                        tool_args=tool_args,
                        error=str(exc),
                        request_id=request_id,
                    )
                    result_content = f"Error executing tool '{tool_name}': {exc}"

            current_messages.append(
                ToolMessage(content=str(result_content), tool_call_id=tool_call_id)
            )
            await on_event({
                "type": "tool_result",
                "tool_name": tool_name,
                "content": str(result_content),
            })

    logger.warning(
        "react_stream_max_iterations",
        max_iterations=_MAX_ITERATIONS,
        request_id=request_id,
    )
    return _build_result(state, current_messages, step_count)


def _extract_chunk_text(chunk: Any) -> str:
    """Extract the text delta from a streaming AIMessageChunk.

    Handles plain-string content and list-of-blocks content.
    """
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item.get("text") or "")
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    return ""


def _iter_chunk_blocks(chunk: Any) -> list[dict]:
    """Yield content blocks from a streaming chunk as dicts with a ``type`` key."""
    blocks: list[dict] = []
    content = getattr(chunk, "content", None)
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                blocks.append(item)
            else:
                btype = getattr(item, "type", None)
                if btype == "thinking":
                    blocks.append({
                        "type": "thinking",
                        "thinking": getattr(item, "thinking", ""),
                    })
    return blocks
