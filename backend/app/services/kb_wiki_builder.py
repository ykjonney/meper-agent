"""One-click wiki builder — LLM ingest routine over the wiki toolset.

Runs a minimal REACT loop (LLM + kb_* tools, no LangGraph/checkpointer —
the builder is a headless Celery job, not an interactive session) that
follows the guide's ingest workflow: read the guide → find undigested
sources (log.md + uncited stats) → batch-sample sources → create/update
concept/entity pages → update overview → append log → lint.

Guarded by ``last_build_status`` on the KB document (running prevents
re-entry). Model comes from ``builder_model_id`` (Model table) via
``build_client_from_doc`` — same pattern as ``model_service.test_model``.
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from loguru import logger

# Builder needs more headroom than the interactive 25-iteration cap: one
# ingest touches 5-15 pages across multiple sources.
_MAX_STEPS = 60

# A build whose claim ("running") is older than this is considered dead
# (worker killed / hard time limit SIGKILLed before the except could run)
# and may be re-dispatched. Global soft limit is 1800s — 2100s adds margin.
_STALE_RUNNING_SECONDS = 2100


def is_stale_running(kb_doc: dict, *, now_ts: float | None = None) -> bool:
    """True when a "running" build claim is old enough to be considered dead.

    Guards against permanently-blocked rebuilds after a hard worker kill
    (soft-limit SoftTimeLimitExceeded is caught by the task and marks
    failed; SIGKILL leaves the claim behind forever).
    """
    import time
    from datetime import datetime

    if kb_doc.get("last_build_status") != "running":
        return False
    started = str(kb_doc.get("last_build_at") or "")
    if not started:
        return True  # running 但没有时间戳——异常态，允许重派
    try:
        started_dt = datetime.fromisoformat(started)
    except ValueError:
        return True
    now = now_ts if now_ts is not None else time.time()
    return (now - started_dt.timestamp()) > _STALE_RUNNING_SECONDS


async def pending_digest_sources(kb_id: str) -> dict[str, list[str]]:
    """构建的消化清单 = 未被引用的源 ∪ 已引用但内容已更新的源。

    - 未被引用：FS 扫描（sources/ 文件 − 脚注引用过的路径）
    - 内容已更新：登记表里 content_hash ≠ digest_hash 的已引用源
      （同名重传覆盖后旧脚注仍指向该路径，纯路径判断会漏掉）
    """
    from app.engine.kb.tree.guide import cited_sources, read_all_pages, wiki_stats
    from app.services import kb_wiki_registry

    stats = wiki_stats(kb_id)
    cited = cited_sources(read_all_pages(kb_id))
    stale: list[str] = []
    for reg in await kb_wiki_registry.list_by_kb(kb_id):
        path = reg.get("relative_path", "")
        content_hash = reg.get("content_hash", "")
        digest_hash = reg.get("digest_hash", "")
        if (
            path in cited
            and content_hash
            and digest_hash
            and content_hash != digest_hash
        ):
            stale.append(path)
    return {
        "uncited": stats["uncited_sources"],
        "stale": sorted(stale),
        "pending": sorted(set(stats["uncited_sources"]) | set(stale)),
    }


async def stamp_digested(kb_id: str) -> int:
    """构建成功后回写 digest_hash：把当前已被引用源的 content_hash 盖章。

    Returns the number of records stamped.
    """
    from app.engine.kb.tree.guide import cited_sources, read_all_pages
    from app.services import kb_wiki_registry

    cited = cited_sources(read_all_pages(kb_id))
    stamped = 0
    for reg in await kb_wiki_registry.list_by_kb(kb_id):
        if reg.get("relative_path") in cited and reg.get(
            "digest_hash"
        ) != reg.get("content_hash"):
            await kb_wiki_registry.set_digest_hash(
                reg["_id"], reg.get("content_hash", "")
            )
            stamped += 1
    return stamped

_BUILDER_SYSTEM_PROMPT = """你是知识库的 Wiki 构建者。严格遵循 kb_guide 返回的指南（黄金法则：sources 只读、冲突时原文赢、论断必须脚注引用源文件+页码）。

本次任务（ingest routine）：
1. 调用 kb_guide 获取指南与本库状态。
2. 「待消化源」= 未被引用的源 + 内容已更新（同名重传）的源。对照 wiki/log.md 最近条目与任务给出的待消化清单，逐个消化（一次构建处理全部待消化源）。
3. 对每个源：kb_read 批量采样（如 pages="1-8"），再精读关键页；把知识按主题归位——
   更新已有概念/实体页（str_replace）或创建新页（create）。一份源通常触碰 5-15 个页面；
   内容已更新的源重点把**变化之处**织入相关页，并核对旧论断是否仍成立（不成立就修正）。
