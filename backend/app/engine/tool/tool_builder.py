"""ToolBuilder — unified entry point for building custom tools from DB docs.

Dispatches by ``source`` to the appropriate builder, returning a LangChain
``BaseTool`` ready for injection into the harness graph.

Supports:
- ``openapi``: HTTP endpoint with {{ }} template rendering + credential injection
- ``code``: User-defined Python code (governed tools — reviewed & enabled by admin)
"""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import httpx
from langchain_core.tools import StructuredTool
from loguru import logger
from pydantic import BaseModel, create_model

if TYPE_CHECKING:
    from agent_flow_harness.sandbox.docker import DockerSandbox

# ---------------------------------------------------------------------------
# Template rendering — simple {{ }} replacement (no Jinja2 dependency)
# ---------------------------------------------------------------------------


def render_template(template: str, context: dict[str, Any]) -> str:
    """Replace ``{{ key.subkey }}`` placeholders with values from context."""
    if not isinstance(template, str):
        return str(template)

    def _replace(match: re.Match) -> str:
        path = match.group(1).strip()
        return _resolve_path(path, context)

    return re.sub(r"\{\{(.+?)\}\}", _replace, template)


def _resolve_path(path: str, context: dict[str, Any]) -> str:
    """Resolve a dotted path like 'credential.token' from context."""
    parts = path.split(".")
    value: Any = context
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part, "")
        else:
            value = getattr(value, part, "")
    return str(value) if value is not None else ""


