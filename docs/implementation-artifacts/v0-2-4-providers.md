# Story v0.2-4: Providers — LLM 工厂 Provider 扩展

**Epic:** v0.2 — P1 增强模块
**Status:** backlog
**Depends on:** v0.1-8 (LLM 工厂)

---

## Story

As **Agent Flow 多云架构师**,
I want **harness 的 LLM 工厂支持除 OpenAI / Anthropic 之外的主流 Provider（Azure / Bedrock / Vertex / Ollama）**,
So that **企业用户能用私有云、本地模型、托管服务接入 harness，不被锁定在单一 SaaS 提供商**。

---

## 背景与动机

v0.1-8 锁定了 2 个 Provider：

- `openai` → `langchain_openai.ChatOpenAI`
- `anthropic` → `langchain_anthropic.ChatAnthropic`

**生产场景的覆盖不足**：

1. **企业合规** — 不能用 OpenAI 直连，需 Azure OpenAI 私有部署
2. **AWS 客户** — 希望走 Bedrock（Claude / Llama / Titan）
3. **GCP 客户** — 希望走 Vertex AI
4. **本地 / 离线** — 希望跑 Ollama / vLLM
5. **多区域** — 不同地区有不同可用模型

`providers` 模块目标：在不破坏 v0.1-8 API 的前提下，扩展 Provider 注册协议。

---

## 范围

### Must（必须做）

- `LLMProvider` Protocol 定义（`name` / `build(config) -> BaseChatModel` / `apply_thinking(llm, enable, model_name) -> BaseChatModel`）
- `PROVIDER_REGISTRY` 注册中心（与 v0.1-8 的 `MIDDLEWARE_REGISTRY` 同构）
- 4 个新增 Provider 实现：
  - `AzureProvider`（Azure OpenAI）
  - `BedrockProvider`（AWS Bedrock）
  - `VertexProvider`（Google Vertex AI）
  - `OllamaProvider`（本地 Ollama）
- `get_llm_client` 改造：根据 `agent["llm_config"]["provider"]` 查 `PROVIDER_REGISTRY`

### Should（应该做）

- `ProviderConfig` 通用 schema（含 `api_key_env` / `base_url` / `region` / `extra`）
- 启动时注册**默认 2 个**（openai / anthropic）+ **可选 4 个**（azure / bedrock / vertex / ollama）
- 选型失败清晰报错（`Unknown provider: 'azure'. Available: ['openai', 'anthropic', ...]. Hint: did you forget to import?`）

### Won't（不在本 Story 做）

- 模型路由 / fallback（一个 provider 失败自动切到另一个）
- 自定义权重 / 成本计算
- 私有模型微调接口

---

## Acceptance Criteria

- **AC1:** `packages/harness/src/agent_flow_harness/llm/providers/__init__.py` 导出 `LLMProvider` Protocol / `PROVIDER_REGISTRY` / `register_provider`
- **AC2:** `LLMProvider` Protocol 包含 `name: str` / `def build(config: ProviderConfig) -> BaseChatModel` / `def apply_thinking(llm, enable_thinking, model_name) -> BaseChatModel`
- **AC3:** `ProviderConfig` Pydantic model 字段：`provider: str` / `model: str` / `api_key_env: str = "OPENAI_API_KEY"` / `base_url: str | None = None` / `region: str | None = None` / `extra: dict = {}` / `temperature: float = 0.7` / `max_tokens: int = 4096`
- **AC4:** `AzureProvider` 实现（基于 `langchain_openai.AzureChatOpenAI`）
- **AC5:** `BedrockProvider` 实现（基于 `langchain_aws.ChatBedrock`）
- **AC6:** `VertexProvider` 实现（基于 `langchain_google_vertexai.ChatVertexAI`）
- **AC7:** `OllamaProvider` 实现（基于 `langchain_ollama.ChatOllama`）
- **AC8:** `get_llm_client` v0.1-8 API 签名**完全不变**，内部改为查 `PROVIDER_REGISTRY`
- **AC9:** 4 个新增 Provider 的 thinking mode 适配（Azure 复用 OpenAI / Bedrock 调 `model_kwargs` / Vertex 调 `safety_settings` / Ollama 不支持 thinking 返回原 llm）
- **AC10:** 30+ 单元测试通过（含 4 个 Provider 各 5+ 测试 + 8 个 thinking mode 适配测试）

