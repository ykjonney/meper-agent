"""SkillManager — 从文件目录加载 Skill（SKILL.md 格式）。

Skill 是 Claude-Code 风格的指令文档：每个 skill 是一个目录，含 SKILL.md
（YAML frontmatter + Markdown 指令）+ 辅助文件（脚本/模板等）。

harness 提供 load_skill 工具，LLM 按需加载 skill 指令。应用层只传 skills_dir
路径，harness 负责加载/白名单/路径提示。

用法：
    mgr = SkillManager(skills_dir=Path("/data/skills"))
    mgr.set_allowed({"researcher", "coder"})
    tool = mgr.make_load_tool()
    # tool 加入 agent 的工具列表
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    pass

_MAX_SKILL_CONTENT = 50_000
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass
class SkillSpec:
    """Skill 元数据（从 SKILL.md frontmatter 解析）。"""

    name: str
    description: str
    base_path: Path
    instructions: str  # Markdown 正文（frontmatter 之后的内容）


class _LoadSkillArgs(BaseModel):
    skill_name: str = Field(..., description="要加载的 Skill 名称")


class SkillManager:
    """从文件目录管理 Skill 的加载。

    扫描 skills_dir 下的子目录，每个含 SKILL.md 的目录是一个 skill。
    白名单控制哪些 skill 对 LLM 可用。
    """

    def __init__(
        self,
        skills_dir: Path,
        *,
        base_path_prefix: str | None = None,
    ) -> None:
        """初始化 SkillManager。

        Args:
            skills_dir: Skill 根目录（每个子目录是一个 skill）。
            base_path_prefix: 返回给 LLM 的路径前缀。None 用 skills_dir 绝对路径；
                传容器路径（如 "/skills"）用于 sandbox 场景。
        """
        self._skills_dir = Path(skills_dir)
        self._base_path_prefix = base_path_prefix
        self._allowed: set[str] | None = None  # None = 全部允许

    def set_allowed(self, names: set[str] | None) -> None:
        """设置白名单。None = 全部允许。"""
        self._allowed = names

    def list_skills(self) -> list[SkillSpec]:
        """列出所有可用 skill（白名单内的）。"""
        result: list[SkillSpec] = []
        if not self._skills_dir.exists():
            return result
        for d in sorted(self._skills_dir.iterdir()):
            if d.is_dir():
                skill_file = d / "SKILL.md"
                if skill_file.exists() and self._is_allowed(d.name):
                    spec = self._parse_skill(d.name, skill_file)
                    if spec is not None:
                        result.append(spec)
        return result

    def load_skill(self, name: str) -> str:
        """加载 skill 的 SKILL.md 内容，返回文本 + 路径提示。

        白名单外的 skill 返回错误字符串（不 raise）。
        """
        if not self._is_allowed(name):
            available = ", ".join(s.name for s in self.list_skills()) or "(none)"
            return f"Skill '{name}' is not available. Available: {available}"

        skill_file = self._skills_dir / name / "SKILL.md"
        if not skill_file.exists():
            return f"Error: Skill '{name}' not found (SKILL.md missing)."

        content = skill_file.read_text(encoding="utf-8", errors="replace")
        if len(content) > _MAX_SKILL_CONTENT:
            content = content[:_MAX_SKILL_CONTENT] + "\n... [truncated]"

        base = self._base_path_for(name)
        return f"{content}\n\n[Skill base path: {base}/ — use this path for all file references]"

    def _is_allowed(self, name: str) -> bool:
        if self._allowed is None:
            return True
        return name in self._allowed

    def _base_path_for(self, name: str) -> str:
        if self._base_path_prefix is not None:
            return f"{self._base_path_prefix}/{name}"
        return str(self._skills_dir / name)

    @staticmethod
    def _parse_skill(name: str, skill_file: Path) -> SkillSpec | None:
        """从 SKILL.md 解析元数据（frontmatter name/description + 正文）。"""
        try:
            content = skill_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

        match = _FRONTMATTER_RE.match(content)
        description = ""
        if match:
            front = match.group(1)
            for line in front.splitlines():
                if line.strip().startswith("description:"):
                    description = line.split(":", 1)[1].strip().strip('"\'')
                    break
            instructions = content[match.end():]
        else:
            instructions = content

        return SkillSpec(
            name=name,
            description=description,
            base_path=skill_file.parent,
            instructions=instructions,
        )

    def make_load_tool(self) -> StructuredTool:
        """生成 load_skill LangChain 工具。"""

        async def _load_skill(skill_name: str) -> str:
            """加载指定 Skill 的指令文档。"""
            return self.load_skill(skill_name)

        return StructuredTool.from_function(
            _load_skill,
            name="load_skill",
            description="加载指定 Skill 的指令文档（SKILL.md）。按需加载，不要一次加载多个。",
            args_schema=_LoadSkillArgs,
            coroutine=_load_skill,
        )


__all__ = ["SkillManager", "SkillSpec"]
