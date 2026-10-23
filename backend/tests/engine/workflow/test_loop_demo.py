"""循环实例测试 —— 「写作-评审」双 agent 循环的端到端演示。

与 test_loop_node.py 的引擎级测试不同：本用例走**真实渲染链路**
（ExpressionEngine 解析 input_query 模板 → 实际 user message），模拟
最典型的 refine 场景，运行后打印每轮的实际过程供人工核对：

    writer 任务模板（含前引后引用 + 首轮冷启动写法）：
      "首轮：围绕主题写80字文案；之后：按评审意见修改。
       上轮评审意见：{{critic.comment}}"
    critic 任务模板（先引前引用）：
      "评审这版稿，结论与意见：{{writer.response}}"

运行（-s 看过程打印）：
    cd backend && uv run pytest tests/engine/workflow/test_loop_demo.py -s -p no:warnings
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.engine.workflow.engine import WorkflowEngine
from app.engine.workflow.expression import ExpressionEngine
from app.engine.workflow.node_executor import NodeResult
from app.engine.workflow.variable_pool import VariablePool

# ── 实例定义：写作-评审循环（refine 最小形态）─────────────────────────

WRITER_QUERY = (
    "首轮：围绕「秋天的码头」写一段80字文案，要求画面感强、不用夸张词；"
    "之后：按评审意见修改稿件。上轮评审意见：{{critic.comment}}"
)
CRITIC_QUERY = "评审这版稿件是否达标（画面感、无夸张词），给出结论与修改意见。稿件：{{writer.response}}"

# critic 的脚本化输出（模拟 response_schema object 模式解析后的产物）：
# 轮1 挑两处毛病；轮2 认可一处；轮3 通过。
CRITIC_SCRIPT = [
    {"verdict": "revise", "comment": "开头太长；结尾的'宛如仙境'是夸张词，删掉"},
    {"verdict": "revise", "comment": "开头已紧凑；'宛如仙境'仍在，仅此一处"},
    {"verdict": "approve", "comment": "画面感达标，无夸张词，通过"},
]
WRITER_SCRIPT = [
    "暮色漫过码头，缆绳在风里轻轻晃着。（首版 80 字……）",
    "暮色漫过码头，缆绳轻晃。（次版：开头收紧……）",
    "暮色漫过码头，缆绳轻晃，潮声渐起。（三版：删去夸张词……）",
]

NODES = [
    {
        "node_id": "writer", "type": "agent", "label": "写手",
        "config": {
            "input_query": WRITER_QUERY,
            "next_nodes": [{"target": "critic", "label": ""}],
            "loop_thread_policy": "continue",
        },
    },
    {
        "node_id": "critic", "type": "agent", "label": "评审",
        "config": {
            "input_query": CRITIC_QUERY,
            # 真实场景由 response_schema 约束；此处直接给脚本化 dict 输出
            "loop_thread_policy": "fresh",
        },
    },
]


def _wf() -> list[dict]:
    loop = {
        "node_id": "loop1", "type": "loop", "label": "写作评审",
        "config": {
            "body": ["writer", "critic"], "body_entry": "writer",
            "max_iterations": 5,
            "converge_expr": "{{ critic.verdict == 'approve' }}",
        },
    }
    return [loop, *NODES]


def _db_mock() -> MagicMock:
    mock_db = MagicMock()
    mock_col = MagicMock()
    mock_col.find_one = AsyncMock(return_value={"status": "running"})
    mock_col.update_one = AsyncMock()
    mock_db.return_value.__getitem__.return_value = mock_col
    return mock_db


def _ts_mock() -> MagicMock:
    ts = MagicMock()
    ts.append_timeline_event = AsyncMock()
    ts.add_total_tokens = AsyncMock()
    ts.transition_task = AsyncMock()
    return ts


def _demo_executors(calls: list[dict]):
    """真实渲染 input_query（ExpressionEngine）→ 记录每轮实际 user message；
    输出按脚本返回。calls 是共享记录（round/node/query/output）。
    idx 放在 factory 外层：get_node_executor 每轮每节点都会调用，计数器
    必须跨轮共享（放 _get 内会每轮重置、脚本永远停在第一段）。"""
    idx = {"writer": 0, "critic": 0}

    def _get(node_type: str, node_id: str, cfg: dict) -> MagicMock:
        ex = MagicMock()
        if node_id == "loop1":
            ex.execute = AsyncMock(return_value=NodeResult(success=True, output={
                "body": cfg["body"], "body_entry": cfg["body_entry"],
                "max_iterations": cfg["max_iterations"],
                "converge_expr": cfg.get("converge_expr"),
            }))
            return ex

        async def _run(variables):
            rnd = int((variables.get("system") or {}).get("loop_round") or 0)
            # ── 真实渲染链路：模板 → 实际 user message ──
            engine = ExpressionEngine(variables)
            query = engine.resolve_str(cfg.get("input_query", ""))
            if node_id == "writer":
                out = {"response": WRITER_SCRIPT[min(idx["writer"], len(WRITER_SCRIPT) - 1)]}
                idx["writer"] += 1
            else:
                out = dict(CRITIC_SCRIPT[min(idx["critic"], len(CRITIC_SCRIPT) - 1)])
                idx["critic"] += 1
            calls.append({"round": rnd, "node": node_id, "query": query, "output": out})
            return NodeResult(success=True, output=out)

        ex.execute = _run
        return ex

    return _get


class TestWritingReviewLoopDemo:
    @pytest.mark.asyncio
    async def test_demo_run(self, capsys) -> None:
        engine = WorkflowEngine()
        engine._task_id = "task_demo"
        engine._nodes = _wf()
        engine._node_map = {n["node_id"]: n for n in engine._nodes}
        engine._pool = VariablePool()

        calls: list[dict] = []
        with patch("app.engine.workflow.engine.get_node_executor",
                   side_effect=_demo_executors(calls)), \
             patch("app.engine.workflow.engine.TaskService", new=_ts_mock()), \
             patch("app.db.mongodb.get_database", new=_db_mock()):
            await engine._execute_node("loop1")

        loop_out = engine._pool.get("loop1")

        # ── 过程打印（pytest -s 查看）──
        print("\n═══════ 写作-评审循环 · 实际执行过程 ═══════")
        for c in calls:
            print(f"\n── 第 {c['round']} 轮 · {c['node']} ──")
            print(f"[实际 user message]\n{c['query']}")
            print(f"[输出] {c['output']}")
        print("\n═══════ 循环结果 ═══════")
        print(f"iterations={loop_out['iterations']}  converged={loop_out['converged']}")
        print(f"裸键 critic.verdict（最新轮）= {engine._pool.get('critic.verdict')}")
        for r in sorted(loop_out["rounds"].keys(), key=int):
            snap = loop_out["rounds"][r]
            print(f"rounds[{r}]: writer.response={snap['writer']['response'][:18]}… "
                  f"critic.verdict={snap['critic']['verdict']}")

        # ── 核心断言：跨轮引用语义的真实渲染结果 ──
        writer_calls = [c for c in calls if c["node"] == "writer"]
        critic_calls = [c for c in calls if c["node"] == "critic"]

        # 第 3 轮 critic 说 approve → 收敛，iterations=3（未跑满 5）
        assert loop_out["iterations"] == 3
        assert loop_out["converged"] is True

        # writer 轮1：冷启动——前引后变量未定义，渲染为空（不报错、不留花括号）
        assert "{{" not in writer_calls[0]["query"]
        assert "上轮评审意见：\n" in writer_calls[0]["query"] or "上轮评审意见：" in writer_calls[0]["query"]

        # writer 轮2/3：前引后=上轮值（真实渲染进消息）
        assert "开头太长" in writer_calls[1]["query"]
        assert "'宛如仙境'仍在" in writer_calls[2]["query"]

        # critic 每轮：先引前=本轮值（当轮稿件全文渲染进消息）
        for i, c in enumerate(critic_calls):
            assert WRITER_SCRIPT[i] in c["query"]

        # rounds 不可变历史 + 裸键最新值
        assert loop_out["rounds"]["1"]["critic"]["verdict"] == "revise"
        assert engine._pool.get("critic.comment") == "画面感达标，无夸张词，通过"
