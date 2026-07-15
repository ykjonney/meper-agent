"""端到端集成: 真实 LocalSandbox + ContextVar 注入 + 工具委托。

验证工具层与真实 LocalSandbox 的完整往返：write→read、bash→glob→read、
grep、路径越权通过工具层被友好拦截、超时隔离。
"""
from __future__ import annotations

import pytest

from agent_flow_harness.sandbox.context import (
    SandboxContext,
    reset_sandbox_context,
    set_sandbox_context,
)
from agent_flow_harness.sandbox.local import LocalSandbox
from agent_flow_harness.sandbox.tools import bash, glob, grep, read, write


@pytest.fixture
def sandbox_ctx(tmp_path):
    sb = LocalSandbox(sandbox_id="itest", work_dir=tmp_path, output_dir=tmp_path / "output", timeout=10)
    token = set_sandbox_context(SandboxContext(sandbox=sb))
    yield sb
    reset_sandbox_context(token)


@pytest.mark.asyncio
async def test_full_write_read_cycle(sandbox_ctx):
    """write 写到 output_dir, bash 也能读取(output 是 work_dir 的子目录)。"""
    await write.ainvoke({"path": "note.txt", "content": "hello sandbox"})
    # write goes to output_dir; read from work_dir won't find it directly,
    # but bash can access it via relative path (output/ is under work_dir.parent)
    content = await bash.ainvoke({"command": "cat output/note.txt"})
    assert "hello sandbox" in content


@pytest.mark.asyncio
async def test_bash_creates_then_glob_reads(sandbox_ctx):
    """bash 创建文件 → glob 匹配 → read 读取。"""
    await bash.ainvoke({"command": "echo 'x' > created.py"})
    matches = await glob.ainvoke({"path": ".", "pattern": "*.py"})
    assert "created.py" in matches
    content = await read.ainvoke({"path": "created.py"})
    assert "x" in content


@pytest.mark.asyncio
async def test_grep_finds_written_content(sandbox_ctx):
    """write 写到 output_dir, bash 创建文件到 work_dir → grep 搜索 work_dir。"""
    await bash.ainvoke({"command": "echo 'TODO: fix this' > search.py"})
    result = await grep.ainvoke({"path": ".", "pattern": "TODO"})
    assert "TODO" in result
    assert "search.py" in result


@pytest.mark.asyncio
async def test_path_traversal_via_tool_blocked(sandbox_ctx):
    """通过工具层触发路径越权 → 友好错误字符串（不 raise）。"""
    result = await read.ainvoke({"path": "../../../etc/passwd"})
    assert "Error" in result


@pytest.mark.asyncio
async def test_bash_timeout_isolated(tmp_path):
    """超时 → 错误字符串，不中断主流程。用短 timeout 避免测试慢。"""
    sb = LocalSandbox(sandbox_id="to", work_dir=tmp_path, timeout=1)
    token = set_sandbox_context(SandboxContext(sandbox=sb))
    try:
        result = await bash.ainvoke({"command": "sleep 30"})
        assert "Error" in result
        assert "timed out" in result.lower()
    finally:
        reset_sandbox_context(token)
