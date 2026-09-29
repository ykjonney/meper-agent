"""ExecutionRecorder — 一次执行的过程事件记录器（execution_log.events 的事实源）。

设计（P0-2 修订版,对齐 penguin-harness trace 的"过程账"思路,但落地为
execution_log 内嵌 capped 数组,不新增存储系统）：

- **只记过程,不记内容**：工具结果只有 size、参数只有 ≤200B 预览——正文
  归 messages/checkpointer,与本 collection 的审计定位互补而非重复。
- **单一事实源**：事件由 recorder 统一产出；request 边界/逐请求 token/
  工具耗时都在这里,顶层指标与之同源（RecorderMiddleware 与 UsageMiddleware
  观察同一组钩子）。
- **有界**：≤500 条 / 序列化 ≤16KB；超限时从**中段**丢 tool_call/tool_result
  （保首尾——开头看装配、结尾看结局）,并追加 events_truncated 自声明。

时间语义：``t`` 为相对 recorder 创建（≈run 开始）的毫秒偏移——省空间且
时序可读；绝对时间以文档 timestamp 为准。

事件词汇表（9 种,详见各方法 docstring）：
tools_resolved / request_begin / request_end / tool_call / tool_result /
interrupt / compaction / error / events_truncated。
"""
from __future__ import annotations

import json
import time
from typing import Any

from loguru import logger

#: 事件条数上限（兜底;序列化上限才是主约束）。
CAP_EVENTS = 500

#: 序列化字节上限（UTF-8）。
CAP_BYTES = 16 * 1024

#: tool_call 参数预览 / error 消息预览的字符上限。
PREVIEW_CHARS = 200

#: tools_resolved 里工具名单上限（防超长 agent）。
TOOLS_LIST_MAX = 30

#: 通用异常经 tool_wrapper 转错误 ToolMessage 时的固定前缀（ok 嗅探用;
#: ToolException 业务错误无统一前缀,只能 best-effort 标 ok=True）。
_TOOL_ERROR_PREFIX = "Error executing tool:"


class ExecutionRecorder:
    """进程内收集一次执行的过程事件,finalize() 产出 capped 事件列表。

    生命周期：resolve_harness_context 创建 → RecorderMiddleware/压缩
    formatter/调用方中途 mark → _record_execution_log 补 error/cancelled
    终态并 finalize → 随 write_log 落库。finalize 后再 mark 静默忽略。
    """

    def __init__(self) -> None:
        self._t0 = time.monotonic()
        self._events: list[dict[str, Any]] = []
        self._finalized: list[dict[str, Any]] | None = None
        self._req_i = 0
        self._llm_start: float | None = None
        self._tool_starts: dict[str, float] = {}

    # ── 基础 ──

    def _now_ms(self) -> int:
        return int((time.monotonic() - self._t0) * 1000)

    def mark(self, e: str, **fields: Any) -> None:
        """追加一条事件（finalize 后静默忽略——终态已定格）。"""
        if self._finalized is not None:
            return
        self._events.append({"t": self._now_ms(), "e": e, **fields})

    @property
    def events(self) -> list[dict[str, Any]]:
        """原始事件列表（未 cap,测试/调试用）。"""
        return self._events

    # ── 语义化标记（RecorderMiddleware / 装配层 / 收尾层调用）──

    def tools_resolved(
        self,
        ctx: str,
        model: str,
        tool_names: list[str],
        load_errors: list[dict] | None = None,
    ) -> None:
        """工具装配结果——哪些工具可用、哪些加载失败（排障第一现场）。"""
        self.mark(
            "tools_resolved",
            ctx=ctx,
            model=model,
            tools=tool_names[:TOOLS_LIST_MAX],
            load_errors=[
                {"tool": err.get("tool_name", ""), "error": str(err.get("error", ""))[:PREVIEW_CHARS]}
                for err in (load_errors or [])[:5]
            ],
        )

    def request_begin(self) -> None:
        """一次 LLM 请求开始（RecorderMiddleware.before_llm）。"""
        self._req_i += 1
        self._llm_start = time.monotonic()
        self.mark("request_begin", i=self._req_i)

    def request_end(self, in_tok: int = 0, out_tok: int = 0) -> None:
        """一次 LLM 请求结束（RecorderMiddleware.after_llm,token 为本请求值）。"""
        dur = (
            int((time.monotonic() - self._llm_start) * 1000)
            if self._llm_start is not None
            else 0
        )
        self._llm_start = None
        self.mark(
            "request_end",
            i=self._req_i,
            status="completed",
            dur=dur,
            in_tok=int(in_tok or 0),
            out_tok=int(out_tok or 0),
        )

    def tool_call(self, tcid: str, name: str, args: Any = None) -> None:
        """一次工具调用（RecorderMiddleware.before_tool,args 只留预览）。"""
        self._tool_starts[tcid] = time.monotonic()
        self.mark(
            "tool_call",
            id=tcid,
            n=name,
            args=str(args)[:PREVIEW_CHARS] if args is not None else "",
        )

    def tool_result(self, tcid: str, name: str, content: str) -> None:
        """工具结果元数据（after_tool 只有 content 字符串,ok 为 best-effort
        嗅探:通用异常有固定前缀,ToolException 业务错误无统一前缀）。"""
        start = self._tool_starts.pop(tcid, None)
        dur = int((time.monotonic() - start) * 1000) if start is not None else 0
        self.mark(
            "tool_result",
            id=tcid,
            n=name,
            dur=dur,
            ok=not content.startswith(_TOOL_ERROR_PREFIX),
            size=len(content),
        )

    def interrupt(self, kind: str) -> None:
        """人机协同中断/用户取消（clarification | app_authorization | cancelled）。"""
        self.mark("interrupt", kind=kind)

    def compaction(self, level: str, **fields: Any) -> None:
        """上下文压缩发生（level=tool_output 时由压缩 formatter 触发,
        before 为原文长度,原文已归档可用 recall_tool_result 回取）。"""
        self.mark("compaction", level=level, **fields)

    def error(self, source: str, msg: str, code: str = "") -> None:
        """执行失败（source: llm | graph | tool;code 为稳定错误码预留）。"""
        self.mark("error", source=source, code=code, msg=str(msg)[:PREVIEW_CHARS])

    # ── 收尾 ──

    def finalize(self) -> list[dict[str, Any]]:
        """产出 capped 事件列表（幂等;多次调用返回同一结果）。"""
        if self._finalized is None:
            self._finalized = self._enforce_cap(self._events)
        return self._finalized

    def _enforce_cap(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """超限时从中段丢 tool_call/tool_result,保首尾,自声明 dropped 数。"""
        result = list(events)

        def _bytes() -> int:
            return len(json.dumps(result, ensure_ascii=False, default=str).encode())

        dropped = 0
        while (len(result) > CAP_EVENTS or _bytes() > CAP_BYTES) and (
            droppable := [
                i for i, ev in enumerate(result)
                if ev.get("e") in ("tool_call", "tool_result")
            ]
        ):
            # 中段优先丢（保首尾：开头看装配,结尾看结局）。
            result.pop(droppable[len(droppable) // 2])
            dropped += 1

        if dropped:
            last_t = result[-1]["t"] if result else 0
            result.append({"t": last_t, "e": "events_truncated", "dropped": dropped})
            logger.debug("execution_events_truncated", dropped=dropped)
        return result


__all__ = ["ExecutionRecorder", "CAP_EVENTS", "CAP_BYTES"]
