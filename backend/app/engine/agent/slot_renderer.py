"""System prompt renderer — reads system_prompt (whole text) from Agent document.

渲染顺序：system_prompt（整段，Jinja2 {{var}} resolve）→ 节点槽覆写追加段（
存量兼容）→ tool_declaration（运行时自动追加）。

旧五槽（role/task/constraints/context/output_format）已废弃并迁移为整段
（migrate_system_prompt.py）；SLOT_SCHEMA 仅供迁移/导入合并函数复用。

Usage::

    from app.engine.agent.slot_renderer import render_system_prompt_full

    system_text = await render_system_prompt_full(
        agent_doc,
        node_slot_overrides={"role": "You are a pirate."},
        variable_pool={"input": {"query": "Hello"}},
    )
"""
from __future__ import annotations

import json
import re
from typing import Any

# 检测字符串里 Jinja2 渲染 dict/list 时产生的 Python repr 片段
# （单引号包裹 key 的 {…} 或 […]），用于把混合模板里的 dict 变量渲染结果
# 修正为合法 JSON 文本。例：上游结果：{'branch': 'HEAVY'} → 含 JSON
_PY_DICT_REPR_RE = re.compile(r"\{['\"]")
_PY_LIST_REPR_RE = re.compile(r"\[['\"]")


def _coerce_slot_value(raw: Any) -> str:
    """把 ExpressionEngine 解析后的值归一化为合法的可读字符串。

    ExpressionEngine 对「单一变量引用」会保留原类型（可能返回 dict/list/bool
    而非字符串），直接用于判空和 f-string 拼接会导致两类问题：

    1. dict/list 是 truthy，判空通过，但 f-string 拼出的是 Python repr（单引号、
       True 大写），既不是合法 JSON 也难以阅读。
    2. 当模板含变量但变量解析失败时，resolve 可能返回 None，被判为空 → 报
       「必填 slot 缺失」，掩盖了真正的「变量解析失败」根因。

    本函数把非字符串值安全转成 JSON 文本（dict/list）或字符串（bool/number）；
    对于已经是字符串但内含 Jinja2 渲染出的 Python dict/list repr（混合模板
    场景），用 ast.literal_eval + json.dumps 修正为合法 JSON。None 视为未
    解析到内容返回空串。
    """
    if raw is None:
        return ""
    if isinstance(raw, (dict, list)):
        return json.dumps(raw, ensure_ascii=False, default=str)
    if not isinstance(raw, str):
        return str(raw)
    # 混合模板：Jinja2 把内嵌的 dict/list 变量渲染成 Python repr（{'k': v}），
    # 这里尝试把其中的 repr 片段修正为合法 JSON 文本。
    if _PY_DICT_REPR_RE.search(raw) or _PY_LIST_REPR_RE.search(raw):
        return _fix_py_reprs_in_string(raw)
    return raw


def _fix_py_reprs_in_string(s: str) -> str:
    """把字符串里所有形如 Python dict/list repr 的片段转为 JSON 文本。

    用正则找出 ``{...}`` / ``[...]`` 片段，逐个用 ``ast.literal_eval`` 还原
    成 Python 对象，再用 ``json.dumps`` 序列化。解析失败的片段保留原样。
    """
    import ast

    # 匹配成对的 {...} 或 [...]（非贪婪，允许嵌套引号）
    pattern = re.compile(r"(\{[^{}]*\}|\[[^\[\]]*\])")

    def _replace(match: re.Match[str]) -> str:
        fragment = match.group(1)
        try:
            obj = ast.literal_eval(fragment)
            if isinstance(obj, (dict, list)):
                return json.dumps(obj, ensure_ascii=False, default=str)
        except (ValueError, SyntaxError):
            pass
        return fragment

    return pattern.sub(_replace, s)


