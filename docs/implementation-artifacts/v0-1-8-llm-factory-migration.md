---
baseline_commit: v0.1-2
---

# Story v0.1-8: LLM 工厂迁移

**Epic:** v0.1 — Harness 拆包与基础
**Status:** done (实施完成，commit `cf77567`；API 命名 build_client_from_doc/build_client_from_env)
**Depends on:** v0.1-2

## Story

As a Agent Flow 维护者，
I want 把 `backend/app/engine/llm_factory.py` 迁移到 `packages/harness/src/agent_flow_harness/llm/`，支持 thinking mode 适配（Claude extended thinking / OpenAI reasoning_effort），
So that harness 自包含 LLM 客户端构建逻辑，应用层零改动即可接入多 provider LLM（OpenAI / Anthropic / 国内模型）。

## Acceptance Criteria

- **AC1:** `packages/harness/src/agent_flow_harness/llm/factory.py` 实现 `get_llm_client(agent: dict, *, enable_thinking: bool = False) -> BaseChatModel` 函数
- **AC2:** `get_llm_client` 函数签名与现状 `backend/app/engine/llm_factory.get_llm_client` **完全一致**（参数/返回值/异常行为）
- **AC3:** `packages/harness/src/agent_flow_harness/llm/providers/openai_compat.py` 迁移 OpenAI 兼容逻辑（支持 OpenAI / Azure / Anthropic / 国内模型）
- **AC4:** `packages/harness/src/agent_flow_harness/llm/thinking.py` 实现 thinking mode 适配：
  - Claude: `thinking={"type": "enabled", "budget_tokens": 5000}`
  - OpenAI o-series: `reasoning_effort="high"`
  - 其他模型: 静默忽略（不抛异常）
- **AC5:** `agent["llm_config"]` 配置字段解析正确：
  ```python
  agent["llm_config"] = {
      "provider": "openai",  # openai / anthropic / azure / custom
      "model": "gpt-4o-mini",
      "api_key_env": "OPENAI_API_KEY",
      "base_url": None,  # 可选（自定义 endpoint）
      "temperature": 0.7,
      "max_tokens": 4096,
      "context_window": 128000,
  }
  ```
- **AC6:** 从 `backend/app/engine/llm_factory.py` 迁移代码到 harness，**行为完全一致**
- **AC7:** `engine/react.py`（v0.1-2 实现）改为通过 `get_llm_client(agent_doc)` 获取 LLM 客户端
- **AC8:** 不支持 thinking mode 的模型启用 `enable_thinking=True` 时静默降级，**不抛异常**
- **AC9:** 提供 10+ 单元测试覆盖：
  - `get_llm_client` 各 provider 测试（openai/anthropic/azure）
  - `thinking.py` 适配逻辑测试（Claude / o-series / 其他）
  - `enable_thinking=False` 默认行为
  - 配置缺失字段时的异常处理
  - `base_url` 自定义 endpoint 测试
- **AC10:** 应用层 `backend/app/engine/llm_factory.py` 删除，改为 `from agent_flow_harness.llm import get_llm_client`
- **AC11:** 应用层全部 169+ 测试通过，harness 10+ 测试通过，无回归

## Tasks / Subtasks

- [ ] **Story 文件** — 创建本文档
- [ ] **目录创建** — 创建 `packages/harness/src/agent_flow_harness/llm/` 目录
- [ ] **factory.py 迁移** — 从 `backend/app/engine/llm_factory.py` 复制 `get_llm_client` 函数
- [ ] **openai_compat.py 迁移** — 从 `backend/app/engine/llm_factory.py` 提取 OpenAI 兼容逻辑
- [ ] **thinking.py 实现** — 实现 `apply_thinking_mode(llm, enable_thinking, model_name)` 函数
- [ ] **Claude 适配** — Anthropic 模型传入 `thinking={"type": "enabled", "budget_tokens": 5000}`
- [ ] **OpenAI o-series 适配** — o1/o3 模型传入 `reasoning_effort="high"`
- [ ] **静默降级** — 其他模型忽略 `enable_thinking` 参数
- [ ] **react.py 集成** — 改为 `get_llm_client(agent_doc, enable_thinking=...)`
- [ ] **删除旧代码** — 删除 `backend/app/engine/llm_factory.py`
- [ ] **10+ 单元测试** — 覆盖各 provider / thinking mode / 配置解析
- [ ] **Run & Verify** — 应用层全部 169+ 测试通过，harness 10+ 测试通过，无回归

