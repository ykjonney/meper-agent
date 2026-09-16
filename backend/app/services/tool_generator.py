"""ToolGeneratorService — AI 按平台规则生成自定义工具定义草稿。

用户用自然语言描述需求，LLM 依据工具体系规则（入口约定 / 凭证注入 /
依赖白名单 / 参数 schema 形态）产出一份**草稿**（不落库）——前端回填
创建表单，用户确认/修改后走既有治理链（create → submit → review →
enable），生成不绕过任何治理环节。

生成结果经本地校验（JSON 形态 + `_validate_code` 依赖白名单），不过则
带反馈重试一轮（共两次 LLM 调用），仍失败抛 UserToolError。
"""
from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from loguru import logger

from app.models.user_tool import SANDBOX_PREINSTALLED_IMPORTS, TOOL_NAME_PATTERN
from app.services.user_tool_service import UserToolError, UserToolService

_ALLOWED_IMPORTS = ", ".join(sorted(SANDBOX_PREINSTALLED_IMPORTS))

# 注意：规则文本里 JSON 花括号是字面量，用拼接而非 f-string 组装动态段
_SYSTEM_PROMPT = (
    "你是 Agent 平台的「工具定义专家」，通过与用户**多轮对话**帮其打造自定义工具。\n\n"
    "【对话协议】\n"
    "- 用户描述需求 → 你生成完整工具定义；用户提修改意见（如「加个参数」「改成用 "
    "SMTP」「名字换成 xxx」）→ 你在上一版基础上修订，输出**完整**新定义（不是 diff）\n"
    "- 修订原则：用户未提及的字段保持上一版不变；不虚构用户没提的需求\n"
    "- 需求不清楚（缺关键信息如接口地址、凭证方式）可以先提问澄清——此时不输出 JSON\n\n"
    "【回复格式（严格遵守）】\n"
    "- 先用一两句话向用户说明你做了什么/改了什么\n"
    "- 若本轮产出或更新了定义，在回复末尾附上 ```json 围栏的完整 JSON 定义\n"
    "- 仅澄清提问时不输出 JSON\n"
    "- 只输出一个 JSON 对象，字段如下：\n"
    "- name: 工具名，英文小写+连字符风格（如 send-email），规则 "
    + TOOL_NAME_PATTERN
    + "\n"
    "- description: 一句话中文说明功能与限制（AI 靠它决定何时调用）\n"
    '- source: "code"（Python 沙箱执行）或 "openapi"（HTTP 接口封装）——'
    "用户指定则遵从；需要计算/文件处理/发邮件等逻辑选 code，"
    "封装现成 REST API 选 openapi\n"
    "- llm_args_schema: 运行参数（AI 每次调用时填值），形如 "
    '{"type":"object","properties":{"参数名":{"type":"string","description":"说明"}},'
    '"required":["参数名"]}；type 限 string/number/boolean/array；参数名英文小写下划线\n'
    "- user_args_schema: 凭证参数（管理员统一配置，同上结构；密码/密钥类参数"
    ' 加 "sensitive": true）\n'
    "- code: source=code 时的 Python 代码；openapi 时为空字符串\n"
    "- endpoint: source=openapi 时形如 "
    '{"method":"POST","url":"https://...","params":[{"name":"参数名",'
    '"in":"query|header|path|body","description":"说明","required":true,'
    '"credential":false}]}（凭证参数 credential=true）；code 时为空对象\n'
    "- output_schema: 返回字段声明 "
    '{"type":"object","fields":[{"name":"字段","type":"string|number|boolean|object",'
    '"is_list":false,"description":"说明"}]}；无明确结构给空对象\n'
    "- tags: 英文小写标签数组\n\n"
    "【code 型代码规则】\n"
    "1. 入口函数 def run(参数...)：参数名与 llm_args_schema 完全一致，带类型注解\n"
    '2. 凭证从环境变量读：os.environ["USER_参数名"]（名字即 user_args_schema 的参数名）\n'
    "3. 只能 import Python 标准库与这些库：" + _ALLOWED_IMPORTS + "\n"
    "4. 返回 str 或 dict/list（自动转 JSON）；失败直接 raise（错误信息会给 AI 重试）\n"
    "5. 文件参数约定：字符串参数值可能是文件路径（input/xxx 只读、output/xxx 可写，"
    "file_id 已被系统自动替换为 input/ 下路径），直接 open() 使用；需产出文件写 output/ 目录\n"
    "6. SMTP 必须按端口分支加密：465 用 smtplib.SMTP_SSL；587/25 用 SMTP + starttls()"
    "（对 STARTTLS 端口发隐式 SSL 会报 WRONG_VERSION_NUMBER）\n"
    "7. 代码精炼完整（不超过 60 行）\n\n"
    "【openapi 型规则】\n"
    "- url 路径参数用 {名字} 占位；参数声明一次，位置决定发送到哪\n"
    "- 无法得知真实 URL 时用 https://api.example.com/... 占位，并在 description 注明需替换"
)


