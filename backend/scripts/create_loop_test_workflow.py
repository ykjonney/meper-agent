"""一键创建「写作-评审循环」测试工作流（验证本轮循环重构的全部新语义）。

用法：
    cd backend
    # token 获取：登录 studio → F12 → Network 任意请求 → 复制 Authorization
    # 头的值（不含 "Bearer " 前缀），设为环境变量后运行：
    AF_TOKEN=eyJ... uv run python scripts/create_loop_test_workflow.py

创建后的工作流出现在「工作流」列表，打开后只需做一件事：
    给「写手」「评审」两个节点各绑定一个 Agent（可以绑同一个，
    角色差异由任务文案承担）。

验证点（跑一次任务，观察任务详情）：
    1. 跨轮引用：写手第 2 轮任务里出现评审第 1 轮的意见（前引后=上轮值）
    2. 首轮冷启动：写手第 1 轮的「上轮评审意见」为空且不报错
    3. 收敛：评审输出 verdict=approve 时循环提前结束（converge 表达式
       消费用户自定义 schema 字段，无引擎约定）
    4. 空转保护：若写手连续 2 轮输出一字不改 → 第 3 轮 stalled 提前结束

运行任务时输入参数（start.input）示例：
    秋天的码头，80字文案，画面感强、不用夸张词
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

BASE = os.environ.get("AF_BASE", "http://localhost:8000/api/v1")
TOKEN = os.environ.get("AF_TOKEN", "")
if not TOKEN:
    print("缺少 AF_TOKEN 环境变量（见脚本头部说明）")
    sys.exit(1)


def _req(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode() if body else None,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {TOKEN}",
        },
        method=method,
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


WRITER_QUERY = (
    "首轮：围绕以下要求创作初稿，只输出稿件全文。"
    "之后各轮：按上轮评审意见修改，只输出修改后的全文（不要解释）。"
    "要求：{{start.input}}。"
    "上轮评审意见：{{critic.comment}}（首轮为空属正常，忽略即可）"
)
CRITIC_QUERY = (
    "只做评审，不要重写稿件。判断稿件是否满足要求（紧扣主题、表达达标）。"
    "稿件：{{writer.response}}。"
    "要求回顾：{{start.input}}"
)

NODES = [
    {
        "node_id": "start", "type": "start", "label": "开始",
        "config": {"next_nodes": [{"target": "loop1", "label": ""}]},
        "position": {"x": 80, "y": 200},
    },
    {
        "node_id": "writer", "type": "agent", "label": "写手",
        "config": {
            "agent_id": "",  # ← 界面里绑定（可与评审用同一个 Agent）
            "input_query": WRITER_QUERY,
            "next_nodes": [{"target": "critic", "label": ""}],
            "loop_thread_policy": "continue",  # 写手跨轮记忆（记得改过什么）
        },
        "position": {"x": 380, "y": 120},
    },
    {
        "node_id": "critic", "type": "agent", "label": "评审",
        "config": {
            "agent_id": "",  # ← 界面里绑定
            "input_query": CRITIC_QUERY,
            # 输出契约：字段名完全由用户自定义（引擎零约定），收敛表达式
            # 引用同一字段名即可
            "response_schema": {
                "type": "object",
                "fields": [
                    {"name": "verdict", "type": "enum", "required": True,
                     "enum_values": ["approve", "revise"], "description": "approve=达标 revise=需修改"},
                    {"name": "comment", "type": "string", "required": True, "description": "修改意见，具体到位置"},
                ],
            },
            "loop_thread_policy": "fresh",  # 评审每轮独立（不被上轮发言锚定）
        },
        "position": {"x": 640, "y": 320},
    },
    {
        "node_id": "loop1", "type": "loop", "label": "写作评审",
        "config": {
            "body": ["writer", "critic"],
            "body_entry": "writer",
            "max_iterations": 3,
            "converge_expr": "{{critic.verdict == 'approve'}}",
            "next_nodes": [{"target": "end", "label": ""}],
        },
        "position": {"x": 400, "y": 200},
    },
    {
        "node_id": "end", "type": "end", "label": "结束",
        "config": {},
        "position": {"x": 720, "y": 200},
    },
]


def main() -> None:
    wf = _req("POST", "/workflows", {
        "name": "循环测试·写作评审",
        "description": "验证跨轮引用/首轮冷启动/自定义字段收敛/空转检测的最小实例",
        "tags": ["测试", "循环"],
    })
    wf_id = wf.get("id") or wf.get("_id")
    print(f"已创建工作流：{wf_id}")
    _req("PUT", f"/workflows/{wf_id}", {"nodes": NODES})
    print("节点已写入。下一步：打开工作流编辑器 → 给「写手」「评审」绑定 Agent → 保存 → 创建任务运行。")
    print("任务输入示例：秋天的码头，80字文案，画面感强、不用夸张词")


if __name__ == "__main__":
    main()
