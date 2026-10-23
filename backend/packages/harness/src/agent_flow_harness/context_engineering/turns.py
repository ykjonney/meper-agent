"""历史分区 — 把历史切分为「可压缩 outer」与「保护 recent」。

两条切分路径(与 compress_node 配合):

    多轮对话(chat):一个 HumanMessage 开启一轮(它是 turn separator)。
    倒数第 N 个 HumanMessage(含)之后属于「最近 N 轮」(保护窗口);之前
    的属于「N轮之外」(可无条件压缩)。→ ``split_by_turns``(旧接口,保留)。

    agent 长任务(workflow 节点:单 HumanMessage + 几十次工具往返):轮语义
    退化——human 数恒 < N,旧规则退化为「全部保护」,outer 恒空,LLM 摘要
    永不触发。→ ``split_for_compression`` 以「token 预算 + 段边界」切分:
    段 = 一次工具批次(带 tool_calls 的 AIMessage + 其全部 ToolMessages),
    从尾部逐段累计,保护 max(min_batches 批, protected_ratio×window);
    切点 snap 到段边界,配对绝不撕裂。批次 token 方差极大(read 大文件
    vs ls),固定段数会让保护窗大小失控——token 定预算、段定落点。

    锚定(两路径共用):首条 HumanMessage(任务指令)永不留在 outer——
    它是任务全程的目标定义,进了 outer 会被摘要/丢弃覆盖,丢了等于失忆。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

DEFAULT_PROTECTED_TURNS = 5
"""最近多少轮(以 HumanMessage 计)受保护:5轮内的内容不被无条件压缩。"""

DEFAULT_PROTECTED_RATIO = 0.15
"""保护窗 token 预算占窗口的比例(token 定预算;Gemini CLI 保留后缀同款:
窗口的 15%,Codex 固定 20k/200k≈10%——取两家中间,留待真实任务校准)。"""

DEFAULT_MIN_BATCHES = 3
"""最少无条件保护的工具批次数(预算是软目标,下限是硬约束):防止单个
大结果把「正在消费的最小工作集」挤出保护窗(Gemini CLI "protect last
3 tool turns" 同款)。"""


def split_by_turns(
    history: "list[BaseMessage]",
    n_turns: int = DEFAULT_PROTECTED_TURNS,
) -> "tuple[list[BaseMessage], list[BaseMessage]]":
    """把 history(不含 system)按轮次切分为 ``(outer, recent)``。

    * ``recent``:倒数第 ``n_turns`` 个 HumanMessage(含)及之后的所有消息
      —— 最近 N 轮,受保护窗口。
    * ``outer``:上述位置之前的所有消息 —— 5轮之外,可无条件压缩。

    边界:
    * HumanMessage 不足 N 个 → 全部归入 recent(没有 5轮之外的内容)。
    * 开头非 HumanMessage(如直接 AIMessage 打头)→ 归入 outer。

    注意:agent 长任务场景请用 :func:`split_for_compression`——本函数的
    「不足 N 轮全保护」正是长任务盲区的根源(outer 恒空)。
    """
    from langchain_core.messages import HumanMessage

    human_idx = [i for i, m in enumerate(history) if isinstance(m, HumanMessage)]
    if len(human_idx) < n_turns:
        # 不足 N 轮,全部保护,没有可压缩的 outer。
        return [], list(history)

    cut = human_idx[-n_turns]  # 倒数第 N 个 HumanMessage 的位置(含)
    outer = history[:cut]
    recent = history[cut:]
    return outer, recent


def _tool_batch_boundaries(history: "list[BaseMessage]") -> list[int]:
    """工具批次对齐的安全切点 index 列表(升序)。

    边界 = HumanMessage 位置 ∪ 带tool_calls/invalid_tool_calls的AIMessage位置。
    以带 tool_calls 的 AIMessage 开启新段,保证该批次(AI + 其全部
    ToolMessages)整体落在切点同侧——配对绝不撕裂(孤儿清理会把撕裂的
    配对整对删除,比不切还糟)。
    """
    from langchain_core.messages import AIMessage, HumanMessage

    bounds: list[int] = []
    for i, m in enumerate(history):
        if isinstance(m, HumanMessage):
            bounds.append(i)
        elif isinstance(m, AIMessage) and (
            getattr(m, "tool_calls", None) or getattr(m, "invalid_tool_calls", None)
        ):
            bounds.append(i)
    return bounds


def split_for_compression(
    history: "list[BaseMessage]",
    *,
    protected_turns: int = DEFAULT_PROTECTED_TURNS,
    protected_ratio: float = DEFAULT_PROTECTED_RATIO,
    min_batches: int = DEFAULT_MIN_BATCHES,
    context_window: int = 128_000,
) -> "tuple[list[BaseMessage], list[BaseMessage]]":
    """切分为 ``(outer, recent)``,供 compress 流水线使用(新语义)。

    * chat 多轮(human ≥ protected_turns):倒数第 N 个 HumanMessage 切点
      (与 :func:`split_by_turns` 一致,行为不变)。
    * agent 长任务(human 不足):从尾部逐段累计 token 构造 recent——
      最近 ``min_batches`` 批无条件保护;继续整段纳入直到累计超过
      ``protected_ratio × context_window``;切点 snap 到段边界。
      段总量不足预算 → 全保护(等价旧行为,早期历史不多不值得动)。
    * 锚定:首条 HumanMessage(任务指令)若落入 outer → 剥出拼回 recent
      头部,永不参与压缩/摘要/丢弃。调用方可通过
      ``recent[0] is history[0]`` 识别锚定消息。
    """
    from langchain_core.messages import HumanMessage

    from agent_flow_harness.engine.context import estimate_messages_tokens

    human_idx = [i for i, m in enumerate(history) if isinstance(m, HumanMessage)]
    if len(human_idx) >= protected_turns:
        cut = human_idx[-protected_turns]
    else:
        bounds = _tool_batch_boundaries(history)
        if len(bounds) <= min_batches:
            # 段也不足 → 全保护。
            cut = 0
        else:
            budget = max(1, int(context_window * protected_ratio))
            # 段 j = [bounds[j], bounds[j+1]);最近 min_batches 段无条件保护。
            start = len(bounds) - min_batches
            cut = bounds[start]
            total = estimate_messages_tokens(history[cut:])
            for j in range(start - 1, -1, -1):
                seg_tokens = estimate_messages_tokens(history[bounds[j]:cut])
                if total + seg_tokens > budget:
                    break
                total += seg_tokens
                cut = bounds[j]

    outer, recent = history[:cut], history[cut:]
    # 锚定:任务指令(首条 HumanMessage)永不进 outer。
    if outer and isinstance(outer[0], HumanMessage):
        anchor = outer.pop(0)
        recent = [anchor, *recent]
    return outer, recent


def count_turns(history: "list[BaseMessage]") -> int:
    """数 history 里有几轮(HumanMessage 个数)。"""
    from langchain_core.messages import HumanMessage

    return sum(1 for m in history if isinstance(m, HumanMessage))


__all__ = [
    "DEFAULT_MIN_BATCHES",
    "DEFAULT_PROTECTED_RATIO",
    "DEFAULT_PROTECTED_TURNS",
    "count_turns",
    "split_by_turns",
    "split_for_compression",
]