## Dev Notes

### 核心约束（绝不能违反）

**harness 不可依赖以下**（应用层基础设施）：

```
❌ fastapi / uvicorn / starlette
❌ motor / pymongo / mongoengine / beanie
❌ celery / redis / kombu
❌ app.models.* / app.services.* / app.api.*
```

**harness 允许依赖**：

```
✅ langgraph >= 1.0.8
✅ langchain-core / langchain-* (官方库)
✅ pydantic >= 2.0
✅ structlog
✅ typing-extensions
```

### LLM 工厂设计

**get_llm_client 函数签名（与现状完全一致）：**

```python
# packages/harness/src/agent_flow_harness/llm/factory.py
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel

class LLMConfig(BaseModel):
    provider: str  # openai / anthropic / azure / custom
    model: str
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str | None = None
    temperature: float = 0.7
    max_tokens: int = 4096
    context_window: int = 128000

def get_llm_client(
    agent: dict,
    *,
    enable_thinking: bool = False,
) -> BaseChatModel:
    """
    根据 agent["llm_config"] 构建 LLM 客户端。

    Args:
        agent: Agent 配置字典，包含 llm_config 字段
        enable_thinking: 是否启用 thinking mode（Claude extended thinking / OpenAI reasoning_effort）

    Returns:
        BaseChatModel 实例

    Raises:
        ValueError: llm_config 缺失或 provider 不支持
        RuntimeError: API key 环境变量未设置
    """
    llm_config_data = agent.get("llm_config")
    if not llm_config_data:
        raise ValueError("agent['llm_config'] is required")

    llm_config = LLMConfig(**llm_config_data)

    # 1. 获取 API key
    import os
    api_key = os.environ.get(llm_config.api_key_env)
    if not api_key:
        raise RuntimeError(f"Environment variable {llm_config.api_key_env} not set")

    # 2. 按 provider 构建
    if llm_config.provider == "openai":
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            model=llm_config.model,
            api_key=api_key,
            base_url=llm_config.base_url,
            temperature=llm_config.temperature,
            max_tokens=llm_config.max_tokens,
        )

    elif llm_config.provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        llm = ChatAnthropic(
            model=llm_config.model,
            api_key=api_key,
            temperature=llm_config.temperature,
            max_tokens=llm_config.max_tokens,
        )

    elif llm_config.provider == "azure":
        from langchain_openai import AzureChatOpenAI
        llm = AzureChatOpenAI(
            azure_deployment=llm_config.model,
            api_key=api_key,
            azure_endpoint=llm_config.base_url,
            temperature=llm_config.temperature,
            max_tokens=llm_config.max_tokens,
        )

    else:
        raise ValueError(f"Unsupported provider: {llm_config.provider}")

    # 3. 应用 thinking mode（如果启用）
    if enable_thinking:
        from agent_flow_harness.llm.thinking import apply_thinking_mode
        llm = apply_thinking_mode(llm, enable_thinking=True, model_name=llm_config.model)

    return llm
```

### Thinking Mode 适配

**thinking.py — apply_thinking_mode：**

