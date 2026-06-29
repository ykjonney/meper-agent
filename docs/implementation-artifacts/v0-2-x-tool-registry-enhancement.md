# Story v0.2-x: 第一层能力型内建工具 (ask_clarification + tool_search) + ToolRegistry use 增强

**Epic:** v0.2 — 工具接入机制增强
**Status:** done (实施完成 2026-06-25，335 harness 测试全绿)
**Depends on:** v0.1-5 (Middleware), v0.1-7 (ToolRegistry)

> 三层工具模型第一层（能力型内建）+ 第三层接入增强（use 字符串）。
> v0.2-1 delegate_to_subagent、v0.2-2 sandbox 已做。present_file 砍掉（应用层职责）。

---

## Story

As **Agent Flow 架构师**,
I want **harness 内置 ask_clarification（HITL 追问）和 tool_search（工具检索）两个能力型工具，并增强 ToolRegistry 支持 use 字符串动态加载**,
So that **harness 自带"交互/检索"通用能力（任何 agent 都需要），同时让第三层领域工具能按 use 规则声明式注入，接入方式对齐 deer-flow**。

---

## 背景与动机

### 三层工具模型定位

| 层 | 归属 | 工具 | 状态 |
|---|---|---|---|
| 第一层 | harness 自带 | delegate_to_subagent | ✅ done (v0.2-1) |
| 第一层 | harness 自带 | **ask_clarification / tool_search** | **本 Story** |
| ~~第一层~~ | ~~砍掉~~ | ~~present_file~~ | ❌ 应用层职责（文件消费方式由宿主定） |
| 第二层 | harness 抽象 | bash/read/write/glob/grep | ✅ done (v0.2-2) |
| 第三层 | 宿主注入 | 查MES/发邮件/MCP/Skill + **use 增强** | **本 Story use 部分** |

### present_file 为何砍掉

主人决策（2026-06-25）：present_file 的作用是"指示应用层如何展示文件"，但**文件生成后怎么消费是应用层业务决策**（backend 扫 output/记 DB/生成下载链接；别的宿主上传 OSS/发邮件）。harness 提供能力（写文件），不规定应用层怎么消费结果。present_file 是 deer-flow 为其前端架构（artifacts reducer）设计的耦合，不是通用 agent 能力。

### 调研基础（deer-flow）

- `ask_clarification`：deer-flow 用占位工具 + ClarificationMiddleware 拦截 → interrupt。但我们的 middleware 是 fault-isolated（吞异常），interrupt 会被吞。**我们改用工具直调 interrupt**（更直接）。
- `tool_search`：deer-flow `tool_search.py` 编译目录正则，遍历工具 description。
- `use` 字符串：deer-flow `resolve_variable(use, BaseTool)` 动态加载 `"模块:符号"`。

---

## 范围

### Must

**第一层工具：**
- `ask_clarification(question, clarification_type, context?, options?)` — 工具直调 `langgraph.interrupt()`，挂起 graph 等用户回答，resume 后返回答案给 LLM
- `tool_search(query)` — 读 TOOL_REGISTRY，模糊匹配工具 name/description，返回匹配列表

**react.py 必要修正（HITL 前提）：**
- react_node 工具执行的 `except Exception` 加 `except GraphInterrupt: raise` 放行（否则 interrupt 被吞）。这是让 langgraph 原生 HITL 工作的通用前提。

**use 字符串增强：**
- `resolve_variable(use, expected_type)` — `"模块:符号"` → 动态 import + 类型检查
- `ToolRegistry.resolve()` 增强 — 有 use 走动态加载，无 use 走原实例查找（向后兼容）

### Should

- group 分组 — `resolve(agent_doc, groups=[...])` 按组筛选
- BUILTIN_TOOLS 常量 — 第一层 + 第二层工具合集

### Won't

- ~~present_file~~（砍掉，应用层职责）
- ask_clarification 的复杂 UI 类型（先做基础 question/type/options）
- tool_search 的延迟加载（先做检索，加载留后续）
- MCP 工具适配（v0.2-3）

---

## 关键设计决策（已与主人确认）

| # | 决策 | 说明 |
|---|---|---|
| 1 | present_file 砍掉 | 应用层职责，不是通用能力 |
| 2 | ask_clarification 工具直调 interrupt | 不用 middleware 拦截（fault-isolated 会吞 interrupt）；工具 await 时 interrupt 直接挂起 graph |
| 3 | react.py 放行 GraphInterrupt | interrupt 是 Exception 子类，被 `except Exception` 吞；加 `except GraphInterrupt: raise` |
| 4 | tool_search 读 TOOL_REGISTRY 单例 | 零注入，纯内存查询 |
| 5 | use 增强向后兼容 | 无 use 走 v0.1-7 原路径，有 use 走 resolve_variable |
| 6 | 三工具分别用最适机制 | interrupt / ToolRegistry / use 字符串，不强行统一 |

