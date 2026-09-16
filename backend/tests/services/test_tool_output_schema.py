"""derive_output_schema 用例 — code 工具返回结构静态推导。

覆盖：
1. dict 字面量返回 → 字段名/类型/列表标记
2. 嵌套 dict → object 子字段
3. 多个 return 合并（重名保首个）
4. 标量/字符串返回 → {}（无字段可推导）
5. 与工具同名的入口函数（-/_ 变体）
6. 语法错误 / 无入口函数 → {}
7. 手工声明优先（create_tool 不覆盖非空 fields——经 generator 集成验证）
"""
from __future__ import annotations

import json

from app.services.tool_output_schema import derive_output_schema

# ── 1/2/3. dict 推导 ─────────────────────────────────────────────────


def test_dict_return_fields():
    code = (
        "def run(to: str) -> dict:\n"
        "    return {\n"
        "        'status': 'sent',\n"
        "        'count': 3,\n"
        "        ok: True,\n".replace("ok: True", "'ok': True")
        + "        'emails': ['a@x.com'],\n"
        "        'detail': {'id': 1},\n"
        "    }\n"
    )
    schema = derive_output_schema(code, "any-tool")
    fields = {f["name"]: f for f in schema["fields"]}
    assert schema["type"] == "object"
    assert fields["status"]["type"] == "string"
    assert fields["count"]["type"] == "number"
    assert fields["ok"]["type"] == "boolean"
    assert fields["emails"]["is_list"] is True and fields["emails"]["type"] == "string"
    assert fields["detail"]["type"] == "object"
    assert fields["detail"]["fields"][0]["name"] == "id"


def test_multiple_returns_merged():
    code = (
        "def run(x: int) -> dict:\n"
        "    if x > 0:\n"
        "        return {'status': 'ok', 'value': 1}\n"
        "    return {'status': 'error', 'reason': 'bad'}\n"
    )
    schema = derive_output_schema(code, "t")
    names = [f["name"] for f in schema["fields"]]
    assert names == ["status", "value", "reason"]  # 重名 status 保首个


# ── 4. 标量返回 → 空 ─────────────────────────────────────────────────


def test_scalar_return_empty():
    code = "def run(to: str) -> str:\n    return 'sent:' + to\n"
    assert derive_output_schema(code, "t") == {}


# ── 5. 与工具同名入口（变体） ────────────────────────────────────────


def test_tool_named_entry():
    code = (
        "def weather-query(city: str) -> dict:\n"
        "    return {'city': city, 'temp': 25}\n"
    )
    schema = derive_output_schema(code.replace("weather-query", "weather_query"), "weather-query")
    assert [f["name"] for f in schema["fields"]] == ["city", "temp"]


# ── 6. 容错 ──────────────────────────────────────────────────────────


def test_syntax_error_and_missing_entry():
    assert derive_output_schema("def broken(:\n", "t") == {}
    assert derive_output_schema("def other() -> dict:\n    return {'a': 1}\n", "t") == {}


# ── 7. generator 集成：AI 未声明 output_schema 时自动推导 ────────────


async def test_generator_derives_output_schema(monkeypatch):
    from app.services.tool_generator import ToolGeneratorService
    from langchain_core.messages import AIMessage

    payload = {
        "name": "calc-tool",
        "description": "计算",
        "source": "code",
        "llm_args_schema": {"type": "object", "properties": {"x": {"type": "integer"}}},
        "user_args_schema": {},
        "code": "def run(x: int) -> dict:\n    return {'doubled': x * 2, 'big': x > 10}\n",
        "output_schema": {},  # AI 没声明
        "tags": [],
    }
    reply = "已生成。\n```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"

    class _FakeLLM:
        async def ainvoke(self, messages):
            return AIMessage(content=reply)

    async def _build(model_id: str = ""):
        return _FakeLLM()

    monkeypatch.setattr(ToolGeneratorService, "_build_llm", _build)

    result = await ToolGeneratorService.generate([{"role": "user", "content": "翻倍计算工具"}])

    fields = {f["name"]: f for f in result["draft"]["output_schema"]["fields"]}
    # x * 2 是未知表达式 → 尽力而为回退 string；x > 10 比较表达式 → boolean
    assert fields["doubled"]["type"] == "string"
    assert fields["big"]["type"] == "boolean"
