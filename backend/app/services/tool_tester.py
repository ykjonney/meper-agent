"""ToolTester — 工具定义试跑与 AI 测试用例生成。

治理链（create → submit → review → enable）缺「验证」环节：作者在提交
审查前需要确认工具真的能跑。两个能力（均不落库、不要求 published/enabled）：

- ``run_once``：给定定义 + 参数 + 试跑凭证（ad hoc，不持久化），构建后
  单次调用，返回 {ok, result | error}
- ``generate_cases``：AI 按工具定义生成 2-3 个测试用例（params 集），
  前端逐个调 run_once 呈现结果

安全边界：code 走既有沙箱（read_only rootfs / 512m / 60s 超时），
入口与创建同权限（tool:write）——能写工具的人本就能提交待审代码。
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from app.engine.llm_factory import content_text, resolve_chat_model
from app.models.user_tool import TOOL_NAME_PATTERN
from app.services.user_tool_service import UserToolError, UserToolService

_RUN_TIMEOUT_S = 60

_CASES_SYSTEM_PROMPT = (
    "你是工具测试专家：根据给定的工具定义生成 2-3 个测试用例。\n\n"
    "要求：\n"
    "- 覆盖正常路径与边界情况（如非法值、缺省参数）\n"
    "- params 只能使用 llm_args_schema 声明的参数名，类型符合声明\n"
    "- 涉及外部服务无法真实成功也没关系——用例目的是验证工具定义能正确"
    "构建与调用（如 SMTP 认证失败也算有效观察点）\n"
    "- 每个用例一句验证点说明\n\n"
    '输出格式：先用一句话说明，再附 ```json 围栏：\n'
    '{"cases":[{"name":"用例名","description":"验证点","params":{...}}]}'
)


async def run_once(definition: dict[str, Any], params: dict, user_args: dict) -> dict[str, Any]:
    """按定义试跑一次（不落库）。

    Args:
        definition: {name, source, code, endpoint, llm_args_schema}
        params: 运行参数（对应 llm_args_schema）
        user_args: 试跑凭证（ad hoc，绝不持久化）

    Returns:
        {"ok": bool, "result": str | None, "error": str | None}
    """
    from app.engine.tool.tool_builder import build_tool

    source = definition.get("source", "")
    if source not in ("code", "openapi"):
        raise UserToolError("试跑仅支持 code / openapi 工具")
    name = str(definition.get("name") or "").strip()
    if not re.match(TOOL_NAME_PATTERN, name):
        raise UserToolError(f"工具名 '{name}' 不符合规则，无法构建")
    if source == "code":
        UserToolService._validate_code(str(definition.get("code") or ""))

    tool = await build_tool(
        {
            "name": name,
            "description": str(definition.get("description") or ""),
            "source": source,
            "code": definition.get("code") or "",
            "endpoint": definition.get("endpoint") or {},
            "llm_args_schema": definition.get("llm_args_schema") or {},
        },
        user_args=user_args,
    )
    if tool is None:
        raise UserToolError("工具构建失败（定义不完整）")

    try:
        result = await asyncio.wait_for(tool.ainvoke(dict(params)), timeout=_RUN_TIMEOUT_S)
    except TimeoutError:
        return {"ok": False, "result": None, "error": f"执行超时（{_RUN_TIMEOUT_S}s）"}
    except Exception as exc:
        return {"ok": False, "result": None, "error": f"{type(exc).__name__}: {exc}"[:500]}

    # code 工具沙箱失败以 "Error:" 文本返回——直调路径同样判失败
    if isinstance(result, str) and result.startswith("Error:"):
        return {"ok": False, "result": None, "error": result[:500]}
    return {"ok": True, "result": result, "error": None}


async def run_saved_once(tool_id: str, params: dict, user_args_override: dict) -> dict[str, Any]:
    """试跑**已保存**的工具（工具节点调试用）。

    定义与组织凭证经 UserToolService.resolve_runnable_tool 统一治理解析
    （与生产直调同口径），user_args_override 可临时覆盖——测试即生产语义。
    """
    resolved = await UserToolService.resolve_runnable_tool(tool_id)
    if resolved is None:
        raise UserToolError(f"工具不可用或不存在：{tool_id}")
    tool_doc, org_args = resolved
    merged_args = {**org_args, **(user_args_override or {})}
    return await run_once(tool_doc, dict(params), merged_args)


async def generate_cases(definition: dict[str, Any], model_id: str = "") -> dict[str, Any]:
    """AI 按工具定义生成测试用例（仅 params，不编造凭证）。"""
    try:
        llm = await resolve_chat_model(model_id, temperature=0.2)
    except ValueError as exc:
        raise UserToolError(f"生成{exc}") from exc

    def_schema = definition.get("llm_args_schema") or {}
    payload = {
        "name": definition.get("name"),
        "description": definition.get("description"),
        "source": definition.get("source"),
        "llm_args_schema": def_schema,
        "endpoint": definition.get("endpoint") or {},
        "code": definition.get("code") or "",
    }
    messages = [
        SystemMessage(content=_CASES_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"工具定义：\n```json\n{json.dumps(payload, ensure_ascii=False, default=str)}\n```"
        )),
    ]
    try:
        resp = await llm.ainvoke(messages)
    except Exception as exc:
        raise UserToolError(f"生成模型调用失败：{str(exc)[:300]}") from exc

    # 结构化 content（thinking/text 块）→ 只取 text（llm_factory.content_text）
    content = content_text(resp)
    match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", content, re.DOTALL)
    if match is None:
        raise UserToolError("AI 未按格式输出测试用例，请重试")
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise UserToolError(f"测试用例 JSON 解析失败：{exc}") from exc

    allowed = set((def_schema.get("properties") or {}).keys())
    cases: list[dict[str, Any]] = []
    for c in data.get("cases") or []:
        if not isinstance(c, dict):
            continue
        params = {k: v for k, v in (c.get("params") or {}).items() if not allowed or k in allowed}
        cases.append({
            "name": str(c.get("name") or "用例"),
            "description": str(c.get("description") or ""),
            "params": params,
        })
    if not cases:
        raise UserToolError("AI 未生成有效测试用例，请重试")
    logger.info("tool_test_cases_generated", tool=name_of(definition), count=len(cases))
    return {"cases": cases[:5]}


def name_of(definition: dict[str, Any]) -> str:
    return str(definition.get("name") or "")
