"""工具定义共享模块——规则文本 + 定义校验/规整 + LLM 解析。

原「单次对话式生成」（/generate 端点 + generate() 循环）已被工具工坊
agent（tool_forge_service，harness REACT + 专用工具）取代并移除；本模块
保留工坊复用的单一事实源：

- ``_DEFINITION_SPEC`` / ``_CODE_RULES`` / ``_OPENAPI_RULES``：定义字段与
  代码/openapi 规则段（工坊系统提示词引用，防两处漂移）
- ``normalize_definition``：dict 形态定义的校验与规整（工坊
  submit_definition 工具复用；沙箱依赖白名单校验复用
  ``UserToolService._validate_code``）
- ``ToolGeneratorService._build_llm``：生成模型解析（model_ 前缀查模型表）
"""
from __future__ import annotations

import re
from typing import Any

from app.models.user_tool import SANDBOX_PREINSTALLED_IMPORTS, TOOL_NAME_PATTERN
from app.services.user_tool_service import UserToolError, UserToolService

_ALLOWED_IMPORTS = ", ".join(sorted(SANDBOX_PREINSTALLED_IMPORTS))

# ── 共享规则段：tool-forge agent 的系统提示词引用（单一事实源防漂移）──
_DEFINITION_SPEC = (
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
    "- tags: 英文小写标签数组"
)

_CODE_RULES = (
    "【code 型代码规则】\n"
    "1. 入口函数 def run(参数...)：参数名与 llm_args_schema 完全一致，带类型注解\n"
    '2. 凭证从环境变量读：os.environ["USER_参数名"]——USER_ 后与 user_args_schema '
    "的参数名**逐字一致且区分大小写**（参数名是小写下划线风格，如 USER_smtp_host；"
    "不要按环境变量惯例转大写成 USER_SMTP_HOST）\n"
    "3. 只能 import Python 标准库与这些库：" + _ALLOWED_IMPORTS + "\n"
    "4. 返回 str 或 dict/list（自动转 JSON）；失败直接 raise（错误信息会给 AI 重试）\n"
    "5. 文件参数约定：字符串参数值可能是文件路径（input/xxx 只读、output/xxx 可写，"
    "file_id 已被系统自动替换为 input/ 下路径），直接 open() 使用；需产出文件写 output/ 目录\n"
    "6. SMTP 必须按端口分支加密：465 用 smtplib.SMTP_SSL；587/25 用 SMTP + starttls()"
    "（对 STARTTLS 端口发隐式 SSL 会报 WRONG_VERSION_NUMBER）\n"
    "7. 代码精炼完整（不超过 60 行）"
)

_OPENAPI_RULES = (
    "【openapi 型规则】\n"
    "- url 路径参数用 {名字} 占位；参数声明一次，位置决定发送到哪\n"
    "- 无法得知真实 URL 时用 https://api.example.com/... 占位，并在 description 注明需替换"
)


def _ensure_schema(schema: Any) -> dict[str, Any]:
    """规整 JSON Schema：无有效 properties 时归为空 schema。"""
    if not isinstance(schema, dict):
        return {}
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    if not props:
        return {}
    return {"type": "object", "properties": props, "required": required}


def normalize_definition(data: Any, source_hint: str = "") -> dict[str, Any]:
    """dict 形态的工具定义校验与规整（tool-forge 的 submit_definition 复用）。

    形态问题以 UserToolError 抛出（forge 工具层转 JSON 结果反馈 LLM 重试）。
    """
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
    if source == "code" and code:
        # 依赖白名单在提交时拦截（旧 generate() 的校验口径——不能拖到 run_test 才报）
        UserToolService._validate_code(code)

    output_schema = data.get("output_schema") if isinstance(data.get("output_schema"), dict) else {}
    if source == "code" and code and not output_schema.get("fields"):
        # AI 未声明返回结构——按生成的代码静态推导（下游 {{node.result.字段}} 可选）
        from app.services.tool_output_schema import derive_output_schema

        output_schema = derive_output_schema(code, name) or output_schema

    llm_args_schema = _ensure_schema(data.get("llm_args_schema"))
    user_args_schema = _ensure_schema(data.get("user_args_schema"))
    if source == "code" and code:
        # 凭证环境变量一致性：代码里字面读取的 USER_x 必须在 user_args_schema
        # 声明（参数名即环境变量名）——防「schema 说 A、代码读 B」的漂移，
        # 否则运行期才报「缺少凭证」（AI 还会误判为沙箱限制）。
        # 常见形态：代码按环境变量惯例转大写（USER_SMTP_HOST）而参数名是
        # 小写下划线（smtp_host）——大小写不匹配单独点名
        env_reads = set(re.findall(r"USER_([A-Za-z_][A-Za-z0-9_]*)", code))
        declared = set(user_args_schema.get("properties") or {})
        undeclared = env_reads - declared
        if undeclared:
            lower_map = {k.lower(): k for k in declared}
            parts: list[str] = []
            for k in sorted(undeclared):
                twin = lower_map.get(k.lower())
                parts.append(
                    f"USER_{k}（与参数「{twin}」仅大小写不同）" if twin else f"USER_{k}"
                )
            raise UserToolError(
                "代码读取的凭证环境变量 " + "、".join(parts)
                + " 未在 user_args_schema 中声明——环境变量名区分大小写，"
                "USER_ 后必须与参数名逐字一致（参数名保持小写下划线，"
                "不要按环境变量惯例转大写），请统一后重新提交"
            )
    return {
        "name": name,
        "description": str(data.get("description") or "").strip(),
        "source": source,
        "llm_args_schema": llm_args_schema,
        "user_args_schema": user_args_schema,
        "endpoint": endpoint if source == "openapi" else {},
        "code": code if source == "code" else "",
        "output_schema": output_schema,
        "tags": [str(t).strip() for t in (data.get("tags") or []) if str(t).strip()],
    }


class ToolGeneratorService:
    """工坊/生成侧共享的 LLM 解析薄封装。"""

    @staticmethod
    async def _build_llm(model_id: str):
        """生成模型解析（薄封装：llm_factory.resolve_chat_model + 领域错误转译）。"""
        from app.engine.llm_factory import resolve_chat_model

        try:
            return await resolve_chat_model(model_id, temperature=0.2)
        except ValueError as exc:
            raise UserToolError(f"生成{exc}") from exc
