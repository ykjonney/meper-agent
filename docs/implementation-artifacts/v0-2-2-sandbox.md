# Story v0.2-2: Sandbox 抽象 + 文件/shell 工具上提

**Epic:** v0.2 — P0 增强模块
**Status:** done (实施完成 2026-06-25，316 harness 测试 + 814 backend 测试全绿)
**Depends on:** v0.1-7 (ToolRegistry + CommunityTool 协议)

> ⚠️ 本 Story 是 v0.2-2 的重写版。原版假设"harness 有 builtin 工具要加沙箱"，
> 但调研 deer-flow + 确认现状后发现：bash/read/write 在 backend 且已有 Docker sandbox。
> 经主人确认，采纳**三层工具模型**，Sandbox 抽象 + 文件/shell 工具上提到 harness。

---

## Story

As **Agent Flow 架构师**,
I want **harness 提供 Sandbox 环境抽象（ABC + Provider）+ bash/read/write/glob/grep 工具，工具代码零 I/O 全部委托 Sandbox 方法，实现通过 config.use 注入**,
So that **harness 作为独立 PyPI 包自带文件/shell 能力（不绑定具体实现），backend 现有 SandboxExecutor 改造为 LocalSandbox 实现，换 sandbox 后端（Local/Docker/E2B）工具代码零改动**。

---

## 背景与动机

### 现状问题

1. **bash/read/write 在 backend，harness 的 builtin.py 是空文件** — harness 作为 PyPI 包没有任何文件/shell 工具，独立使用时无法跑代码
2. **工具与 backend 实现耦合** — bash 直接调 `SandboxExecutor.execute()`，read/write 直接 `open()`，换实现要改工具
3. **内建工具太少** — deer-flow 有 7 个文件/shell 工具 + 8 个能力型工具，我们 harness 一个都没有

### 调研基础（deer-flow）

deer-flow 把 Sandbox 作为 harness 一等公民：

| deer-flow 组件 | 位置 | 作用 |
|---|---|---|
| `Sandbox` (ABC) | `sandbox/sandbox.py` | 8 方法：execute_command/read_file/write_file/glob/grep/list_dir/download_file/update_file |
| `SandboxProvider` (ABC) | `sandbox/sandbox_provider.py` | 生命周期：acquire/get/release，config.use 动态加载 |
| `LocalSandbox` | `sandbox/local/` | 默认本地实现（subprocess + 文件系统） |
| 文件/shell 工具 | `sandbox/tools.py` | bash/ls/glob/grep/read_file/write_file/str_replace，全部委托 Sandbox |
| 注入机制 | `Runtime` (langchain) | 工具签名 `runtime: Runtime`，框架自动注入 |

**核心洞察**：工具代码零 I/O，全部委托 Sandbox 方法。换 Local/Remote/Docker 实现，工具代码一行不改。

### 三层工具模型（已固化到 SPEC）

本 Story 实现**第二层**（文件/shell 能力 + 环境抽象）：
- **第一层**（能力型内建）：delegate_to_subagent（已做）/ present_file / ask_clarification / tool_search — 归 v0.2-x
- **第二层**（本 Story）：Sandbox 抽象 + bash/read/write/glob/grep 工具
- **第三层**（领域工具）：宿主注入，harness 不持有

---

## 范围

### Must（必须做）

- `Sandbox` Protocol/ABC：execute_command / read_file / write_file / glob / grep 五个核心方法
- `SandboxProvider` Protocol/ABC + 进程级单例（acquire/get/release）
- `SandboxResult` 数据类（stdout/stderr/exit_code/duration/timed_out）
- `LocalSandbox` 默认实现（subprocess + 本地文件系统）
- **Sandbox 注入走 ContextVar**（`sandbox_context`，与 workspace_context/subagent_context 同模式）
- `bash` / `read` / `write` / `glob` / `grep` 五个工具，全部委托 Sandbox 方法，工具代码零 I/O
- 工具调用失败返回结构化错误字符串（不抛异常给 LLM）

### Should（应该做）

- `list_dir` 工具 + Sandbox 方法
- 资源度量（cpu_time / mem_peak）写入 SandboxResult

### Won't（不在本 Story 做）