def _content_text(resp: Any) -> str:
    """LangChain 响应 → 文本（委托 llm_factory.content_text，保历史调用点）。"""
    from app.engine.llm_factory import content_text

    return content_text(resp)


def _ensure_schema(schema: Any) -> dict[str, Any]:
    """规整 JSON Schema：无有效 properties 时归为空 schema。"""
    if not isinstance(schema, dict):
        return {}
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    if not props:
        return {}
    return {"type": "object", "properties": props, "required": required}


def _extract_trailing_json(content: str) -> tuple[str, str] | None:
    """从无围栏回复中截取末尾的完整 JSON 对象（返回 前文, JSON 文本）。

    模型偶尔无视围栏要求直接裸输出定义——遍历行首 ``{``，取首个
    「自身到结尾整段可解析且含 name 字段」的候选。
    """
    for idx, ch in enumerate(content):
        if ch != "{" or (idx > 0 and content[idx - 1] not in "\n \t"):
            continue
        candidate = content[idx:]
        if '"name"' not in candidate:
            continue
        try:
            json.loads(candidate)
        except json.JSONDecodeError:
            continue
        return content[:idx], candidate
    return None


def _parse_reply(content: str, source_hint: str) -> tuple[str, dict[str, Any] | None]:
    """拆分 AI 回复：围栏外文本（给用户看）+ ```json 围栏内定义（草稿，可无）。

    无围栏 JSON 视为纯文本回复（澄清提问/说明）——draft=None；
    但若文本末尾带裸 JSON 对象（模型无视围栏要求），兜底提取。
    """
    match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", content, re.DOTALL)
    if match is not None:
        reply = (content[: match.start()] + content[match.end():]).strip()
        draft = _parse_and_normalize(match.group(1), source_hint)
        return reply or "已生成工具定义草稿。", draft
    fallback = _extract_trailing_json(content)
    if fallback is not None:
        text, raw = fallback
        draft = _parse_and_normalize(raw, source_hint)
        return text.strip() or "已生成工具定义草稿。", draft
    return content.strip(), None


