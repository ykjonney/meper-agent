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
    """AC7: bash 委托 sandbox.execute_command。"""
    sb = _mock_sandbox(SandboxResult(stdout="hello", stderr="", exit_code=0))
    token = _set_ctx(sb)
    try:
        result = await bash.ainvoke({"command": "echo hello"})
        assert "hello" in result
        sb.execute_command.assert_called_once_with("echo hello")
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
        sb.read_file.assert_called_once_with("app.py")
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
        sb.grep.assert_called_once_with(".", "match")
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

    def _slow_exec(_command: str) -> SandboxResult:
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
