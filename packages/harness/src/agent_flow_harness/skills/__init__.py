"""Skills 模块 — Skill 加载与执行（v0.2 增强）。

harness 提供 SkillManager 从文件目录加载 Skill（SKILL.md 格式），
生成 load_skill 工具供 LLM 按需加载。应用层只传 skills_dir 配置。

Skill 是 Claude-Code 风格的指令文档：LLM 调 load_skill(name) 拿到指令文本，
然后用 bash/read 工具执行。
"""
from agent_flow_harness.skills.manager import SkillManager, SkillSpec

__all__ = ["SkillManager", "SkillSpec"]