- DockerSandbox / E2BSandbox 实现（主人按需扩展，本 Story 只做 LocalSandbox）
- 网络 egress 白名单、seccomp（属于具体实现的细节，LocalSandbox 用 cwd 限制 + 超时）
- 网络拦截、资源 rlimit（LocalSandbox 基础版先不做，留 TODO）
- backend 现有 SandboxExecutor 的迁移改造（另开 Story，本 Story 只做 harness 侧）

---

## 关键设计决策（已与主人确认）

| # | 决策点 | 选择 | 理由 |
|---|---|---|---|
| 1 | 工具分层 | 三层模型（本 Story 做第二层） | 能力型/环境/领域分离，对齐 deer-flow |
| 2 | bash/read/write 归属 | 上提到 harness | 文件/shell 是通用能力，不是领域工具 |
| 3 | Sandbox 抽象 | ABC + 5 核心方法（execute/read/write/glob/grep） | 对齐 deer-flow，足够覆盖核心场景 |
| 4 | 注入机制 | ContextVar（sandbox_context） | 与 workspace_context/subagent_context 同模式，非 deer-flow 的 Runtime |
| 5 | Provider | ABC + 进程级单例 + config.use 动态加载 | 与 ToolRegistry 同哲学，harness 不绑定实现 |
| 6 | 默认实现 | LocalSandbox（subprocess + 本地 FS） | 零依赖，开发环境够用 |
| 7 | 工具 I/O | 零 I/O，全部委托 Sandbox 方法 | 换实现不改工具 |
| 8 | backend 迁移 | 另开 Story（本 Story 只做 harness 侧） | 控制 blast radius |

---

## 架构

### 数据流（工具 → Sandbox → 实现）

```
LLM 决定调用 bash(command="ls -la")
    │
    ▼
bash 工具 (sandbox/tools.py, 零 I/O)
    │  1. 从 ContextVar 读 SandboxContext(sandbox)
    │  2. result = sandbox.execute_command(command, timeout=...)
    │  3. 返回 result.stdout / 错误字符串
    │
    ▼
Sandbox (ABC, sandbox/base.py)
    │  execute_command() 是抽象方法
    │
    ▼
具体实现 (通过 config.use 注入)
    ├─ LocalSandbox (sandbox/local.py) — subprocess.run, 本地 FS
    ├─ DockerSandbox (主人扩展) — 容器隔离
    └─ E2BSandbox (主人扩展) — 云沙箱
```

### SandboxProvider 注入时序

```
启动时: set_sandbox_provider(LocalSandboxProvider())  ← 或 config.use 动态加载
    ↓
主 Agent 执行前: sandbox = acquire_sandbox(thread_id)
                 token = set_sandbox_context(SandboxContext(sandbox))
    ↓
工具执行: sandbox = get_sandbox_context().sandbox
          result = sandbox.execute_command(...)
    ↓
主 Agent 结束: release_sandbox(sandbox_id); reset_sandbox_context(token)
```

### ContextVar 注入（与现有模式一致）

```python
# sandbox/context.py
@dataclass
class SandboxContext:
    sandbox: Sandbox

_sandbox_ctx: ContextVar[SandboxContext | None] = ContextVar("sandbox_ctx", default=None)

def set_sandbox_context(ctx) -> Token
def get_sandbox_context() -> SandboxContext    # 未设置 raise RuntimeError
def reset_sandbox_context(token) -> None
```

---

## 组件设计

### 1. Sandbox (ABC) — `sandbox/base.py`

```python
class Sandbox(ABC):
    """执行环境抽象。工具代码只调这些方法，从不直接做 I/O。"""

    @property
    @abstractmethod
    def id(self) -> str: ...

    @abstractmethod
    def execute_command(self, command: str, *, timeout: int = 120) -> SandboxResult: ...

    @abstractmethod
    def read_file(self, path: str) -> str: ...

    @abstractmethod
    def write_file(self, path: str, content: str) -> None: ...

    @abstractmethod
    def glob(self, path: str, pattern: str) -> list[str]: ...

    @abstractmethod
    def grep(self, path: str, pattern: str) -> list[GrepMatch]: ...
```

