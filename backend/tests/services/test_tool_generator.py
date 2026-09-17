"""normalize_definition — 工具定义校验/规整测试（tool-forge 共享模块）。

原「单次对话式生成」路径（generate() 循环 + /generate 端点）已被工具工坊
agent 取代并移除；本文件只覆盖工坊 submit_definition 复用的校验口径：
名称规则 / source 判定 / code 与 openapi 完整性 / 依赖白名单（提交时拦截）/
schema 规整 / output_schema 静态推导。
"""
from __future__ import annotations

import pytest
from app.services.tool_generator import normalize_definition
from app.services.user_tool_service import UserToolError

CODE = "def run(text: str) -> str:\n    return text"


def _code_draft(**overrides):
    base = {
        "name": "echo",
        "description": "回显",
        "source": "code",
        "code": CODE,
        "llm_args_schema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "输入"}},
            "required": ["text"],
        },
        "user_args_schema": {},
        "tags": ["util", " "],
    }
    base.update(overrides)
    return base


def test_normalize_code_draft():
    d = normalize_definition(_code_draft())
    assert d["name"] == "echo" and d["source"] == "code"
    assert d["llm_args_schema"]["properties"]["text"]["type"] == "string"
    assert d["user_args_schema"] == {}  # 无 properties 归空
    assert d["endpoint"] == {}  # code 时清空 endpoint
    assert d["tags"] == ["util"]  # 空白标签剔除


def test_normalize_invalid_name_rejected():
    with pytest.raises(UserToolError):
        normalize_definition(_code_draft(name="bad name!"))


def test_normalize_code_missing_rejected():
    with pytest.raises(UserToolError):
        normalize_definition(_code_draft(code="   "))


def test_normalize_openapi_requires_url():
    with pytest.raises(UserToolError):
        normalize_definition({"name": "api", "source": "openapi", "endpoint": {}})
    d = normalize_definition({
        "name": "api",
        "source": "openapi",
        "endpoint": {"method": "GET", "url": "https://x.io/w", "params": []},
    })
    assert d["endpoint"]["url"] == "https://x.io/w"
    assert d["code"] == ""  # openapi 时清空 code


def test_normalize_source_hint_overrides():
    d = normalize_definition(_code_draft(source="openapi"), source_hint="code")
    assert d["source"] == "code"  # hint 优先（工坊入口指定类型）
    # 非法 source 回退 code
    assert normalize_definition(_code_draft(source="mcp"))["source"] == "code"


def test_normalize_rejects_banned_import_at_submit():
    """依赖白名单在提交时拦截（回归：旧 generate() 的校验口径，不能拖到
    run_test 才报）。"""
    with pytest.raises(UserToolError):
        normalize_definition(_code_draft(code="import flask\n" + CODE))


def test_normalize_derives_output_schema():
    """未声明返回结构——按代码静态推导（return 字面量键）。"""
    code = 'def run() -> dict:\n    return {"status": "ok"}'
    d = normalize_definition(_code_draft(code=code))
    names = [f["name"] for f in d["output_schema"].get("fields", [])]
    assert "status" in names


def test_normalize_manual_output_schema_wins():
    fields = {"type": "object", "fields": [{"name": "custom", "type": "string"}]}
    d = normalize_definition(_code_draft(output_schema=fields))
    assert d["output_schema"]["fields"][0]["name"] == "custom"


def test_normalize_rejects_env_name_schema_drift():
    """代码读取的 USER_ 环境变量必须在 user_args_schema 声明（防
    schema 说 A、代码读 B——运行期才报缺少凭证、AI 误判沙箱限制）。"""
    code = 'import os\n\ndef run() -> str:\n    return os.environ["USER_smtp_server"]'
    with pytest.raises(UserToolError, match="smtp_server"):
        normalize_definition(_code_draft(code=code))
    # 参数名与代码一致 → 通过
    ok = normalize_definition(_code_draft(
        code=code,
        user_args_schema={
            "type": "object",
            "properties": {"smtp_server": {"type": "string", "sensitive": True}},
        },
    ))
    assert "smtp_server" in ok["user_args_schema"]["properties"]


def test_normalize_env_case_mismatch_called_out():
    """大小写漂移（代码按环境变量惯例转大写）单独点名——环境变量区分大小写。"""
    code = 'import os\n\ndef run() -> str:\n    return os.environ["USER_SMTP_HOST"]'
    with pytest.raises(UserToolError, match="仅大小写不同"):
        normalize_definition(_code_draft(
            code=code,
            user_args_schema={
                "type": "object",
                "properties": {"smtp_host": {"type": "string", "sensitive": True}},
            },
        ))
