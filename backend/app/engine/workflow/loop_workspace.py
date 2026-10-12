"""LoopWorkspace — 循环工作台（refine 模板 MVP）。

状态中心架构（docs/multi-agent-collaboration.md §六 / loop ADR 续篇）：
事实源仍是变量池 rounds 快照与任务 workspace 文件，本模块是它们的
「投影 + 注入」层——轮首渲染视图注入体成员上下文、轮末按约定吸收
输出契约字段。不构成第二事实源（可从 rounds 快照重建）。

约定式字段映射（零配置，absorb 按体成员顺序调用）：
- response / draft（str）→ artifacts 槽（key=节点 label；机械 digest：
  版本/sha/字数/首行——引擎算，不信 LLM 自述）
- verdict（str）          → verdicts 轨迹 append；approve 隐式关闭全部 issue
- issues（list）          → 打开新 issue（自增 id）
- resolved（list[id]）    → 评审确认关闭
- fixes（list[id]）       → 声明已修（待评审确认；approve 兜底）
- notes（str）            → notes 槽（贵重调研沉淀，覆盖式）

视图纪律（分区，不做整视图字数截断）：
- 状态区（goal / open issues / 当前产物行）永不截断——语义本体
- 日志区（verdicts 轨迹）压缩呈现（最近 3 条 + 计数）——历史可损
- 产物全文不进视图（引用+digest），需要全文 agent 自己 read 拉取

注入协议（AgentNodeExecutor 消费系统变量）：
- workspace_view  全量视图；workspace_delta  上一吸收周期的变化量
- fresh 策略或第 1 轮 → view；continue 后续轮 → delta（任务说明只此一份）
"""
from __future__ import annotations

import hashlib
from typing import Any


def _as_str_list(v: Any) -> list[str]:
    """issues 字段宽容解析：["文本"] / [{text}] / 单条 str。"""
    if isinstance(v, str) and v.strip():
        return [v.strip()]
    if not isinstance(v, list):
        return []
    out: list[str] = []
    for item in v:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, dict):
            t = str(item.get("text") or "").strip()
            if t:
                out.append(t)
    return out


def _as_int_list(v: Any) -> list[int]:
    """resolved/fixes 字段解析：[1,2] / ["1"] / 单值。"""
    if isinstance(v, (int, str)) and str(v).strip().isdigit():
        return [int(v)]
    if not isinstance(v, list):
        return []
    out = []
    for item in v:
        s = str(item).strip()
        if s.isdigit():
            out.append(int(s))
    return out