```python
# packages/harness/src/agent_flow_harness/llm/thinking.py
from langchain_core.language_models import BaseChatModel

def apply_thinking_mode(
    llm: BaseChatModel,
    *,
    enable_thinking: bool,
    model_name: str,
) -> BaseChatModel:
    """
    应用 thinking mode 到 LLM 客户端。

    - Claude (Anthropic): thinking={"type": "enabled", "budget_tokens": 5000}
    - OpenAI o-series (o1/o3): reasoning_effort="high"
    - 其他模型: 静默忽略（不抛异常）

    Args:
        llm: LLM 客户端实例
        enable_thinking: 是否启用 thinking mode
        model_name: 模型名称（用于判断 provider）

    Returns:
        修改后的 LLM 客户端（或原实例）
    """
    if not enable_thinking:
        return llm

    # Claude (Anthropic)
    if "claude" in model_name.lower() or "anthropic" in type(llm).__name__.lower():
        # ChatAnthropic 支持 thinking 参数
        if hasattr(llm, "thinking"):
            llm.thinking = {"type": "enabled", "budget_tokens": 5000}
        else:
            # 旧版本不支持，静默忽略
            logger.warning(f"Model {model_name} does not support thinking mode, ignoring")
        return llm

    # OpenAI o-series
    if model_name.lower().startswith(("o1", "o3")):
        # ChatOpenAI 支持 reasoning_effort 参数
        if hasattr(llm, "reasoning_effort"):
            llm.reasoning_effort = "high"
        else:
            logger.warning(f"Model {model_name} does not support reasoning_effort, ignoring")
        return llm

    # 其他模型 — 静默忽略
    logger.info(f"Model {model_name} does not support thinking mode, ignoring")
    return llm
```

### Provider 支持矩阵

| Provider | 类 | thinking 支持 | 备注 |
|----------|---|--------------|------|
| openai | ChatOpenAI | o1/o3 (reasoning_effort) | gpt-4o 不支持 |
| anthropic | ChatAnthropic | ✅ (thinking) | Claude 3.5+ |
| azure | AzureChatOpenAI | 同 openai | Azure 部署 |
| custom | ChatOpenAI (base_url) | 取决于后端 | 国内模型（Qwen/GLM/...） |

### Agent LLM 配置

**agent["llm_config"] 字段：**

```python
agent["llm_config"] = {
    "provider": "openai",  # openai / anthropic / azure / custom
    "model": "gpt-4o-mini",
    "api_key_env": "OPENAI_API_KEY",  # 环境变量名
    "base_url": None,  # 可选（自定义 endpoint）
    "temperature": 0.7,
    "max_tokens": 4096,
    "context_window": 128000,  # 用于 context 压缩
}
```

**配置解析逻辑：**
1. 从 `agent["llm_config"]` 提取配置
2. 验证必需字段（provider / model / api_key_env）
3. 从环境变量获取 API key
4. 按 provider 实例化对应 LLM 类
5. 如果 `enable_thinking=True`，应用 thinking mode 适配

### 与当前 llm_factory.py 的对比

**当前实现（`backend/app/engine/llm_factory.py`）：**

```python
def get_llm_client(agent: dict, *, enable_thinking: bool = False) -> BaseChatModel:
    llm_config = agent.get("llm_config")
    if not llm_config:
        raise ValueError("agent['llm_config'] is required")

    provider = llm_config["provider"]
    model = llm_config["model"]
    api_key_env = llm_config.get("api_key_env", "OPENAI_API_KEY")
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise RuntimeError(f"Environment variable {api_key_env} not set")

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            model=model,
            api_key=api_key,
            temperature=llm_config.get("temperature", 0.7),
            max_tokens=llm_config.get("max_tokens", 4096),
        )
    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        llm = ChatAnthropic(
            model=model,
            api_key=api_key,
            temperature=llm_config.get("temperature", 0.7),
            max_tokens=llm_config.get("max_tokens", 4096),
        )
    # ... 其他 provider

    # thinking mode 适配（硬编码）
    if enable_thinking:
        if "claude" in model.lower():
            llm.thinking = {"type": "enabled", "budget_tokens": 5000}
        elif model.startswith("o1") or model.startswith("o3"):
            llm.reasoning_effort = "high"

    return llm
```

**v0.1-8 新实现：**

