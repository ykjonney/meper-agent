"""后台任务（run_in_background / bash_output）— 真实 LocalSandbox 集成测试。

覆盖：启动立即返回 / 探活 / 增量读取 / 退出码 / block 等待 / 软超时 /
未知任务 / task_id 校验。工具层走 ContextVar 注入（与生产一致）。
"""
from __future__ import annotations

import time

import pytest
from langchain_core.tools import ToolException

from agent_flow_harness.sandbox.bg_tasks import (
    build_output_exec,
    build_start_exec,
    is_valid_task_id,
    new_task_id,
    parse_output_exec,
)
from agent_flow_harness.sandbox.context import (
    SandboxContext,
    reset_sandbox_context,
    set_sandbox_context,
)
from agent_flow_harness.sandbox.local import LocalSandbox
from agent_flow_harness.sandbox.tools import bash, bash_output


@pytest.fixture
def sandbox_ctx(tmp_path):
    sb = LocalSandbox(sandbox_id="bg-test", work_dir=tmp_path, timeout=10)
    token = set_sandbox_context(SandboxContext(sandbox=sb))
    yield sb
    reset_sandbox_context(token)


def test_task_id_shape():
    tid = new_task_id()
    assert is_valid_task_id(tid)
    assert not is_valid_task_id("bg-XYZ!")  # 防注入：非法字符拒绝
    assert not is_valid_task_id("rm -rf")


async def test_background_start_and_finish(sandbox_ctx):
    """启动立即返回 → 轮询到 finished + 输出 + 退出码。"""
    start = await bash.ainvoke({
        "command": "echo hello-bg; echo done-marker",
        "run_in_background": True,
    })
    assert "Started background task" in start
    tid = start.split("task ")[1].split(".")[0]

    result = await bash_output.ainvoke({"command_id": tid, "block": True, "block_timeout": 20})
    assert f"task {tid}: finished" in result
    assert "exit=0" in result
    assert "hello-bg" in result
    assert "done-marker" in result


async def test_background_running_status_and_incremental(sandbox_ctx):
    """运行中探活 + 增量读取（第二次调用只返回新增输出）。"""
    tid_start = await bash.ainvoke({
        "command": "echo part-1; sleep 2; echo part-2",
        "run_in_background": True,
    })
    tid = tid_start.split("task ")[1].split(".")[0]

    first = await bash_output.ainvoke({"command_id": tid})
    assert "running" in first
    assert "part-1" in first

    time.sleep(2.2)
    second = await bash_output.ainvoke({"command_id": tid})
    assert "finished" in second
    assert "part-2" in second


async def test_background_block_wait(sandbox_ctx):
    """block 模式：在本调用内等待任务结束。"""
    start = await bash.ainvoke({
        "command": "sleep 1; echo waited-done",
        "run_in_background": True,
    })
    tid = start.split("task ")[1].split(".")[0]
    result = await bash_output.ainvoke({"command_id": tid, "block": True, "block_timeout": 20})
    assert "finished" in result
    assert "waited-done" in result


async def test_background_soft_timeout(sandbox_ctx, monkeypatch):
    """软超时：超过生命周期的运行中任务被 kill 并标记 timeout。"""
    from agent_flow_harness.sandbox import bg_tasks

    monkeypatch.setattr(bg_tasks, "BG_TASK_MAX_LIFETIME", 1)
    start = await bash.ainvoke({
        "command": "sleep 30",
        "run_in_background": True,
    })
    tid = start.split("task ")[1].split(".")[0]
    time.sleep(1.2)
    result = await bash_output.ainvoke({"command_id": tid})
    assert "timeout" in result


async def test_unknown_task_and_invalid_id(sandbox_ctx):
    result = await bash_output.ainvoke({"command_id": "bg-deadbeef"})
    assert "Unknown background task" in result
    with pytest.raises(ToolException, match="Invalid command_id"):
        await bash_output.ainvoke({"command_id": "evil; rm -rf /"})


def test_build_output_exec_unknown_task_marker(tmp_path):
    """build_output_exec：未知任务输出 status=unknown 标记行。"""
    import subprocess

    wrapped, parse_re = None, None  # noqa: F841 — 占位保持风格一致
    script = build_output_exec("bg-000000", block_timeout=0)
    proc = subprocess.run(["bash", "-c", script], cwd=tmp_path, capture_output=True, text=True)
    status, _ = parse_output_exec(proc.stdout)
    assert status["status"] == "unknown"


def test_start_exec_inner_script_writes_exit_code(tmp_path):
    """启动脚本尾部注入退出码落盘（finished/exit 的来源）。"""
    import subprocess

    tid = "bg-aabbcc"
    script = build_start_exec(tid, "echo ok")
    subprocess.run(["bash", "-c", script], cwd=tmp_path, capture_output=True, text=True)
    time.sleep(0.3)
    exit_file = tmp_path / ".af_bg" / f"{tid}.exit"
    assert exit_file.read_text().strip() == "0"
    assert "ok" in (tmp_path / ".af_bg" / f"{tid}.log").read_text()
