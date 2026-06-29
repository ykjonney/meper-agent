"""端到端真实模型测试（需要真实 LLM API key，默认跳过）。

运行方式：
    cd packages/harness
    export E2E_LLM_API_KEY=sk-xxx
    uv run pytest tests/test_e2e_live.py -v --no-header -p no:warnings

验证 harness 完整链路：create_agent → run/stream → 工具执行 → sandbox → 事件流。
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# 需要 API key 才运行
_API_KEY = os.environ.get("E2E_LLM_API_KEY", "")
_LLM_MODEL = os.environ.get("E2E_LLM_MODEL", "qwen3.7-plus")
_LLM_BASE_URL = os.environ.get("E2E_LLM_BASE_URL", "https://dashscope.aliyuncs.com/apps/anthropic")

pytestmark = pytest.mark.skipif(
    not _API_KEY,
    reason="设置 E2E_LLM_API_KEY 环境变量以运行真实模型端到端测试",
)


def _make_llm():
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(
        model=_LLM_MODEL,
        api_key=_API_KEY,
        base_url=_LLM_BASE_URL,
        max_tokens=2000,
        temperature=0.7,
    )


@pytest.fixture
def sandbox_workdir():
    tmp = Path(tempfile.mkdtemp())
    return tmp


@pytest.mark.asyncio
async def test_e2e_simple_chat(sandbox_workdir):
    """端到端：简单对话。"""
    from agent_flow_harness import AgentConfig, create_agent, LocalSandbox

    sb = LocalSandbox(sandbox_id="e2e", work_dir=sandbox_workdir, timeout=30)
    config = AgentConfig(
        name="e2e",
        system_prompt="你是测试助手。用中文简短回答。",
        builtin_tools=None,
    )
    agent = create_agent(config, model=_make_llm())
    result = await agent.run("你好")
    assert len(result) > 0
    assert "你好" in result or "帮助" in result or "助手" in result


@pytest.mark.asyncio
async def test_e2e_bash_tool(sandbox_workdir):
    """端到端：bash 工具执行。"""
    from agent_flow_harness import AgentConfig, create_agent, LocalSandbox

    sb = LocalSandbox(sandbox_id="e2e", work_dir=sandbox_workdir, timeout=30)
    config = AgentConfig(
        name="e2e",
        system_prompt="你是测试助手。如果用户让你执行命令，用 bash 工具。",
        builtin_tools=["bash"],
        exclude_tools=["delegate_to_subagent", "ask_clarification", "tool_search", "glob", "grep", "read", "write"],
        sandbox=sb,
    )
    agent = create_agent(config, model=_make_llm())
    result = await agent.run("请用 bash 执行 echo hello_harness 并告诉我输出")
    assert "hello_harness" in result


@pytest.mark.asyncio
async def test_e2e_write_read(sandbox_workdir):
    """端到端：write + read 文件往返。"""
    from agent_flow_harness import AgentConfig, create_agent, LocalSandbox

    sb = LocalSandbox(sandbox_id="e2e", work_dir=sandbox_workdir, timeout=30)
    config = AgentConfig(
        name="e2e",
        system_prompt="你是测试助手。按用户要求操作文件。",
        builtin_tools=["write", "read"],
        exclude_tools=["delegate_to_subagent", "ask_clarification", "tool_search", "glob", "grep", "bash"],
        sandbox=sb,
    )
    agent = create_agent(config, model=_make_llm())
    result = await agent.run(
        '请用 write 工具写入文件 test.txt 内容是 "harness e2e ok"，'
        "然后用 read 工具读取它，告诉我内容"
    )
    assert "harness e2e ok" in result
    # 文件确实写到了 sandbox work_dir
    written = (sandbox_workdir / "test.txt").read_text()
    assert "harness e2e ok" in written


@pytest.mark.asyncio
async def test_e2e_stream_events(sandbox_workdir):
    """端到端：stream 事件流（tool_call + tool_result + final_answer_delta）。"""
    from agent_flow_harness import AgentConfig, create_agent, LocalSandbox

    sb = LocalSandbox(sandbox_id="e2e", work_dir=sandbox_workdir, timeout=30)
    config = AgentConfig(
        name="e2e",
        system_prompt="你是测试助手。用 bash 执行命令。",
        builtin_tools=["bash"],
        exclude_tools=["delegate_to_subagent", "ask_clarification", "tool_search", "glob", "grep", "read", "write"],
        sandbox=sb,
    )
    agent = create_agent(config, model=_make_llm())

    events: list[dict] = []

    async def collect(ev):
        events.append(ev)

    await agent.stream("请用 bash 执行 echo stream_test", on_event=collect)

    # 应收到 tool_call + tool_result + final_answer 事件
    types = {ev["type"] for ev in events}
    assert "tool_call" in types
    assert "tool_result" in types
    assert "final_answer" in types
    # tool_result 应包含 stream_test
    tool_results = [ev for ev in events if ev["type"] == "tool_result"]
    assert any("stream_test" in ev.get("content", "") for ev in tool_results)