---

## Tasks / Subtasks

1. **LLMProvider Protocol**
   - 三个方法：`build` / `apply_thinking` / 隐含 `name` 字段
   - 模仿 v0.1-7 `CommunityTool` Protocol 设计
2. **ProviderConfig schema**
   - Pydantic v2 BaseModel
   - 字段校验（`provider` 必须是非空字符串、`temperature ∈ [0, 2]`）
3. **PROVIDER_REGISTRY 注册中心**
   - `register_provider(provider: LLMProvider)` 装饰器/函数
   - `get_provider(name: str) -> LLMProvider` 查表（找不到抛 `ValueError` 给出 hint）
4. **AzureProvider 实现**
   - `build` 调 `AzureChatOpenAI(azure_endpoint=..., api_version=..., deployment_name=model, ...)`
   - `apply_thinking` 复用 OpenAI 逻辑（o1/o3 系列）
5. **BedrockProvider 实现**
   - `build` 调 `ChatBedrock(model_id=model, region_name=region, ...)`
   - `apply_thinking` 注入 `model_kwargs={"thinking": {"type": "enabled", "budget_tokens": 5000}}`（Anthropic on Bedrock）
6. **VertexProvider 实现**
   - `build` 调 `ChatVertexAI(model_name=model, project=..., location=region, ...)`
   - `apply_thinking` 调 `safety_settings`（Vertex 无原生 thinking，跳过或 warn）
7. **OllamaProvider 实现**
   - `build` 调 `ChatOllama(model=model, base_url=base_url)`
   - `apply_thinking` 静默忽略（Ollama 不支持 thinking）
8. **get_llm_client 改造**
   - v0.1-8 的 openai / anthropic 分支抽为 `OpenAIProvider` / `AnthropicProvider`
   - 启动时自动注册到 `PROVIDER_REGISTRY`
   - `get_llm_client` 改为 `provider = PROVIDER_REGISTRY.get(config["provider"]); llm = provider.build(config); llm = provider.apply_thinking(llm, enable_thinking, model)`
9. **依赖管理**
   - `pyproject.toml` 的 `[project.optional-dependencies]` 加 `azure` / `bedrock` / `vertex` / `ollama` 4 个 extras
   - 不强制安装，启动时按需 import
10. **测试**
    - 30+ 单元测试：4 个 Provider 各 5 个（build/thinking/缺依赖/参数错误/未知 provider）
    - 8 个 thinking mode 适配测试

---

## Dev Notes

### 关键设计点

1. **v0.1-8 API 零变更** — `get_llm_client(agent, *, enable_thinking)` 签名不变，仅内部实现改为查注册表
2. **按需 import** — 4 个 Provider 的 langchain 适配器不强制安装（`pyproject.toml` extras）
3. **Provider 失败友好提示** — 找不到 provider 时 hint 用户检查 import
4. **thinking mode 一致性** — 4 个 Provider 行为对齐 v0.1-8（能则用，不能则忽略并 warn）
5. **不要做 fallback** — 一个 provider 失败不要自动切到另一个（v0.3+ 考虑）

### 与 v0.1-8 兼容

- `OpenAIProvider` / `AnthropicProvider` 是 v0.1-8 内置分支的"包装"
- `get_llm_client` 默认注册 2 个，**对应用层无感**
- `agent["llm_config"]["provider"]` 已有字段，直接用

### Provider 配置示例