class LoopWorkspace:
    """单个 loop 执行期的工作台实例（dict 序列化友好，随 checkpoint 持久化）。"""

    def __init__(self, goal: str) -> None:
        self.goal = goal
        self.artifacts: dict[str, dict[str, Any]] = {}
        self.issues: list[dict[str, Any]] = []
        self.verdicts: list[dict[str, Any]] = []
        self.notes: str = ""
        self.round: int = 0
        # 吸收周期产生的变化量（下一轮 continue 注入用）
        self.last_delta: str = ""
        # open issue 数量轨迹（通胀检测：连续 3 轮严格递增）
        self._open_history: list[int] = []

    # ── 吸收（轮末，引擎按体链序对每个成员调用一次） ──

    def absorb(self, node_label: str, output: dict[str, Any] | None, rnd: int) -> None:
        if not isinstance(output, dict):
            return
        self.round = rnd
        delta: list[str] = [f"【第 {rnd} 轮工作台变化】"]

        # 产物：draft 优先（object 模式契约字段），response 兜底（text 模式）
        content = output.get("draft")
        if not isinstance(content, str) or not content.strip():
            content = output.get("response")
        if isinstance(content, str) and content.strip():
            bumped = self._absorb_artifact(node_label, content, rnd)
            a = self.artifacts[node_label]
            if bumped:
                delta.append(f"当前{node_label}更新为 v{a['version']}（{a['chars']}字）")
            else:
                delta.append(f"当前{node_label}与上轮相同（v{a['version']}）")

        # 评审轨迹 + approve 隐式全关
        verdict = output.get("verdict")
        if isinstance(verdict, str) and verdict.strip():
            self.verdicts.append(
                {"round": rnd, "by": node_label, "verdict": verdict.strip()}
            )
            delta.append(f"{node_label}判定：{verdict.strip()}")
            if verdict.strip() == "approve":
                closed = 0
                for i in self.issues:
                    if i["status"] != "resolved":
                        i["status"] = "resolved"
                        i["resolved_round"] = rnd
                        closed += 1
                if closed:
                    delta.append(f"approve 隐式关闭 {closed} 个待解决项")

        # issues / resolved / fixes（issue 双向流转：fixes 声明，resolved 确认）
        opened = _as_str_list(output.get("issues"))
        for t in opened:
            self.issues.append(
                {
                    "id": len(self.issues) + 1,
                    "text": t,
                    "raised_by": node_label,
                    "raised_round": rnd,
                    "status": "open",
                    "resolved_round": None,
                }
            )
        if opened:
            delta.append(f"新增待解决：{'；'.join(opened)}")
        resolved_ids = [i for i in _as_int_list(output.get("resolved")) if self._set_issue(i, "resolved", rnd)]
        if resolved_ids:
            delta.append(f"已确认解决：{resolved_ids}")
        fixed_ids = [i for i in _as_int_list(output.get("fixes")) if self._set_issue(i, "claimed", rnd)]
        if fixed_ids:
            delta.append(f"声明已修（待评审确认）：{fixed_ids}")

        notes = output.get("notes")
        if isinstance(notes, str) and notes.strip():
            self.notes = notes.strip()
            delta.append(f"要点笔记已更新：{self.notes[:80]}")

        open_now = self._open_count()
        self._open_history.append(open_now)
        self.last_delta = "\n".join(delta) if len(delta) > 1 else f"【第 {rnd} 轮工作台变化】（无）"

    def _absorb_artifact(self, label: str, content: str, rnd: int) -> bool:
        """机械 digest（sha/字数/首行，引擎算不信自述）。返回是否版本前进。"""
        text = content.strip()
        sha8 = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
        prev = self.artifacts.get(label)
        if prev is not None and prev["sha8"] == sha8:
            prev["round"] = rnd
            prev["stall"] = int(prev.get("stall", 0)) + 1
            return False
        self.artifacts[label] = {
            "version": (prev["version"] + 1) if prev else 1,
            "sha8": sha8,
            "chars": len(text),
            "head": (text.splitlines()[0][:60] if text else ""),
            "round": rnd,
            "stall": 0,
        }
        return True

    def _set_issue(self, issue_id: int, status: str, rnd: int) -> bool:
        for i in self.issues:
            if i["id"] == issue_id and i["status"] != "resolved":
                i["status"] = status
                if status == "resolved":
                    i["resolved_round"] = rnd
                return True
        return False

    def _open_count(self) -> int:
        return sum(1 for i in self.issues if i["status"] != "resolved")

    # ── 视图（轮首注入） ──

    def render_view(self, verdict_tail: int = 3) -> str:
        """全量视图：状态区全量（不截断），日志区压缩。"""
        lines = [f"【循环工作台】目标：{self.goal}"]
        for label, a in self.artifacts.items():
            lines.append(f"当前{label}：v{a['version']}（{a['chars']}字）{a['head']}")
        open_issues = [i for i in self.issues if i["status"] != "resolved"]
        if open_issues:
            lines.append("待解决：")
            for i in open_issues:
                mark = "已修复待确认" if i["status"] == "claimed" else "待处理"
                lines.append(
                    f"  #{i['id']} {i['text']}（{i['raised_by']}·第{i['raised_round']}轮·{mark}）"
                )
        elif self.issues:
            lines.append("待解决：（全部已解决）")
        if self.verdicts:
            tail = [v["verdict"] for v in self.verdicts[-verdict_tail:]]
            lines.append(
                f"评审轨迹：{' → '.join(tail)}（共{len(self.verdicts)}次）"
            )
        if self.notes:
            lines.append(f"要点笔记：{self.notes[:200]}")
        return "\n".join(lines)

    # ── 停机检测 ──

    def is_stalled(self, streak: int = 2) -> bool:
        """空转：任一产物连续 streak 轮 sha 不变（改无可改/敷衍重交）。"""
        return any(int(a.get("stall", 0)) >= streak for a in self.artifacts.values())

    def is_diverging(self) -> bool:
        """通胀：open issues 连续 3 轮严格递增（吹毛求疵永不收敛）。"""
        h = self._open_history
        return len(h) >= 3 and h[-1] > h[-2] > h[-3]

    # ── 序列化（随 progress checkpoint 折叠持久化） ──

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "artifacts": self.artifacts,
            "issues": self.issues,
            "verdicts": self.verdicts,
            "notes": self.notes,
            "round": self.round,
            "last_delta": self.last_delta,
            "open_history": self._open_history,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> LoopWorkspace | None:
        if not isinstance(d, dict) or not d.get("goal"):
            return None
        ws = cls(str(d["goal"]))
        ws.artifacts = dict(d.get("artifacts") or {})
        ws.issues = list(d.get("issues") or [])
        ws.verdicts = list(d.get("verdicts") or [])
        ws.notes = str(d.get("notes") or "")
        ws.round = int(d.get("round") or 0)
        ws.last_delta = str(d.get("last_delta") or "")
        ws._open_history = list(d.get("open_history") or [])
        return ws


def compose_workspace_message(sys_vars: dict[str, Any], node_config: dict[str, Any]) -> str:
    """体成员 user message 的工作台注入段（AgentNodeExecutor 调用）。

    规则：fresh 策略或第 1 轮 → 全量视图（goal/产物/待解决——任务说明
    只此一份）；continue 后续轮 → 增量（上一吸收周期的变化量，消除每轮
    重述）。gate 于 loop_round：仅体成员注入，循环外节点不受残留影响。
    返回空串 = 不注入（未启用工作台 / 非体成员）。
    """
    loop_round = int(sys_vars.get("loop_round") or 0)
    view = str(sys_vars.get("workspace_view") or "")
    if not loop_round or not view:
        return ""
    is_fresh = node_config.get("loop_thread_policy") == "fresh"
    if is_fresh or loop_round <= 1:
        return view
    return str(sys_vars.get("workspace_delta") or "") or view


__all__ = ["LoopWorkspace"]
