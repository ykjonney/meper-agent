"""AC2/AC3 cover: SandboxResult + GrepMatch 数据类。"""
from __future__ import annotations

from agent_flow_harness.sandbox.base import GrepMatch, SandboxResult


def test_sandbox_result_defaults():
    r = SandboxResult(stdout="ok", stderr="", exit_code=0)
    assert r.stdout == "ok"
    assert r.stderr == ""
    assert r.exit_code == 0
    assert r.duration == 0.0
    assert r.timed_out is False


def test_sandbox_result_with_all_fields():
    r = SandboxResult(stdout="", stderr="timeout", exit_code=-1, duration=1.5, timed_out=True)
    assert r.timed_out is True
    assert r.duration == 1.5
    assert r.exit_code == -1


def test_grep_match_fields():
    m = GrepMatch(path="src/app.py", line_number=42, line="print('hi')")
    assert m.path == "src/app.py"
    assert m.line_number == 42
    assert m.line == "print('hi')"