```python
def get_llm_client(agent: dict, *, enable_thinking: bool = False) -> BaseChatModel:
    from agent_flow_harness.llm.factory import get_llm_client as _get_llm_client
    return _get_llm_client(agent, enable_thinking=enable_thinking)
```

**优势：**
- 代码从 harness 外迁移到 harness 内
- thinking mode 适配集中到 `thinking.py`
- 支持更多 provider（通过 providers/ 扩展）
- 应用层零改动（函数签名完全一致）

### 测试组织（v0.1-8）

```
packages/harness/tests/
├── llm/
│   ├── __init__.py
│   ├── test_factory.py          # 6+ 用例
│   │   ├── test_get_llm_client_openai
│   │   ├── test_get_llm_client_anthropic
│   │   ├── test_get_llm_client_azure
│   │   ├── test_get_llm_client_missing_config
│   │   ├── test_get_llm_client_missing_api_key
│   │   └── test_get_llm_client_unsupported_provider
│   └── test_thinking.py         # 4+ 用例
│       ├── test_apply_thinking_claude
│       ├── test_apply_thinking_openai_oseries
│       ├── test_apply_thinking_unsupported_model
│       └── test_apply_thinking_disabled
```

### 兼容性

- `get_llm_client()` 的**对外行为**（输入 agent + enable_thinking，输出 BaseChatModel）**完全保持**
- 应用层 API（`POST /api/v1/sessions/{id}/messages`）**无变化**
- 前端 SSE 事件 schema 由 v0.1-3 继续保证不变

### 已知风险

| 风险 | 缓解 |
|------|------|
| 新 provider 需要修改 factory.py | v0.2 引入 `providers/` 注册表机制，支持动态扩展 |
| thinking mode 参数不兼容 | `apply_thinking_mode` 静默降级，记录 warning 日志 |
| API key 环境变量命名冲突 | 应用层负责管理环境变量，harness 只读取 |

## Dev Agent Record

### Implementation Plan

1. 创建 `packages/harness/src/agent_flow_harness/llm/` 目录
2. 从 `backend/app/engine/llm_factory.py` 迁移 `get_llm_client` 函数
3. 提取 OpenAI 兼容逻辑到 `providers/openai_compat.py`
4. 实现 `thinking.py`（apply_thinking_mode 函数）
5. 实现 Claude / OpenAI o-series / 其他模型的 thinking 适配
6. 更新 `engine/react.py` 改为 `get_llm_client(agent_doc, enable_thinking=...)`
7. 删除 `backend/app/engine/llm_factory.py`
8. 编写 10+ 单元测试
9. 运行完整测试套件

### Debug Log



### Completion Notes



## File List

**新增文件:**
- `packages/harness/src/agent_flow_harness/llm/__init__.py`
- `packages/harness/src/agent_flow_harness/llm/factory.py` — get_llm_client 函数
- `packages/harness/src/agent_flow_harness/llm/providers/__init__.py`
- `packages/harness/src/agent_flow_harness/llm/providers/openai_compat.py` — OpenAI 兼容逻辑
- `packages/harness/src/agent_flow_harness/llm/thinking.py` — thinking mode 适配
- `packages/harness/tests/llm/__init__.py`
- `packages/harness/tests/llm/test_factory.py` — 6+ 测试
- `packages/harness/tests/llm/test_thinking.py` — 4+ 测试

**修改文件:**
- `packages/harness/src/agent_flow_harness/__init__.py` — re-export get_llm_client
- `packages/harness/src/agent_flow_harness/engine/react.py` — 改为 get_llm_client(agent_doc, enable_thinking=...)
- `packages/app/pyproject.toml` — 无变化（已在 v0.1-1 添加 Git 依赖）

**删除文件:**
- `backend/app/engine/llm_factory.py`

## Change Log

- 2026-06-23: Story v0.1-8 创建 — LLM 工厂迁移（ready-for-dev，依赖 v0.1-2）

## Status

**Status:** ready-for-dev
