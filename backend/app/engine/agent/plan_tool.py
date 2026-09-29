"""propose_plan 工具 — 计划模式的终结动作：HITL 计划审批。

计划模式（plan_mode）是 chat 上的一种受约束执行：只调研不执行，调研
完备后必须调用本工具提交计划并挂起，等用户在计划卡片上审批。与
ask_clarification 同构：工具内直调 langgraph interrupt() 挂起 graph，
宿主 resume(Command(resume=answer)) 后 answer 作为返回值交给 LLM。

resume 语义（前端按卡片按钮选择）：
- 批准   → answer = PLAN_APPROVED_MARKER（本模块导出的标记），且
           resume 请求不带 plan_mode（恢复全量工具——批准即解除只读）
- 反馈   → answer = 用户文本（修改意见/重新规划要求），resume 保持
           plan_mode=true（继续只读，修订计划后再次提交）
- 放弃   → 走 interrupt/dismiss 端点合成 tool_result，不恢复执行

计划规范（五段式 markdown，工具 description 与 builder 计划纪律段同源）：
# 目标 / # 背景与约束 / # 步骤（checkbox） / # 验收标准 / # 完成时交付
"""

from __future__ import annotations

import re

from langchain_core.tools import BaseTool, StructuredTool

#: 批准标记——前端「批准执行」按钮以此作为 resume answer（与 chat-api 共享字面量）。
PLAN_APPROVED_MARKER = "__plan_approved__"

_PLAN_SPEC = (
    "按以下五段式 markdown 组织（段名固定）：\n"
    "# 目标 —— 一句话，可判断达成与否\n"
    "# 背景与约束 —— 从对话沉淀的关键信息（范围/环境/不能动什么/偏好）\n"
    "# 步骤 —— checkbox 列表（`- [ ]`），粗粒度、可演化\n"
    "# 验收标准 —— 人可审的判据；有可命令化判据时写明命令\n"
    "# 完成时交付 —— 交付物形态（文件/报告/变更摘要）"
)

#: 必需章节——分别承载"可判定的完成定义"与"人可审的判据"，缺任一则
#: 计划书对用户不可审（其余三节推荐但不强制，按任务形态取舍）。
_REQUIRED_PLAN_SECTIONS = ("目标", "验收标准")


def validate_plan_sections(plan: str) -> list[str]:
    """校验五段式计划的必需章节；返回缺失/为空的章节名列表。

    章节标题行形如 ``# 目标`` 或 ``# 目标：修复测试``（冒号后内容不计入
    标题）。必需章节存在且正文非空才算通过——空壳章节视同缺失。
    """
    sections: dict[str, str] = {}
    current = ""
    for line in plan.splitlines():
        m = re.match(r"^#\s+(.*)$", line)
        if m:
            # 标题规范化：冒号后缀既是标题装饰也是内容（"目标：修复测试"
            # 的实质内容在标题行内），计入正文防空壳误判。
            parts = re.split(r"[：:]", m.group(1).strip(), maxsplit=1)
            current = parts[0].strip()
            sections.setdefault(current, "")
            if len(parts) > 1 and parts[1].strip():
                sections[current] += parts[1].strip() + "\n"
        elif current:
            sections[current] += line + "\n"
    return [t for t in _REQUIRED_PLAN_SECTIONS if not sections.get(t, "").strip()]


async def _propose_plan(plan: str) -> str:
    """提交计划供用户审批。计划模式下调研完备后必须调用本工具终结。"""
    from langgraph.types import interrupt

    # 结构闸门（服务端权威，前端静默跳过缺失节）：缺必需章节不挂起，
    # 直接反馈让模型补全重交——用户永远不会看到结构不完整的计划书。
    missing = validate_plan_sections(plan)
    if missing:
        return (
            f"计划缺少必要章节：{'、'.join(missing)}。请按五段式规范补全"
            f"（{_PLAN_SPEC}）后重新提交完整计划，不要提交残缺版本。"
        )

    decision = interrupt({"type": "plan", "plan": plan})
    if isinstance(decision, str) and decision == PLAN_APPROVED_MARKER:
        return (
            "用户已批准该计划。计划全文已在对话中。请简短确认收到，"
            "然后停下来等待用户指示开始执行——不要自行开始执行步骤。"
        )
    # 任意非批准文本 = 用户反馈（修改意见 / 重新规划要求）
    feedback = decision if isinstance(decision, str) else str(decision)
    return (
        f"用户对计划的反馈（请据此修订计划并再次调用 propose_plan 提交，"
        f"或说明为何无法满足）：{feedback}"
    )


propose_plan = StructuredTool.from_function(
    _propose_plan,
    name="propose_plan",
    description=(
        "提交完整计划供用户审批。仅对路径不确定、动作不可逆或方案需用户"
        "确认的任务使用——批量重复、路径明确的任务直接执行,不要造计划;"
        "简单问答直接回答。调研完备后必须调用本工具,不要只在纯文本里描述计划。"
        f"{_PLAN_SPEC}"
    ),
    # 异步函数必须显式挂 coroutine——from_function 不做协程自动识别,
    # 缺省会把 async 函数当同步 func 调用,返回未 await 的协程对象
    # (工具结果变成 "<coroutine object ...>",interrupt 也不会触发)。
    # 与 ask_clarification 的构造方式一致。
    coroutine=_propose_plan,
)

# ---------------------------------------------------------------------------
# Tool list — plan 上下文注入（不进 _INJECTED_BUILTIN_TOOL_NAMES，
# 不出现在工具市场/builtin 端点——计划模式专属能力型工具，同 _TASK_TOOLS 模式）
# ---------------------------------------------------------------------------

_PLAN_TOOLS: list[BaseTool] = [propose_plan]

#: name → tool 实例查找表（context.py plan 分支注入用）。
PLAN_TOOL_BY_NAME: dict[str, BaseTool] = {t.name: t for t in _PLAN_TOOLS}

__all__ = ["PLAN_APPROVED_MARKER", "PLAN_TOOL_BY_NAME", "propose_plan"]