---

## 组件设计

### 1. ask_clarification 工具（直调 interrupt）

```python
async def _ask_clarification(question: str, *, clarification_type: str = "missing_info",
                              context: str | None = None, options: list[str] | None = None) -> str:
    """追问用户，挂起执行等待回答。"""
    from langgraph.types import interrupt
    payload = {"question": question, "type": clarification_type, "context": context, "options": options}
    # interrupt 挂起 graph；resume 时用户答案作为返回值
    return interrupt(payload)

ask_clarification = StructuredTool.from_function(
    _ask_clarification, name="ask_clarification",
    description="向用户提问以获取澄清信息。执行会中断，等待用户回答后继续。",
    args_schema=_ClarificationArgs, coroutine=_ask_clarification,
)
```

### 2. tool_search 工具（读 ToolRegistry）

```python
async def _tool_search(query: str) -> str:
    """按关键词检索可用工具。"""
    from agent_flow_harness.tools import TOOL_REGISTRY
    tools = TOOL_REGISTRY.list_community_tools()  # 已有方法
    # 模糊匹配 query 与 tool.name / tool.description
    matches = [t for t in tools if _matches(query, t)]
    if not matches:
        return "(no matching tools)"
    return "\n".join(f"- {t.name}: {t.description}" for t in matches)
```

### 3. react.py 放行 GraphInterrupt

```python
# react.py 工具执行处（原 except Exception 之前加）
try:
    result_content = await _execute_tool(tool_fn, tool_args)
except GraphInterrupt:
    raise  # 放行 HITL interrupt，不被当工具错误吞
except Exception as exc:
    ...  # 原错误处理
```

### 4. resolve_variable（use 字符串）

```python
def resolve_variable(use: str, expected_type: type) -> Any:
    """'模块路径:符号名' → 动态 import + 类型检查。"""
    module_path, _, symbol = use.partition(":")
    mod = importlib.import_module(module_path)
    obj = getattr(mod, symbol)
    if not isinstance(obj, expected_type):
        raise TypeError(f"{use} is {type(obj)}, expected {expected_type}")
    return obj
```

---

## Acceptance Criteria

- **AC1:** `ask_clarification` 工具实现，直调 `interrupt()`，挂起 graph
- **AC2:** react_node 放行 `GraphInterrupt`（不吞 interrupt）
- **AC3:** ask_clarification 在 react_node 内被调用 → graph 正确挂起 → resume 后返回用户答案给 LLM
- **AC4:** `tool_search(query)` 读 TOOL_REGISTRY，模糊匹配 name/description，返回工具列表
- **AC5:** `resolve_variable("模块:符号", BaseTool)` 正确动态加载 + 类型校验
- **AC6:** `ToolRegistry.resolve()` 支持 use 字段（有 use 走 resolve_variable，无 use 走原路径，向后兼容）
- **AC7:** 包导出 ask_clarification / tool_search / resolve_variable
- **AC8:** react_node 放行修正不破坏现有工具错误处理（普通异常仍转 ToolMessage）
- **AC9:** 20+ 测试通过（含 HITL interrupt 端到端 + use 动态加载 + tool_search）

---

## Tasks / Subtasks

1. **react.py 放行 GraphInterrupt**（前提，1 行 + 测试）
2. **ask_clarification 工具**（直调 interrupt + 端到端 HITL 测试）
3. **tool_search 工具**（读 TOOL_REGISTRY 模糊匹配）
4. **resolve_variable**（use 字符串动态加载 + 类型校验）
5. **ToolRegistry.resolve use 增强**（向后兼容分支）
6. **包导出** + BUILTIN_TOOLS 合集
7. **测试** + 全量回归

---

## References

- [SPEC.md §Always 三层工具模型](../../SPEC.md)
- [deer-flow clarification_tool.py](https://github.com/bytedance/deer-flow) — 占位 + middleware（我们改直调）
- [deer-flow tool_search.py](https://github.com/bytedance/deer-flow) — 目录检索
- [deer-flow tools/tools.py](https://github.com/bytedance/deer-flow) — resolve_variable
- [v0.2-1 subagents](v0-2-1-subagents.md) — delegate_to_subagent（第一层先例）
- [v0.2-2 sandbox](v0-2-2-sandbox.md) — 第二层文件/shell 工具
- [v0.1-5 middleware](v0-1-5-middleware-chain.md) — fault-isolated（为何不用 middleware 拦截）
- [v0.1-7 ToolRegistry](v0-1-7-tool-registry-and-builtin-tools.md) — use 增强基础
