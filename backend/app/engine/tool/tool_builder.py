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

    Supports basic types: string, integer, number, boolean, array (多附件
    等 list 参数场景，元素不细分校验). Falls back to ``str`` for unknown
    types.
    """
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    fields: dict[str, Any] = {}

    type_map = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
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
    args (argv[1]) and print the result (non-str results as JSON).

    工作区根探测：容器内工作区挂载于 /workspace（cwd 为 /workspace/tmp），
    本地降级时 cwd 为 {root}/tmp——chdir 到工作区根后，用户代码统一用
    相对路径（input/xxx 读、output/xxx 写）。无挂载（无工作区）时探测不
    命中，cwd 保持 tmp，行为与旧版一致。
    """
    return f"""
import json, os, sys

# 工作区根探测（容器 /workspace → 本地 cwd/..），统一相对路径访问 input/output
for _root in ("/workspace", os.path.join(os.getcwd(), "..")):
    if os.path.isdir(os.path.join(_root, "input")) or os.path.isdir(os.path.join(_root, "output")):
        os.chdir(_root)
        break

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
    """治理工具专用沙箱（进程级缓存，无挂载）。

    与 LLM bash 沙箱（SANDBOX_NETWORK_MODE=none）的区别：治理工具经
    admin 审查+开启，功能上需要出网（SMTP/HTTP），默认 bridge 网络；
    进程隔离不变——工具代码读不到 worker 环境变量（密钥/凭证）与
    宿主文件系统。代码以 base64 管道传入，无需挂载。

    仅用于无工作区场景（工具预览等）；执行上下文有工作区时改用
    :func:`_get_workspace_tool_sandbox`（挂载 input/output/tmp）。
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
        from app.engine.tool.workspace import sandbox_bind_source_mapper

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
                bind_source_mapper=sandbox_bind_source_mapper(),
            ),
            timeout=settings.SANDBOX_TIMEOUT,
        )
    return _tool_sandbox


def _get_workspace_tool_sandbox(workspace: Any) -> DockerSandbox:
    """挂载当前工作区的治理工具沙箱（文件读写通道）。

    mounts 与 LLM bash 沙箱同约定：input 只读、output/tmp 可写（ro/rw
    由 DockerSandbox 按 input 名约定处理），容器内挂到 /workspace/{name}；
    网络仍为 TOOL_SANDBOX_NETWORK_MODE（治理工具需出网）。每次现建——
    init 仅 mkdir + 路径解析，docker client 到执行时才创建，无缓存必要。

    预建三个目录：既是 chdir 探测依据，也避免 Docker 自动以 root 创建
    缺失的 bind mount 源目录（属主错位导致容器内不可写）。
    """
    from agent_flow_harness.sandbox.docker import (
        DockerSandbox,
        DockerSandboxConfig,
    )

    from app.core.config import settings
    from app.engine.tool.workspace import sandbox_bind_source_mapper

    for d in (workspace.input_dir, workspace.output_dir, workspace.tmp_dir):
        d.mkdir(parents=True, exist_ok=True)

    return DockerSandbox(
        sandbox_id="tool-code-ws",
        work_dir=workspace.tmp_dir,
        mounts={
            "input": workspace.input_dir,
            "output": workspace.output_dir,
            "tmp": workspace.tmp_dir,
        },
        config=DockerSandboxConfig(
            image=settings.SANDBOX_IMAGE,
            enabled=settings.SANDBOX_ENABLED,
            allow_local_fallback=settings.SANDBOX_FALLBACK == "local",
            mem_limit=settings.SANDBOX_MEM_LIMIT,
            cpu_quota=settings.SANDBOX_CPU_QUOTA,
            timeout=settings.SANDBOX_TIMEOUT,
            max_output_bytes=settings.SANDBOX_MAX_OUTPUT_BYTES,
            network_mode=settings.TOOL_SANDBOX_NETWORK_MODE,
            # backend 容器化时把 volumes 源换算成 daemon 可见的宿主路径
            bind_source_mapper=sandbox_bind_source_mapper(),
        ),
        timeout=settings.SANDBOX_TIMEOUT,
    )


# ---------------------------------------------------------------------------
# CodeTool 文件通道：file_id 解析暂存 + output/ 产物报告
# ---------------------------------------------------------------------------

_FILE_ID_RE = re.compile(r"^file_[0-9A-Za-z]+$")

_FILE_CONVENTION_NOTE = (
    "文件支持：参数值可直接传 file_id（自动解析为 input/ 下可读路径）"
    "或工作区相对路径（input/ 只读，output/ 可写）；需产出文件时写入 "
    "output/ 目录，产物会自动注册供下载与下游节点引用。"
)


