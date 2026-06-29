"""SubAgentSpec — 子 Agent 的声明性配置（纯数据）。

每个 SubAgentSpec 描述一个可被主 Agent 委派的子 Agent：它的 system_prompt、
可用工具名称、LLM 配置和最大轮数。运行时由 SubAgentRegistry 存储；
delegate_to_subagent 工具被调用时才据此延迟构建子 agent graph。

system_prompt 是完整文本（不走 6 段式 Slot 渲染）——子 Agent 通常只需
简单 prompt。tools 是名称列表，运行时经 TOOL_REGISTRY.resolve() 解析。
llm_config={"model": "inherit"} 表示复用主 Agent 的 LLM。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class SubAgentSpec(BaseModel):
    """声明一个可委派的子 Agent。"""

    name: str = Field(..., min_length=1, description="唯一标识")
    description: str = Field(..., description="给主 Agent 看的委派时机说明")
    system_prompt: str = Field(..., description="子 Agent 完整 system prompt")
    tools: list[str] = Field(default_factory=list, description="允许的工具名称列表")
    llm_config: dict[str, Any] = Field(default_factory=dict, description="LLM 配置; {'model':'inherit'} 复用主 LLM")
    max_turns: int = Field(default=25, ge=1, description="REACT 最大迭代数")

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        """name 去空白后不能为空（拦截纯空格串）。"""
        if not v.strip():
            msg = "name must not be blank"
            raise ValueError(msg)
        return v


__all__ = ["SubAgentSpec"]