### 2. SandboxResult — `sandbox/base.py`

```python
@dataclass
class SandboxResult:
    stdout: str
    stderr: str
    exit_code: int
    duration: float = 0.0
    timed_out: bool = False

@dataclass
class GrepMatch:
    path: str
    line_number: int
    line: str
```

### 3. SandboxProvider (ABC) — `sandbox/provider.py`

```python
class SandboxProvider(ABC):
    @abstractmethod
    def acquire(self, thread_id: str | None = None) -> Sandbox: ...

    @abstractmethod
    def get(self, sandbox_id: str) -> Sandbox | None: ...

    @abstractmethod
    def release(self, sandbox_id: str) -> None: ...

# 进程级单例（与 TOOL_REGISTRY / checkpointer 同模式）
def set_sandbox_provider(provider: SandboxProvider) -> None
def get_sandbox_provider() -> SandboxProvider
def reset_sandbox_provider() -> None
```

### 4. LocalSandbox — `sandbox/local.py`

```python
class LocalSandbox(Sandbox):
    """默认实现：subprocess + 本地文件系统。

    cwd 限制为 work_dir，timeout 强制 kill。
    生产环境多租户隔离应使用 DockerSandbox/E2BSandbox。
    """

    def __init__(self, sandbox_id: str, work_dir: Path, timeout: int = 120) -> None: ...

    def execute_command(self, command, *, timeout=120) -> SandboxResult:
        # subprocess.run(["bash","-c",command], cwd=work_dir, timeout=...)
        # timeout → TimeoutExpired → 强制返回 timed_out=True

    def read_file(self, path) -> str:
        # 路径校验（必须在 work_dir 内）→ open + read + 截断

    def write_file(self, path, content) -> None:
        # 路径校验 → mkdir parents + write

    def glob(self, path, pattern) -> list[str]: ...
    def grep(self, path, pattern) -> list[GrepMatch]: ...
```

### 5. 文件/shell 工具 — `sandbox/tools.py`（零 I/O）

```python
async def bash(command: str) -> str:
    """执行 shell 命令。委托 sandbox.execute_command。"""
    sandbox = get_sandbox_context().sandbox
    result = sandbox.execute_command(command)
    return _format_result(result)   # stdout + stderr + exit_code，失败转错误字符串

async def read(path: str) -> str:
    """读文件。委托 sandbox.read_file。"""

async def write(path: str, content: str) -> str:
    """写文件。委托 sandbox.write_file。"""

async def glob(path: str, pattern: str) -> str:
    """文件匹配。委托 sandbox.glob。"""

async def grep(path: str, pattern: str) -> str:
    """内容搜索。委托 sandbox.grep。"""
```

所有工具：异常 catch 转错误字符串，不抛给 LLM。

---

## Acceptance Criteria

- **AC1:** `sandbox/__init__.py` 导出 `Sandbox`、`SandboxProvider`、`SandboxResult`、`GrepMatch`、`LocalSandbox`、`set/get_sandbox_provider`、`SandboxContext`、`set/get/reset_sandbox_context`、5 个工具
- **AC2:** `Sandbox` ABC 定义 5 抽象方法（execute_command/read_file/write_file/glob/grep）+ id 属性
- **AC3:** `SandboxResult` 字段：stdout/stderr/exit_code/duration/timed_out
- **AC4:** `SandboxProvider` ABC 3 方法（acquire/get/release）+ 进程级单例 set/get/reset
- **AC5:** `LocalSandbox` 实现 Sandbox 全部方法（subprocess + 本地 FS + cwd 限制 + timeout 强制 kill）
- **AC6:** `SandboxContext` + ContextVar 注入（set/get/reset，未设置 raise RuntimeError）
- **AC7:** `bash`/`read`/`write`/`glob`/`grep` 五工具实现，**全部委托 Sandbox 方法，工具代码无 subprocess/open**
- **AC8:** 工具异常隔离 — 任何 I/O 失败返回错误字符串，不抛给 LLM
- **AC9:** 30+ 单元测试通过（含 LocalSandbox 各方法 + 5 工具委托验证 + 异常隔离 + 路径越权拦截）
- **AC10:** bash 工具超时 → 返回 "Error: timed out"，进程被 kill