4. 全部源消化完后：更新 wiki/overview.md（计数、主题导览、Key Findings、Recent Updates）。
5. 在 wiki/log.md 文末追加 `## [今天日期] ingest | 源标题` 条目（不改写历史）。
6. 调用 kb_lint，修复其中的 error 项（补脚注/修链接）。
7. 完成后输出一段简短总结（写了哪些页、更新了哪些页、遗留什么），然后停止——不要再调用任何工具。

注意：如果任务给出的待消化清单为空，直接输出「无需构建」的总结即可。"""

_TRIGGER_PROMPT = "开始执行本次 Wiki 构建任务。"


async def run_wiki_build(kb_id: str) -> dict[str, Any]:
    """Execute one build cycle; caller (Celery task) owns status transitions.

    Returns {"status": "completed"|"failed", "steps": n, "summary": str}.
    """
    from app.db.mongodb import get_database
    from app.engine.kb.tree import fs as kb_fs
    from app.engine.kb.tree.manager import KbManager
    from app.engine.llm_factory import build_client_from_doc
    from app.services.model_service import ModelService

    kb_doc = await get_database()["knowledge_bases"].find_one({"_id": kb_id})
    if kb_doc is None:
        return {"status": "failed", "error": f"知识库 {kb_id} 不存在"}
    builder_model_id = kb_doc.get("builder_model_id") or ""
    if not builder_model_id.startswith("model_"):
        return {"status": "failed", "error": "未配置构建模型（builder_model_id）"}

    model_doc = await ModelService.get_model_config_by_id(builder_model_id)
    if model_doc is None:
        return {"status": "failed", "error": f"构建模型不存在: {builder_model_id}"}
    try:
        llm = build_client_from_doc(model_doc, {"temperature": 0.2})
    except Exception as exc:
        return {"status": "failed", "error": f"构建模型客户端构造失败（{builder_model_id}）：{exc}"}

    kb_roots = {kb_id: kb_fs.get_kb_base_path(kb_id)}
    tools = KbManager(kb_roots, wiki_kb_ids={kb_id}).make_tools()
    tools_by_name = {t.name: t for t in tools}
    llm_with_tools = llm.bind_tools(tools)

    pending = await pending_digest_sources(kb_id)
    pending_list = pending["pending"]
    messages: list[Any] = [
        SystemMessage(content=_BUILDER_SYSTEM_PROMPT),
        HumanMessage(
            content=(
                f"{_TRIGGER_PROMPT}\n\n当前库状态："
                f"待消化源 {len(pending_list)} 个"
                + (
                    "（其中内容已更新："
                    + "；".join(pending["stale"])
                    + "）" if pending["stale"] else ""
                )
                + "："
                + ("；".join(pending_list) or "无")
            )
        ),
    ]

    summary = ""
    steps = 0
    for step in range(_MAX_STEPS):
        steps = step + 1
        try:
            ai = await llm_with_tools.ainvoke(messages)
        except Exception as exc:
            # 模型调用是最高频失败点（Key/地址无效、模型不支持 tools）——
            # 包上步骤号与模型名，让 last_build_error 一眼可辨。
            raise RuntimeError(
                f"构建模型调用失败（第 {steps} 步，模型 {model_doc.get('name', builder_model_id)}）：{exc}"
            ) from exc
        messages.append(ai)
        tool_calls = getattr(ai, "tool_calls", None)
        if not tool_calls:
            summary = str(ai.content or "").strip()
            break
        for tc in tool_calls:
            name = tc.get("name", "")
            tool = tools_by_name.get(name)
            if tool is None:
                result = f"Error: unknown tool {name}"
            else:
                try:
                    result = str(await tool.ainvoke(tc.get("args", {})))
                except Exception as exc:  # 单工具失败不终止构建
                    logger.warning(
                        "wiki_build_tool_failed", kb_id=kb_id, tool=name, error=str(exc)
                    )
                    result = f"Error: {exc}"
            messages.append(ToolMessage(content=result[:8000], tool_call_id=tc.get("id", "")))
    else:
        summary = "（达到步数上限，构建提前收尾——可再次点击构建继续增量消化）"

    logger.info(
        "wiki_build_loop_done", kb_id=kb_id, steps=steps, summary_len=len(summary)
    )
    return {"status": "completed", "steps": steps, "summary": summary[:4000]}


def dispatch_build_task(kb_id: str) -> None:
    """Dispatch the Celery build task (lazy import; tests monkeypatch)."""
    from app.workers.tasks.wiki_build import build_wiki_kb

    build_wiki_kb.delay(kb_id)
