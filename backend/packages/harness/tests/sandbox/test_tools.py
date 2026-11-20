"""AC7/AC8 cover: bash/read/write/edit/glob/grep 六工具委托 + 异常隔离。"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from langchain_core.tools import ToolException

from agent_flow_harness.sandbox.base import GrepMatch, Sandbox, SandboxResult
from agent_flow_harness.sandbox.context import (
    SandboxContext,
    reset_sandbox_context,
    set_sandbox_context,
)
from agent_flow_harness.sandbox.tools import bash, edit, grep, glob, read, write


def _mock_sandbox(
    exec_result: SandboxResult | None = None,
    exec_exc: Exception | None = None,
) -> MagicMock:
    sb = MagicMock(spec=Sandbox)
    sb.id = "mock"
    if exec_exc:
        sb.execute_command.side_effect = exec_exc
    else:
        sb.execute_command.return_value = exec_result or SandboxResult(
            stdout="ok", stderr="", exit_code=0
        )
    sb.read_file.return_value = "file content"
    sb.write_file.return_value = None
    sb.edit_file.return_value = "Successfully edited 'app.py' (1 replacement)."
    sb.glob.return_value = ["a.py", "b.py"]
    sb.grep.return_value = [GrepMatch(path="x.py", line_number=1, line="match")]
    return sb


def _set_ctx(sb):
    token = set_sandbox_context(SandboxContext(sandbox=sb))
    return token


@pytest.mark.asyncio
async def test_bash_delegates_to_sandbox():
    """AC7: bash 委托 sandbox.execute_command（timeout=None → 沿用沙箱默认超时）。"""
    sb = _mock_sandbox(SandboxResult(stdout="hello", stderr="", exit_code=0))
    token = _set_ctx(sb)
    try:
        result = await bash.ainvoke({"command": "echo hello"})
        assert "hello" in result
        sb.execute_command.assert_called_once_with("echo hello", timeout=None)
    finally:
        reset_sandbox_context(token)


@pytest.mark.asyncio
async def test_bash_timeout_passthrough():
    """timeout 参数透传 sandbox.execute_command。"""
    sb = _mock_sandbox(SandboxResult(stdout="ok", stderr="", exit_code=0))
    token = _set_ctx(sb)
    try:
        await bash.ainvoke({"command": "make build", "timeout": 300})
        sb.execute_command.assert_called_once_with("make build", timeout=300)
    finally:
        reset_sandbox_context(token)


@pytest.mark.asyncio
async def test_bash_includes_stderr_and_exit_code():
    sb = _mock_sandbox(SandboxResult(stdout="out", stderr="err", exit_code=2))
    token = _set_ctx(sb)
    try:
        result = await bash.ainvoke({"command": "x"})
        assert "out" in result
        assert "err" in result
        assert "2" in result
    finally:
        reset_sandbox_context(token)


@pytest.mark.asyncio
async def test_bash_exception_isolated():
    """AC8: sandbox 抛异常 → ToolException（由 wrapper 转 status="error"，循环不中断）。"""
    sb = _mock_sandbox(exec_exc=RuntimeError("boom"))
    token = _set_ctx(sb)
    try:
        with pytest.raises(ToolException, match="Error executing command: boom"):
            await bash.ainvoke({"command": "x"})
    finally:
        reset_sandbox_context(token)


@pytest.mark.asyncio
async def test_read_delegates():
    sb = _mock_sandbox()
    token = _set_ctx(sb)
    try:
        result = await read.ainvoke({"path": "app.py"})
        assert result == "file content"
        sb.read_file.assert_called_once_with("app.py", offset=1, limit=2000)
    finally:
        reset_sandbox_context(token)


@pytest.mark.asyncio
async def test_read_pagination_passthrough():
    """offset/limit 分页参数透传 sandbox.read_file。"""
    sb = _mock_sandbox()
    token = _set_ctx(sb)
    try:
        await read.ainvoke({"path": "app.py", "offset": 10, "limit": 5})
        sb.read_file.assert_called_once_with("app.py", offset=10, limit=5)
    finally:
        reset_sandbox_context(token)


@pytest.mark.asyncio
async def test_write_delegates():
    sb = _mock_sandbox()
    token = _set_ctx(sb)
    try:
        result = await write.ainvoke({"path": "out.txt", "content": "data"})
        assert "wrote" in result.lower() or "success" in result.lower()
        sb.write_file.assert_called_once_with("out.txt", "data")
    finally:
        reset_sandbox_context(token)


@pytest.mark.asyncio
async def test_edit_delegates():
    """edit 委托 sandbox.edit_file（含 replace_all 透传）。"""
    sb = _mock_sandbox()
    token = _set_ctx(sb)
    try:
        result = await edit.ainvoke({
            "path": "app.py", "old_string": "a", "new_string": "b",
        })
        assert "Successfully edited" in result
        sb.edit_file.assert_called_once_with("app.py", "a", "b", replace_all=False)

        await edit.ainvoke({
            "path": "app.py", "old_string": "a", "new_string": "b",
            "replace_all": True,
        })
        sb.edit_file.assert_called_with("app.py", "a", "b", replace_all=True)
    finally:
        reset_sandbox_context(token)


@pytest.mark.asyncio
async def test_edit_exception_isolated():
    """AC8: sandbox.edit_file 抛异常 → ToolException（由 wrapper 转 status="error"）。"""
    sb = _mock_sandbox()
    sb.edit_file.side_effect = ValueError("old_string not found in 'app.py'.")
    token = _set_ctx(sb)
    try:
        with pytest.raises(ToolException, match="Error editing file"):
            await edit.ainvoke({
                "path": "app.py", "old_string": "a", "new_string": "b",
            })
    finally:
        reset_sandbox_context(token)


@pytest.mark.asyncio
async def test_edit_batch_delegates_to_edit_file_many():
    """edits[] 批量 → 委托 sandbox.edit_file_many（快照匹配由 sandbox 层负责）。"""
    sb = _mock_sandbox()
    sb.edit_file_many.return_value = "Successfully edited 'app.py' (2 replacements across 2 edits)."
    token = _set_ctx(sb)
    try:
        result = await edit.ainvoke({
            "path": "app.py",
            "edits": [
                {"old_string": "a", "new_string": "A"},
                {"old_string": "b", "new_string": "B"},
            ],
        })
        assert "2 replacements across 2 edits" in result
        sb.edit_file_many.assert_called_once_with(
            "app.py", [("a", "A"), ("b", "B")], replace_all=False
        )
        sb.edit_file.assert_not_called()
    finally:
        reset_sandbox_context(token)


@pytest.mark.asyncio
async def test_edit_batch_json_string_tolerated():
    """GLM 系 quirk：edits 传 JSON 字符串 → 自动解析（pi 同款容错）。"""
    import json

    sb = _mock_sandbox()
    sb.edit_file_many.return_value = "ok"
    token = _set_ctx(sb)
    try:
        await edit.ainvoke({
            "path": "app.py",
            "edits": json.dumps([
                {"old_string": "a", "new_string": "A"},
                {"old_string": "b", "new_string": "B"},
            ]),
        })
        sb.edit_file_many.assert_called_once_with(
            "app.py", [("a", "A"), ("b", "B")], replace_all=False
        )
    finally:
        reset_sandbox_context(token)


@pytest.mark.asyncio
async def test_edit_merges_legacy_single_with_edits():
    """old_string/new_string 与 edits[] 同时提供 → 合并（pi 同款语义）。"""
    sb = _mock_sandbox()
    sb.edit_file_many.return_value = "ok"
    token = _set_ctx(sb)
    try:
        await edit.ainvoke({
            "path": "app.py",
            "old_string": "c", "new_string": "C",
            "edits": [{"old_string": "a", "new_string": "A"}],
        })
        sb.edit_file_many.assert_called_once_with(
            "app.py", [("a", "A"), ("c", "C")], replace_all=False
        )
    finally:
        reset_sandbox_context(token)


@pytest.mark.asyncio
async def test_edit_requires_old_new_or_edits():
    """两者都缺 → ToolException 引导模型修正入参。"""
    sb = _mock_sandbox()
    token = _set_ctx(sb)
    try:
        with pytest.raises(ToolException, match="old_string\\+new_string or a non-empty edits"):
            await edit.ainvoke({"path": "app.py"})
    finally:
        reset_sandbox_context(token)


@pytest.mark.asyncio
async def test_glob_delegates():
    sb = _mock_sandbox()
    token = _set_ctx(sb)
    try:
        result = await glob.ainvoke({"path": ".", "pattern": "*.py"})
        assert "a.py" in result
        sb.glob.assert_called_once_with(".", "*.py")
    finally:
        reset_sandbox_context(token)


@pytest.mark.asyncio
async def test_grep_delegates():
    sb = _mock_sandbox()
    token = _set_ctx(sb)
    try:
        result = await grep.ainvoke({"path": ".", "pattern": "match"})
        assert "match" in result
        sb.grep.assert_called_once_with(
            ".", "match", context=0, ignore_case=False, glob_filter=None
        )
    finally:
        reset_sandbox_context(token)


@pytest.mark.asyncio
async def test_grep_head_limit_truncates():
    """超过 head_limit 的匹配截断并附提示（默认 100 同理，防上下文溢出）。"""
    sb = _mock_sandbox()
    sb.grep.return_value = [
        GrepMatch(path="x.py", line_number=i, line=f"match-{i}") for i in range(1, 6)
    ]
    token = _set_ctx(sb)
    try:
        result = await grep.ainvoke({"path": ".", "pattern": "match", "head_limit": 2})
        assert "match-1" in result and "match-2" in result
        assert "match-3" not in result
        assert "[showing 2 of 5 matches" in result
    finally:
        reset_sandbox_context(token)


@pytest.mark.asyncio
async def test_grep_under_limit_no_note():
    sb = _mock_sandbox()
    token = _set_ctx(sb)
    try:
        result = await grep.ainvoke({"path": ".", "pattern": "match"})
        assert "showing first" not in result
    finally:
        reset_sandbox_context(token)


@pytest.mark.asyncio
async def test_tool_without_context_raises_tool_exception():
    """未注入 sandbox context → ToolException（wrapper 转 status="error"，不炸循环）。"""
    with pytest.raises(ToolException, match="sandbox not initialized"):
        await bash.ainvoke({"command": "x"})


@pytest.mark.asyncio
async def test_bash_does_not_block_event_loop():
    """execute_command 是阻塞调用，必须经线程池卸载——阻塞期间事件循环上的
    其他任务仍能推进（一条慢命令不能卡死整个循环）。"""
    import asyncio
    import time

    sb = _mock_sandbox()

    def _slow_exec(_command: str, timeout: int | None = None) -> SandboxResult:
        time.sleep(0.3)
        return SandboxResult(stdout="slow-done", stderr="", exit_code=0)

    sb.execute_command.side_effect = _slow_exec
    token = _set_ctx(sb)
    try:
        order: list[str] = []

        async def _probe() -> None:
            order.append("probe")

        task = asyncio.create_task(bash.ainvoke({"command": "slow"}))
        await asyncio.sleep(0.05)  # 让 bash 进入线程池执行
        probe_task = asyncio.create_task(_probe())
        result = await task
        order.append("bash")
        await probe_task
        assert "slow-done" in result
        # probe 必须在 bash 执行期间完成；若在协程内直调阻塞 API，
        # probe 只能排在 bash 完成之后。
        assert order.index("probe") < order.index("bash"), (
            f"事件循环在 bash 执行期间被阻塞: order={order}"
        )
    finally:
        reset_sandbox_context(token)


@pytest.mark.asyncio
async def test_grep_output_modes_and_offset():
    """files_with_matches/count 输出模式 + offset 翻页。"""
    sb = _mock_sandbox()
    sb.grep.return_value = [
        GrepMatch(path="a.py", line_number=i, line=f"m{i}") for i in range(1, 4)
    ] + [GrepMatch(path="b.py", line_number=9, line="m9")]
    token = _set_ctx(sb)
    try:
        files = await grep.ainvoke(
            {"path": ".", "pattern": "m", "output_mode": "files_with_matches"}
        )
        assert "a.py" in files and "b.py" in files
        assert "m1" not in files

        count = await grep.ainvoke(
            {"path": ".", "pattern": "m", "output_mode": "count"}
        )
        assert "a.py: 3" in count and "b.py: 1" in count

        paged = await grep.ainvoke(
            {"path": ".", "pattern": "m", "offset": 3, "head_limit": 10}
        )
        assert "m9" in paged and "m1" not in paged  # offset=3 跳过 a.py 的 3 条
        assert "[showing 1 of 4 matches (offset 3)" in paged
    finally:
        reset_sandbox_context(token)


@pytest.mark.asyncio
async def test_grep_context_passthrough():
    """context/ignore_case/glob_filter 透传 sandbox.grep。"""
    sb = _mock_sandbox()
    token = _set_ctx(sb)
    try:
        await grep.ainvoke({
            "path": ".", "pattern": "x", "context": 2,
            "ignore_case": True, "glob_filter": "*.py",
        })
        sb.grep.assert_called_once_with(
            ".", "x", context=2, ignore_case=True, glob_filter="*.py"
        )
    finally:
        reset_sandbox_context(token)