---

## Tasks / Subtasks

1. **SandboxResult + GrepMatch 数据类**（`sandbox/base.py`）
2. **Sandbox ABC**（`sandbox/base.py`）— 5 抽象方法 + id
3. **SandboxProvider ABC + 进程级单例**（`sandbox/provider.py`）
4. **LocalSandbox 实现**（`sandbox/local.py`）— subprocess + FS + 路径校验 + timeout
5. **SandboxContext + ContextVar**（`sandbox/context.py`）
6. **5 个文件/shell 工具**（`sandbox/tools.py`）— 委托 Sandbox，零 I/O，异常隔离
7. **包导出**（`sandbox/__init__.py` + 顶层 `__init__.py`）
8. **测试** — LocalSandbox 各方法 / 工具委托 / 异常隔离 / 路径越权 / 超时

---

## Dev Notes

### 关键设计点

1. **工具零 I/O** — bash 工具只调 `sandbox.execute_command()`，绝不直接 `subprocess.run`。这是核心约束，保证换实现不改工具。
2. **ContextVar 注入** — 与 workspace_context / subagent_context 完全同模式。宿主执行前 set，工具内 get。
3. **路径校验在 Sandbox 实现** — LocalSandbox 内部做 work_dir 白名单校验，工具不关心（换远程 sandbox 路径语义不同）。
4. **Provider 单例** — 与 TOOL_REGISTRY / checkpointer 同模式，进程级，启动时配置。
5. **backend 迁移另开 Story** — 本 Story 只做 harness 侧，不破坏 backend 现有 builtin_tools.py（它继续工作）。

### 与 v0.1 兼容

- **不修改** react_node / build_agent_graph / AgentState / ToolRegistry
- 5 个新工具通过 ToolRegistry 注册（与 backend 的 bash/read/write 共存，迁移时切换）
- ContextVar 是新增，不影响现有 workspace_context

### 与 deer-flow 的差异

| 维度 | deer-flow | 我们 |
|---|---|---|
| 注入机制 | Runtime (langchain create_agent) | ContextVar（纯 LangGraph） |
| Sandbox 方法数 | 8 | 5（精简，够用） |
| 默认实现 | LocalSandbox | LocalSandbox（同） |

---

## File List

**新增文件:**
- `packages/harness/src/agent_flow_harness/sandbox/__init__.py`
- `packages/harness/src/agent_flow_harness/sandbox/base.py` — Sandbox ABC + SandboxResult + GrepMatch
- `packages/harness/src/agent_flow_harness/sandbox/provider.py` — SandboxProvider ABC + 单例
- `packages/harness/src/agent_flow_harness/sandbox/local.py` — LocalSandbox
- `packages/harness/src/agent_flow_harness/sandbox/context.py` — SandboxContext + ContextVar
- `packages/harness/src/agent_flow_harness/sandbox/tools.py` — bash/read/write/glob/grep 五工具
- `packages/harness/tests/sandbox/test_base.py`
- `packages/harness/tests/sandbox/test_provider.py`
- `packages/harness/tests/sandbox/test_local.py`
- `packages/harness/tests/sandbox/test_tools.py`

**修改文件:**
- `packages/harness/src/agent_flow_harness/__init__.py` — 导出 sandbox API

**不修改（明确）:**
- `engine/react.py` / `graph/builder.py` / `state.py` / `tools/registry.py`
- `backend/app/engine/agent/builtin_tools.py`（继续工作，迁移另开 Story）
- `backend/app/engine/tool/sandbox.py`（继续工作，迁移另开 Story）

---

## References

- [SPEC.md §Always 三层工具模型](../../SPEC.md) — 架构决策
- [deer-flow sandbox/sandbox.py](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/sandbox/sandbox.py) — Sandbox ABC 参考
- [deer-flow sandbox/sandbox_provider.py](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/sandbox/sandbox_provider.py) — Provider 参考
- [v0.2-1 subagents context.py](../packages/harness/src/agent_flow_harness/subagents/context.py) — ContextVar 模式参照
- [v0.1-7 ToolRegistry](v0-1-7-tool-registry-and-builtin-tools.md) — Provider 单例模式参照
