"""SkillManager 测试。"""
from __future__ import annotations

import pytest
from pathlib import Path

from agent_flow_harness.skills.manager import SkillManager


def _make_skill(base: Path, name: str, desc: str = "test skill", body: str = "Do the thing."):
    """创建一个测试 skill 目录 + SKILL.md。"""
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {desc}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return d


def test_list_skills(tmp_path):
    _make_skill(tmp_path, "coder", "coding skill")
    _make_skill(tmp_path, "writer", "writing skill")
    mgr = SkillManager(tmp_path)
    skills = mgr.list_skills()
    assert len(skills) == 2
    names = {s.name for s in skills}
    assert names == {"coder", "writer"}


def test_list_skills_empty(tmp_path):
    mgr = SkillManager(tmp_path)
    assert mgr.list_skills() == []


def test_list_skills_nonexistent_dir(tmp_path):
    mgr = SkillManager(tmp_path / "nonexistent")
    assert mgr.list_skills() == []


def test_load_skill_success(tmp_path):
    _make_skill(tmp_path, "coder", "coding skill", "Write clean code.")
    mgr = SkillManager(tmp_path)
    result = mgr.load_skill("coder")
    assert "Write clean code." in result
    assert "Skill base path:" in result


def test_load_skill_whitelist(tmp_path):
    _make_skill(tmp_path, "coder")
    _make_skill(tmp_path, "writer")
    mgr = SkillManager(tmp_path)
    mgr.set_allowed({"coder"})

    # coder 可加载
    assert "Skill base path:" in mgr.load_skill("coder")
    # writer 被白名单挡住
    result = mgr.load_skill("writer")
    assert "not available" in result
    assert "coder" in result  # 提示可用的


def test_load_skill_unknown(tmp_path):
    _make_skill(tmp_path, "coder")
    mgr = SkillManager(tmp_path)
    result = mgr.load_skill("nonexistent")
    assert "not found" in result or "not available" in result


def test_load_skill_truncation(tmp_path):
    _make_skill(tmp_path, "big", body="x" * 60_000)
    mgr = SkillManager(tmp_path)
    result = mgr.load_skill("big")
    assert "[truncated]" in result


def test_base_path_prefix(tmp_path):
    _make_skill(tmp_path, "coder")
    mgr = SkillManager(tmp_path, base_path_prefix="/skills")
    result = mgr.load_skill("coder")
    assert "[Skill base path: /skills/coder/" in result


def test_parse_skill_description(tmp_path):
    _make_skill(tmp_path, "coder", "A great coding assistant")
    mgr = SkillManager(tmp_path)
    skills = mgr.list_skills()
    assert skills[0].description == "A great coding assistant"


def test_make_load_tool(tmp_path):
    _make_skill(tmp_path, "coder", "coding", "Write code.")
    mgr = SkillManager(tmp_path)
    tool = mgr.make_load_tool()
    assert tool.name == "load_skill"


@pytest.mark.asyncio
async def test_load_tool_ainvoke(tmp_path):
    _make_skill(tmp_path, "coder", "coding", "Write clean code.")
    mgr = SkillManager(tmp_path)
    tool = mgr.make_load_tool()
    result = await tool.ainvoke({"skill_name": "coder"})
    assert "Write clean code." in result