def _parse_and_normalize(content: str, source_hint: str) -> dict[str, Any]:
    """解析 LLM 输出为工具定义草稿；形态问题以 UserToolError 反馈重试。"""
    text = content.strip()
    if text.startswith("```"):  # 容错：剥 markdown 围栏
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise UserToolError(f"输出不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise UserToolError("输出必须是 JSON 对象")

    name = str(data.get("name") or "").strip()
    if not re.match(TOOL_NAME_PATTERN, name):
        raise UserToolError(
            f"工具名 '{name}' 不符合规则（字母数字开头，可含 - _，不超过 64 字符）"
        )

    source = source_hint if source_hint in ("code", "openapi") else str(data.get("source") or "")
    if source not in ("code", "openapi"):
        source = "code"

    code = str(data.get("code") or "").strip()
    endpoint = data.get("endpoint") if isinstance(data.get("endpoint"), dict) else {}
    if source == "code" and not code:
        raise UserToolError("source=code 但缺少代码（code 字段为空）")
    if source == "openapi" and not str(endpoint.get("url") or "").strip():
        raise UserToolError("source=openapi 但缺少接口地址（endpoint.url）")

    output_schema = data.get("output_schema") if isinstance(data.get("output_schema"), dict) else {}
    if source == "code" and code and not output_schema.get("fields"):
        # AI 未声明返回结构——按生成的代码静态推导（下游 {{node.result.字段}} 可选）
        from app.services.tool_output_schema import derive_output_schema

        output_schema = derive_output_schema(code, name) or output_schema
    return {
        "name": name,
        "description": str(data.get("description") or "").strip(),
        "source": source,
        "llm_args_schema": _ensure_schema(data.get("llm_args_schema")),
        "user_args_schema": _ensure_schema(data.get("user_args_schema")),
        "endpoint": endpoint if source == "openapi" else {},
        "code": code if source == "code" else "",
        "output_schema": output_schema,
        "tags": [str(t).strip() for t in (data.get("tags") or []) if str(t).strip()],
    }


class ToolGeneratorService:
    """AI 多轮对话生成工具定义草稿（无状态，历史随请求携带）。"""

    @staticmethod
    async def generate(
        messages: list[dict[str, str]], *, source_hint: str = "", model_id: str = ""
    ) -> dict[str, Any]:
        """按对话历史产出本轮回复与（若有）工具定义草稿。

        对话协议：用户描述需求 → AI 生成完整定义（```json 围栏）；用户提
        修改意见 → AI 修订并再次输出**完整**定义；需求不清时 AI 可只提问
        不输出 JSON（此时 draft=None）。草稿不落库——前端回填创建表单，
        用户确认后走既有治理链。

        Args:
            messages: 对话历史 [{role: "user"|"assistant", content}]，末条须为 user。
            source_hint: 指定 "code" / "openapi"（空 = AI 按需求判断）。
            model_id: 生成模型（model_ 前缀查模型表；空 = 平台默认）。

        Returns:
            {"reply": 给用户看的文本说明, "draft": 草稿 dict | None}

        Raises:
            UserToolError: 草稿两轮校验不过 / 模型不可用 / 入参不合法。
        """
        if not messages or messages[-1].get("role") != "user":
            raise UserToolError("对话历史为空或末条不是用户消息")
        llm = await ToolGeneratorService._build_llm(model_id)

        system = _SYSTEM_PROMPT
        if source_hint in ("code", "openapi"):
            system += f"\n\n【本轮约束】用户指定 source={source_hint}。"
        convo: list[Any] = [
            SystemMessage(content=system),
            *(
                HumanMessage(content=m["content"]) if m.get("role") == "user"
                else AIMessage(content=m["content"])
                for m in messages[-20:]  # 截断防 token 膨胀
            ),
        ]

        last_error = ""
        for _attempt in range(2):  # 生成 + 一轮带反馈修复
            try:
                resp = await llm.ainvoke(convo)
            except UserToolError:
                raise
            except Exception as exc:
                # 模型侧错误（403 无权限 / 429 限额 / 网络失败）转可读错误，
                # 不以 unhandled 500 裸奔——提示换模型或稍后重试
                raise UserToolError(f"生成模型调用失败：{str(exc)[:300]}") from exc
            content = _content_text(resp)
            try:
                reply, draft = _parse_reply(content, source_hint)
                if draft is not None and draft["source"] == "code":
                    UserToolService._validate_code(draft["code"])
                return {"reply": reply, "draft": draft}
            except UserToolError as exc:
                last_error = exc.message
                logger.warning("tool_generate_retry", error=last_error)
                convo = [
                    *convo,
                    AIMessage(content=content),
                    HumanMessage(content=(
                        f"输出的定义未通过校验：{last_error}\n"
                        "请修正问题，重新按约定格式回复（说明 + 完整 ```json 围栏定义）。"
                    )),
                ]
        raise UserToolError(f"AI 生成的定义未通过校验（已重试一轮）：{last_error}")

    @staticmethod
    async def _build_llm(model_id: str):
        """生成模型解析（薄封装：llm_factory.resolve_chat_model + 领域错误转译）。"""
        from app.engine.llm_factory import resolve_chat_model

        try:
            return await resolve_chat_model(model_id, temperature=0.2)
        except ValueError as exc:
            raise UserToolError(f"生成{exc}") from exc
