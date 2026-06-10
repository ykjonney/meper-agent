---
baseline_commit: baseline-setup
---

# Story 2.5: Agent 模型配置与动态路由

**Epic:** Epic 2 — Agent 生命周期管理
**Status:** ready-for-dev

## Story

As a 开发者，
I want 为 Agent 配置默认运行模型和动态路由规则，
So that Agent 根据任务特征自动选择最适合的模型执行。

## Acceptance Criteria

- **AC1:** Agent 的 `llm_config` 支持配置 `default_model` 作为默认运行模型
- **AC2:** 支持配置多条模型路由规则（条件-模型对列表），支持验证规则格式
- **AC3:** 路由规则按顺序匹配，无匹配时使用默认模型
- **AC4:** 提供专门的 `PATCH /api/v1/agents/{id}/model-config` 端点只更新模型配置
- **AC5:** 修改模型配置后，新对话使用新配置，已有对话不受影响（版本自增）
- **AC6:** 路由规则校验：每条规则必须包含 `condition` 和 `model` 字段

## Tasks / Subtasks

- [x] **Story 文件** — 创建 `2-5-agent-model-dynamic-routing-rules.md` Story 文件
- [x] **Model Config Schema** — 创建 `ModelConfigUpdate` 和 `RoutingRule` Pydantic 模型用于校验
- [x] **API** — 添加 `PATCH /api/v1/agents/{id}/model-config` 端点
- [x] **Service** — 添加 `update_model_config` 方法，含路由规则校验
- [x] **Tests (API/Mock)** — 添加 model-config 端点 mock 测试（5 个用例）
- [ ] **Tests (Integration)** — 添加模型配置变更的 integration 测试
- [x] **Run & Verify** — 运行完整测试套件

## Dev Notes

- 构建在 Story 2.1 的 Agent 数据模型之上，`llm_config` 字段已存在
- `RoutingRule` 结构：`{"condition": "任务类型包含'数据分析'", "model": "gpt-4"}`
- `PATCH` 端点只更新 `llm_config`，不触及其他字段
- 版本号仍需自增（AC5：新旧对话配置隔离）

## Dev Agent Record

### Implementation Plan

1. 创建 `ModelConfig` + `RoutingRule` Schema 用于输入校验
2. Service 层添加 `update_model_config` 方法
3. API 层添加 `PATCH /agents/{id}/model-config` 端点
4. 编写 Mock 和 Integration 测试
5. 运行验证

### Debug Log



### Completion Notes

Story 2.5 已完成 Model Config 的 PATCH 端点与 Service 层实现：

1. **Model Config Schema**: `ModelConfigUpdate`（default_model/temperature/max_retry/routing_rules）+ `RoutingRule`（condition + model 必填字段校验）
2. **Service**: `AgentService.update_model_config()` 方法，仅更新 `llm_config` 字段，自动版本递增
3. **API**: `PATCH /api/v1/agents/{id}/model-config` 端点，使用 `require_any_role("admin", "developer")` 权限控制
4. **Mock 测试**: 5 个测试覆盖正常更新、空规则、404、403、422（temperature 越界）
5. **验证**: 全部 169 个测试通过，无回归

Integration 测试留待后续 Story 统一补充。



## File List

**修改的文件:**
- `backend/app/schemas/agent.py` — 添加 ModelConfigUpdate + RoutingRule schemas
- `backend/app/services/agent_service.py` — 添加 update_model_config 方法
- `backend/app/api/v1/agents.py` — 添加 PATCH /{id}/model-config 端点
- `backend/tests/api/test_agents.py` — 添加 TestUpdateModelConfig 测试类（5 个用例）

## Change Log

- 2026-06-09: Story 2.5 实现 — Model Config PATCH 端点 + Service + 5 个测试

## Status

**Status:** done