```python
# Azure OpenAI
agent_doc["llm_config"] = {
    "provider": "azure",
    "model": "gpt-4o",
    "api_key_env": "AZURE_OPENAI_API_KEY",
    "base_url": "https://mycompany.openai.azure.com",
    "extra": {"api_version": "2024-08-01-preview", "deployment_name": "gpt-4o-deploy"},
}

# AWS Bedrock (Claude)
agent_doc["llm_config"] = {
    "provider": "bedrock",
    "model": "anthropic.claude-3-5-sonnet-20241022-v2:0",
    "region": "us-east-1",
    "extra": {"aws_access_key_env": "AWS_ACCESS_KEY_ID", "aws_secret_key_env": "AWS_SECRET_ACCESS_KEY"},
}

# Google Vertex AI
agent_doc["llm_config"] = {
    "provider": "vertex",
    "model": "gemini-1.5-pro",
    "region": "us-central1",
    "extra": {"project": "my-gcp-project", "credentials_path": "/path/to/sa.json"},
}

# 本地 Ollama
agent_doc["llm_config"] = {
    "provider": "ollama",
    "model": "llama3.1:70b",
    "base_url": "http://localhost:11434",
}
```

### pyproject.toml extras 设计

```toml
[project.optional-dependencies]
azure = ["langchain-openai>=0.1", "openai>=1.0"]
bedrock = ["langchain-aws>=0.1", "boto3>=1.34"]
vertex = ["langchain-google-vertexai>=2.0", "google-cloud-aiplatform>=1.60"]
ollama = ["langchain-ollama>=0.1", "ollama>=0.3"]

# 默认安装（兼容 v0.1-8）
all = ["agent-flow-harness[azure,bedrock,vertex,ollama]"]
```

### 安全考量

- **API key 不入日志** — `get_llm_client` 失败时不要 print config（含 key）
- **base_url 校验** — 防止 LLM 注入到恶意 endpoint（用 `https?://` 白名单）
- **extra 字段透传风险** — 应用层必须自己控制，不要把 user input 塞进 `extra`

---

## File List

**新增文件:**
- `packages/harness/src/agent_flow_harness/llm/providers/__init__.py` — 已有（v0.1-8），扩展导出
- `packages/harness/src/agent_flow_harness/llm/providers/base.py` — LLMProvider Protocol + ProviderConfig
- `packages/harness/src/agent_flow_harness/llm/providers/registry.py` — PROVIDER_REGISTRY + register_provider
- `packages/harness/src/agent_flow_harness/llm/providers/azure.py`
- `packages/harness/src/agent_flow_harness/llm/providers/bedrock.py`
- `packages/harness/src/agent_flow_harness/llm/providers/vertex.py`
- `packages/harness/src/agent_flow_harness/llm/providers/ollama.py`
- `packages/harness/src/agent_flow_harness/llm/providers/openai.py` — 抽自 v0.1-8
- `packages/harness/src/agent_flow_harness/llm/providers/anthropic.py` — 抽自 v0.1-8
- `packages/harness/tests/llm/providers/test_azure.py`
- `packages/harness/tests/llm/providers/test_bedrock.py`
- `packages/harness/tests/llm/providers/test_vertex.py`
- `packages/harness/tests/llm/providers/test_ollama.py`
- `packages/harness/tests/llm/providers/test_registry.py`
- `packages/harness/tests/llm/providers/test_thinking.py`

**修改文件:**
- `packages/harness/src/agent_flow_harness/llm/factory.py` — 改为查 PROVIDER_REGISTRY
- `packages/harness/src/agent_flow_harness/llm/thinking.py` — thinking mode 改为 per-provider
- `packages/harness/pyproject.toml` — 新增 4 个 extras + `all` 聚合
- `packages/harness/src/agent_flow_harness/__init__.py` — 导出 LLMProvider / PROVIDER_REGISTRY

---

## References

- [SPEC.md §12.5 providers](../../SPEC.md) — 详细设计
- [v0.1-8 LLM factory](v0-1-8-llm-factory-migration.md) — 改造源
- [v0.1-7 tool registry](v0-1-7-tool-registry-and-builtin-tools.md) — CommunityTool 注册协议参考
- [langchain-openai](https://python.langchain.com/docs/integrations/chat/azure_chat_openai) / [langchain-aws](https://python.langchain.com/docs/integrations/chat/bedrock) / [langchain-google-vertexai](https://python.langchain.com/docs/integrations/chat/google_vertex_ai_palm) / [langchain-ollama](https://python.langchain.com/docs/integrations/chat/ollama)