def render_dict(d: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Recursively render template strings in a dict (values in lists included)."""
    return {k: _render_value(v, context) for k, v in d.items()}


def _render_value(v: Any, context: dict[str, Any]) -> Any:
    """Render a single value: str / dict / list are templated recursively."""
    if isinstance(v, str):
        return render_template(v, context)
    if isinstance(v, dict):
        return render_dict(v, context)
    if isinstance(v, list):
        # 数组里的模板同样渲染（如 body {"to": ["{{llm.to}}"]}）
        return [_render_value(item, context) for item in v]
    return v


# ---------------------------------------------------------------------------
# JSON Schema → Pydantic model (for StructuredTool args_schema)
# ---------------------------------------------------------------------------


def _json_schema_to_pydantic(name: str, schema: dict[str, Any]) -> type[BaseModel]:
    """Convert a simple JSON Schema to a Pydantic model.

    Supports basic types: string, integer, number, boolean.
    Falls back to ``str`` for unknown types.
    """
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    fields: dict[str, Any] = {}

    type_map = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
    }

    for prop_name, prop_schema in properties.items():
        json_type = prop_schema.get("type", "string")
        py_type = type_map.get(json_type, str)
        default = ... if prop_name in required else None
        fields[prop_name] = (py_type | None if prop_name not in required else py_type, default)

    return create_model(f"{name}_Args", **fields)  # type: ignore[call-overload]


# ---------------------------------------------------------------------------
# ToolBuilder — unified entry
# ---------------------------------------------------------------------------


async def build_tool(tool_doc: dict, *, user_args: dict | None = None) -> StructuredTool | None:
    """Build a LangChain tool from a tool document.

    Args:
        tool_doc: Tool document from the ``tools`` collection.
        user_args: Agent 绑定时填入的用户参数值（已解密）。

    Returns:
        A ``StructuredTool`` ready for the harness graph, or ``None``.
    """
    source = tool_doc.get("source", "")
    name = tool_doc.get("name", "")
    description = tool_doc.get("description", "")
    user_args = user_args or {}

    try:
        if source == "openapi":
            return await _build_openapi_tool(tool_doc, name, description, user_args)
        if source == "code":
            return await _build_code_tool(tool_doc, name, description, user_args)
        logger.warning("tool_builder_unknown_source", name=name, source=source)
        return None
    except Exception as exc:
        logger.error("tool_builder_failed", name=name, source=source, error=str(exc))
        return None


# ---------------------------------------------------------------------------
# OpenApiToolBuilder
# ---------------------------------------------------------------------------


def _assemble_params_request(endpoint: dict, kwargs: dict, user_args: dict) -> tuple[str, str, dict, dict, dict]:
    """参数表模型组装请求（主流 HTTP 工具模型）：参数声明一次、位置定发送。

    按位置分桶：query → query params；header → 请求头；path → URL {占位} 替换；
    body → JSON body 字段。凭证参数的值取 user_args（构建时已解密注入），
    其余取 LLM 调用入参。返回 (method, url, headers, query, body)。
    """
    url = str(endpoint.get("url") or "")
    method = str(endpoint.get("method") or "GET").upper()
    headers: dict[str, str] = {}
    query: dict[str, str] = {}
    body: dict[str, Any] = {}
    for p in endpoint.get("params") or []:
        pname = str(p.get("name") or "")
        value = user_args.get(pname) if p.get("credential") else kwargs.get(pname)
        if value is None:
            continue
        value = str(value)
        pos = p.get("in")
        if pos == "header":
            headers[pname] = value
        elif pos == "path":
            url = url.replace("{" + pname + "}", value)
        elif pos == "body":
            body[pname] = value
        else:
            query[pname] = value
    return method, url, headers, query, body


async def _build_openapi_tool(
    tool_doc: dict, name: str, description: str, user_args: dict
) -> StructuredTool:
    """Build a tool from an OpenAPI endpoint configuration.

    参数表模型：endpoint.params 每项 {name, in(query/header/path/body),
    description, required, credential}——位置决定发送到哪，credential 的值
    来自工具级凭证（user_args，已解密），其余由 LLM 调用时填。
    旧模板模型（headers/params dict + {{user.x}}/{{llm.x}}）保留兼容。
    endpoint.response_notes（返回说明）附加到工具描述，帮助 AI 理解结果。
    """
    endpoint = tool_doc.get("endpoint", {})
    llm_args_schema = tool_doc.get("llm_args_schema", {})
    response_notes = str(endpoint.get("response_notes") or "").strip()
    if response_notes:
        description = f"{description}\n返回格式：{response_notes}".strip()

    args_model = _json_schema_to_pydantic(name, llm_args_schema)
    use_params_model = isinstance(endpoint.get("params"), list)

    async def _handler(**kwargs: Any) -> str:
        if use_params_model:
            method, url, headers, params, body = _assemble_params_request(
                endpoint, kwargs, user_args
            )
            timeout = float(user_args.get("timeout", 30)) if "timeout" in user_args else 30.0
        else:
            # 旧模板模型（{{user.x}}/{{llm.x}} 渲染）——存量数据兼容
            context = {
                "user": user_args,   # Agent 绑定时填入（含解密后的凭据）
                "llm": kwargs,       # LLM 运行时填入
            }
            method = render_template(endpoint.get("method", "GET"), context).upper()
            url = render_template(endpoint.get("url", ""), context)
            headers = render_dict(endpoint.get("headers", {}), context)
            params = render_dict(endpoint.get("params", {}), context)
            body = endpoint.get("body")
            if body:
                body = render_dict(body, context)
            timeout = float(user_args.get("timeout", 30)) if "timeout" in user_args else 30.0

        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "GET":
                resp = await client.get(url, headers=headers, params=params)
            elif method == "POST":
                resp = await client.post(url, headers=headers, params=params, json=body or None)
            elif method == "PUT":
                resp = await client.put(url, headers=headers, params=params, json=body or None)
            elif method == "DELETE":
                resp = await client.delete(url, headers=headers, params=params)
            else:
                resp = await client.request(method, url, headers=headers, params=params, json=body or None)

        # Extract response path if configured
        response_path = endpoint.get("response_path", "")
        if response_path:
            try:
                data: Any = resp.json()
                for part in response_path.split("."):
                    if isinstance(data, dict):
                        data = data.get(part, data)
                    elif isinstance(data, list) and part.lstrip("-").isdigit():
                        # 数组下标（如 data.items.0.name）
                        idx = int(part)
                        data = data[idx] if -len(data) <= idx < len(data) else data
                return json.dumps(data, ensure_ascii=False, default=str)
            except Exception:
                return resp.text
        return resp.text

    return StructuredTool.from_function(
        coroutine=_handler,
        name=name,
        description=description,
        args_schema=args_model,
    )


# ---------------------------------------------------------------------------
# CodeToolBuilder
# ---------------------------------------------------------------------------


def _entry_script(code: str, func_name: str) -> str:
    """Wrap user code into a runnable script: call entry function with JSON
    args (argv[1]) and print the result (non-str results as JSON)."""
    return f"""
import json, sys

# --- User code ---
{code}
# --- End user code ---

_args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {{}}
_func = globals().get('{func_name}') or globals().get('run')
if _func is None:
    print("Error: function '{func_name}' or 'run' not found", file=sys.stderr)
    sys.exit(1)
_result = _func(**_args)
if not isinstance(_result, str):
    _result = json.dumps(_result, default=str, ensure_ascii=False)
print(_result)
"""


_tool_sandbox: DockerSandbox | None = None


def _get_tool_sandbox() -> DockerSandbox:
    """治理工具专用沙箱（进程级缓存）。

    与 LLM bash 沙箱（SANDBOX_NETWORK_MODE=none）的区别：治理工具经
    admin 审查+开启，功能上需要出网（SMTP/HTTP），默认 bridge 网络；
    进程隔离不变——工具代码读不到 worker 环境变量（密钥/凭证）与
    宿主文件系统。代码以 base64 管道传入，无需挂载。
    """
    global _tool_sandbox
    if _tool_sandbox is None:
        import tempfile
        from pathlib import Path

        from agent_flow_harness.sandbox.docker import (
            DockerSandbox,
            DockerSandboxConfig,
        )

        from app.core.config import settings

        _tool_sandbox = DockerSandbox(
            sandbox_id="tool-code",
            work_dir=Path(tempfile.gettempdir()) / "agentflow-tool-sandbox",
            mounts={},
            config=DockerSandboxConfig(
                image=settings.SANDBOX_IMAGE,
                enabled=settings.SANDBOX_ENABLED,
                allow_local_fallback=settings.SANDBOX_FALLBACK == "local",
                mem_limit=settings.SANDBOX_MEM_LIMIT,
                cpu_quota=settings.SANDBOX_CPU_QUOTA,
                timeout=settings.SANDBOX_TIMEOUT,
                max_output_bytes=settings.SANDBOX_MAX_OUTPUT_BYTES,
                network_mode=settings.TOOL_SANDBOX_NETWORK_MODE,
            ),
            timeout=settings.SANDBOX_TIMEOUT,
        )
    return _tool_sandbox


async def _build_code_tool(
    tool_doc: dict, name: str, description: str, user_args: dict
) -> StructuredTool:
    """Build a tool from user-defined Python code.

    治理工具代码在专用沙箱执行（Docker 隔离 / 开发环境显式降级 subprocess）：
    - 凭证（user_args 含敏感字段）以 USER_ 前缀环境变量透传进执行环境，
      不触碰 worker 进程环境（密钥不可窃取）；
    - LLM args 以 JSON argv 传给入口函数；
    - 同步执行放线程池，不阻塞 event loop（env 走子进程/容器注入，
      并发安全）。
    """
    code = tool_doc.get("code", "")
    llm_args_schema = tool_doc.get("llm_args_schema", {})

    args_model = _json_schema_to_pydantic(name, llm_args_schema)

    async def _handler(**kwargs: Any) -> str:
        import asyncio
        import base64
        import shlex

        from app.core.config import settings

        user_env: dict[str, str] = {}
        for k, v in user_args.items():
            user_env[f"USER_{k}"] = str(v)

        script = _entry_script(code, name)
        b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
        payload = json.dumps(kwargs, ensure_ascii=False, default=str)
        command = f"echo {b64} | base64 -d | python3 - {shlex.quote(payload)}"

        result = await asyncio.to_thread(
            _get_tool_sandbox().execute_command,
            command,
            timeout=settings.SANDBOX_TIMEOUT,
            env=user_env,
        )
        output = (result.stdout or "").strip()
        if result.exit_code != 0:
            err = (result.stderr or "").strip() or f"exit_code={result.exit_code}"
            return f"Error: {err[-2000:]}"
        return output

    return StructuredTool.from_function(
        coroutine=_handler,
        name=name,
        description=description,
        args_schema=args_model,
    )