async def render_system_prompt_full(
    agent_doc: dict,
    *,
    node_slot_overrides: dict[str, str] | None = None,
    variable_pool: dict[str, Any] | None = None,
    strict: bool = True,
    exclude_skill_names: set[str] | None = None,
    execution_context: str = "chat",
    response_schema: dict | None = None,
    output_schema: list[dict] | None = None,
    subagents: list[dict] | None = None,
) -> str:
    """Render the full system prompt from the Agent's system_prompt field.

    旧五槽（prompt_slots）设计已废弃（migrate_system_prompt.py 数据迁移）——
    system_prompt 为整段自由文本，槽值中的 Jinja2 ``{{var}}`` 语法在整段上
    统一 resolve（工作流变量池注入保持）。

    Args:
        agent_doc: The Agent MongoDB document.
        node_slot_overrides: 节点级槽覆写（存量数据为零；有值时以【label】段
            追加在整段之后）。
        variable_pool: Variable pool for Jinja2 ``{{var}}`` resolution.
        strict: When True (default), an empty system_prompt raises ValueError.
            When False, empty prompt is silently skipped (for preview).
        execution_context: "chat"(默认)或 "workflow"(工作流 agent 节点,
            无人值守——工具声明去掉 Clarification/Task 段,追加自主执行规则)。
        response_schema: 工作流 agent 节点的 response 结构契约(可选,
            {type: object|array, fields: [...]} 嵌套最多两层)。配置时
            tool_declaration 追加 Output Contract 段,最终回复必须是
            符合契约的 JSON(即 response 的值)。
        output_schema: **已废弃**（旧格式 list[字段]）。仅为兼容热重载
            进程中残留的旧调用方保留——收到时转译为 response_schema 并
            打 warning 日志；新代码请勿使用。

    Returns:
        Fully assembled system prompt string.
    """
    if response_schema is None and output_schema:
        from loguru import logger

        logger.warning(
            "render_system_prompt_full: output_schema 参数已废弃，请改用 response_schema",
        )
        response_schema = {"type": "object", "fields": output_schema}
    raw_prompt = str(agent_doc.get("system_prompt") or "")
    overrides = dict(node_slot_overrides or {})
    empty_after_resolve = ""  # 原文含 {{var}} 但渲染为空时记录原文

    # ── Resolve Jinja2 expressions over the whole prompt ──
    if variable_pool and ("{{" in raw_prompt or any("{{" in str(v) for v in overrides.values())):
        from app.engine.workflow.expression import ExpressionEngine

        engine = ExpressionEngine(variable_pool)
        resolved = engine.resolve(raw_prompt)
        coerced = _coerce_slot_value(resolved)
        if not coerced and "{{" in raw_prompt:
            empty_after_resolve = raw_prompt
        raw_prompt = coerced
        for k, v in overrides.items():
            if isinstance(v, str):
                overrides[k] = _coerce_slot_value(engine.resolve(v))

    parts: list[str] = []
    if raw_prompt.strip():
        parts.append(raw_prompt.strip())
    elif strict:
        # 无人值守等场景 agent 无 prompt 没有意义——fail fast 给出精确根因
        if empty_after_resolve:
            raise ValueError(
                "system_prompt 含变量引用但渲染后为空"
                f"（上游变量可能不存在或为空值）: {empty_after_resolve}"
            )
        if overrides:
            parts.extend(f"【{k}】\n{v}" for k, v in overrides.items() if v)
        else:
            raise ValueError(
                "system_prompt 未配置。请在 Agent 配置中填写系统提示词，"
                "或检查节点槽覆写与上游变量输出。"
            )

    # 节点槽覆写（存量零使用，参数兼容保留）：以【key】段追加在整段之后
    for k, v in overrides.items():
        if v:
            parts.append(f"【{k}】\n{v}")

    # ── Always append tool_declaration at the end ──
    from app.engine.agent.builder import build_tool_declaration

    tool_decl = await build_tool_declaration(
        agent_doc,
        exclude_names=exclude_skill_names,
        execution_context=execution_context,
        response_schema=response_schema,
        subagents=subagents,
    )
    if tool_decl:
        parts.append(tool_decl)

    return "\n\n".join(parts)