async def _resolve_file_args(kwargs: dict[str, Any], workspace: Any) -> dict[str, Any]:
    """file_id 参数值 → input/ 暂存路径。

    扫描顶层与 list 内的字符串参数值：命中 file_library（且属于当前
    用户）的 file_id 暂存到 ``input/_staged/{file_id}/{原名}`` 并把参数
    值替换为该工作区相对路径——LLM 传 file_id，用户代码直接 open()。
    未命中（非 file_id / 查无此文件）原样传递；非本人文件拒绝解析
    （防越权读他人 file_library）。重复出现的 file_id 复用同一暂存路径。
    """
    from app.services.file_service import FileService
    from app.services.file_storage import LocalFileStorage

    file_service = FileService(LocalFileStorage())
    staged: dict[str, str] = {}

    async def _resolve(value: Any) -> Any:
        if isinstance(value, list):
            return [await _resolve(v) for v in value]
        if isinstance(value, dict):
            # 工作流 {{node.files}} 整体渲染出的结构化引用（元素为
            # {file_id, name, ...}）——取 file_id 归一化后按普通 id 解析；
            # 无 file_id 的 dict 原样穿透（调用方自有语义）
            fid = value.get("file_id") or value.get("id")
            if isinstance(fid, str) and _FILE_ID_RE.match(fid):
                return await _resolve(fid)
            return value
        if not (isinstance(value, str) and _FILE_ID_RE.match(value)):
            return value
        if value in staged:
            return staged[value]
        try:
            fref = await file_service.get(value)
        except Exception:
            fref = None
        if fref is None or fref.owner_user_id != workspace.user_id:
            return value
        try:
            loaded = await file_service.load_content(value)
        except Exception:
            return value
        if loaded is None:
            return value
        staged[value] = _stage_library_file(fref, loaded[1], workspace)
        logger.info(
            "code_tool_file_staged", file_id=value, name=fref.name, size=fref.size
        )
        return staged[value]

    return {k: await _resolve(v) for k, v in kwargs.items()}


def _stage_library_file(fref: Any, data: bytes, workspace: Any) -> str:
    """暂存 file_library 文件到 input/，返回工作区相对路径。

    幂等：目标已存在同名同大小直接复用；先写临时文件再 rename，避免
    并发调用读到半写文件。文件名取原名的 basename（防路径注入）。
    """
    from pathlib import Path

    safe_name = Path(fref.name).name or fref.id
    dest_dir = workspace.input_dir / "_staged" / fref.id
    dest = dest_dir / safe_name
    if dest.exists() and dest.stat().st_size == len(data):
        return f"input/_staged/{fref.id}/{safe_name}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{safe_name}.tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return f"input/_staged/{fref.id}/{safe_name}"


def _snapshot_output(output_dir: Any) -> dict[str, tuple[float, int]]:
    """记录 output/ 现有文件 {相对路径: (mtime, size)}，供事后识别本次产物。"""
    if not output_dir.exists():
        return {}
    snapshot: dict[str, tuple[float, int]] = {}
    for p in output_dir.rglob("*"):
        if p.is_file():
            st = p.stat()
            snapshot[str(p.relative_to(output_dir))] = (st.st_mtime, st.st_size)
    return snapshot


def _append_output_files_report(
    output: str, output_dir: Any, snapshot: dict[str, tuple[float, int]]
) -> str:
    """把本次新增/变更的 output/ 产物清单附加到结果文本。

    workflow 场景 Agent/工具节点会另行扫描 output/ 注册 file_library，
    chat 场景会话文件列表直接列 output/ 目录——此处清单是给 LLM 的
    产物路径提示（可继续引用/转述给用户）。
    """
    current = _snapshot_output(output_dir)
    fresh = [rel for rel, (mt, _) in current.items() if snapshot.get(rel, (0.0, 0))[0] != mt]
    if not fresh:
        return output
    lines = [f"- output/{rel} ({current[rel][1] / 1024:.1f} KB)" for rel in sorted(fresh)]
    return f"{output}\n\n[output_files]\n" + "\n".join(lines)


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

    文件通道（TOOL_SANDBOX_MOUNT_WORKSPACE 开启且有工作区时）：
    - 挂载当前工作区（chat 会话 / workflow 任务，由 resolve_harness_
      context 在工具调用时刻设置的 contextvar 提供）——input 只读、
      output/tmp 可写，用户代码统一相对路径访问；
    - 参数中的 file_id 自动解析暂存为 input/ 路径（见 _resolve_file_args）；
    - 执行后扫描 output/ 新增文件附加产物清单（见 _append_output_files_report）。
    """
    from app.core.config import settings

    code = tool_doc.get("code", "")
    llm_args_schema = tool_doc.get("llm_args_schema", {})

    if settings.TOOL_SANDBOX_MOUNT_WORKSPACE:
        description = f"{description}\n{_FILE_CONVENTION_NOTE}".strip()

    args_model = _json_schema_to_pydantic(name, llm_args_schema)

    async def _handler(**kwargs: Any) -> str:
        import asyncio
        import base64
        import shlex

        workspace = None
        if settings.TOOL_SANDBOX_MOUNT_WORKSPACE:
            from app.engine.agent.builtin_tools import _get_workspace

            workspace = _get_workspace()

        if workspace is not None:
            kwargs = await _resolve_file_args(kwargs, workspace)
            sandbox = _get_workspace_tool_sandbox(workspace)
        else:
            sandbox = _get_tool_sandbox()

        user_env: dict[str, str] = {}
        for k, v in user_args.items():
            user_env[f"USER_{k}"] = str(v)

        script = _entry_script(code, name)
        b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
        payload = json.dumps(kwargs, ensure_ascii=False, default=str)
        command = f"echo {b64} | base64 -d | python3 - {shlex.quote(payload)}"

        output_snapshot = _snapshot_output(workspace.output_dir) if workspace else {}

        result = await asyncio.to_thread(
            sandbox.execute_command,
            command,
            timeout=settings.SANDBOX_TIMEOUT,
            env=user_env,
        )
        output = (result.stdout or "").strip()
        if result.exit_code != 0:
            err = (result.stderr or "").strip() or f"exit_code={result.exit_code}"
            return f"Error: {err[-2000:]}"
        if workspace is not None:
            output = _append_output_files_report(output, workspace.output_dir, output_snapshot)
        return output

    return StructuredTool.from_function(
        coroutine=_handler,
        name=name,
        description=description,
        args_schema=args_model,
    )

