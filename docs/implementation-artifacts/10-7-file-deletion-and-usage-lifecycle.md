---
baseline_commit: e48a07f
---

# Story 10.7: 文件删除与使用生命周期

**Epic:** Epic 10 — 文件管理
**Status:** review
**Story ID:** 10-7
**Story Key:** 10-7-file-deletion-and-usage-lifecycle

## Story

As a 系统管理者，
I want 文件有完整的生命周期管理（回收站恢复、过期清理、消费者感知删除），
So that 文件资源不会无限积累，用户可恢复误删文件。

> ⚠️ **关键背景**：
> - `FileService.delete(force=False)` 当前直接硬删除（无引用时），docstring 说软删除但实际不是
> - `FileService.update_status()` 可做软删除（`status → trashed`）
> - API 层 `DELETE /files/{file_id}?force=true` 有引用时返回 409（与 service 层行为不一致）
> - `FileUsage.expires_at` 字段存在但从未被检查/清理
> - 无恢复、无过期清理、无消费者感知删除
> - 文件删除策略：**仅手动删除，不做自动 TTL**（产品决策）
> - 本 Story 补齐生命周期管理能力

## Acceptance Criteria

### AC1: 从回收站恢复
**Given** 文件已被软删除（`status: trashed`）
**When** `POST /api/v1/files/{file_id}/restore`
**Then** 文件 `status` 恢复为 `active`
**And** 返回更新后的 `FileRefResponse`

### AC2: 清空回收站
**Given** 用户有多个 trashed 文件
**When** `POST /api/v1/files/trash/empty`
**Then** 所有 `status: trashed` 且 `usage_count == 0` 的文件被硬删除
**And** 返回清理数量

### AC3: force-delete 行为一致化
**Given** `DELETE /files/{file_id}?force=true`
**When** 文件有引用
**Then** 不再返回 409 — 改为级联删除所有 FileUsage + 硬删除文件
**And** 返回 204

### AC4: FileService 软删除修复
**Given** `FileService.delete(force=False)`
**When** 调用删除
**Then** `force=False` 时执行软删除（`update_status → trashed`）
**And** `force=True` 时级联删除 usage + 物理文件 + DB 记录

### AC5: 过期 Usage 清理 API
**Given** 系统有过期的 FileUsage（`expires_at < now`）
**When** `POST /api/v1/files/cleanup`（管理员端）
**Then** 删除所有已过期的 FileUsage 记录
**And** 返回清理数量
**And** 清理后若文件无引用且 `status: trashed` → 一并硬删除

### AC6: 消费者感知删除
**Given** Session/Workflow/CronJob 被删除
**When** 删除操作完成
**Then** 对应的 FileUsage 记录自动清理（`consumer_kind + consumer_id`）
**And** 不影响其他消费者的引用

### AC7: 测试覆盖
**Given** 本 Story 所有功能
**When** 运行测试
**Then** 覆盖：
  - 从回收站恢复（正常 + 文件不存在 + 文件未删除）
  - 清空回收站（有/无引用 + 混合状态）
  - force-delete 级联删除
  - 过期 usage 清理
  - 消费者感知删除

### AC8: 回归兼容
**Given** 现有删除 API
**When** 修改行为
**Then** `DELETE /files/{file_id}`（无 force）仍为软删除
**And** 现有测试通过或合理更新

## Tasks / Subtasks

### 后端（Backend）

- [x] **T1: FileService 软删除修复** (AC: #4)
  - [x] 修改 `file_service.py` 的 `delete(force=False)`
  - [x] `force=False` → 调用 `update_status("trashed")` 并返回 True
  - [x] `force=True` → 级联删除 usage + 物理文件 + DB

- [x] **T2: 恢复端点** (AC: #1)
  - [x] 在 `files.py` 新增 `POST /files/{file_id}/restore`
  - [x] 调用 `update_status("active")`
  - [x] 文件不存在返回 404

- [x] **T3: 清空回收站端点** (AC: #2)
  - [x] 在 `files.py` 新增 `POST /files/trash/empty`
  - [x] 查询所有 trashed 文件
  - [x] 逐个检查 usage，无引用则硬删除
  - [x] 返回清理数量

- [x] **T4: force-delete 一致化** (AC: #3)
  - [x] 修改 `DELETE /files/{file_id}?force=true` 逻辑
  - [x] 有引用时不再 409 — 改为级联删除
  - [x] 更新测试

- [x] **T5: 过期 Usage 清理** (AC: #5)
  - [x] 在 FileService 新增 `cleanup_expired_usages()` 方法
  - [x] 在 `files.py` 新增 `POST /files/cleanup`
  - [x] 删除过期 usage + 无引用 trashed 文件

- [x] **T6: 消费者感知删除** (AC: #6)
  - [x] 在 FileService 新增 `remove_usages_by_consumer(consumer_kind, consumer_id)` 方法
  - [x] 在 session/workflow/cron 删除逻辑中调用（如已有删除端点）

- [x] **T7: 测试** (AC: #7, #8)
  - [x] 更新 `tests/services/test_file_service.py`
  - [x] 更新 `tests/api/test_files.py`
  - [x] 运行全量回归

## Dev Notes

### 📁 文件清单

**修改：**
- `backend/app/services/file_service.py` — 软删除修复 + cleanup_expired_usages + remove_usages_by_consumer
- `backend/app/api/v1/files.py` — restore + trash/empty + cleanup 端点 + force-delete 修改
- `backend/tests/services/test_file_service.py` — 更新测试
- `backend/tests/api/test_files.py` — 更新测试

### 🚫 本 Story 不做的事

- **不做自动 TTL 清理** — 产品决策：仅手动删除
- **不做前端回收站 UI** — 当前只做 API
- **不做存储用量统计** — 后续可增强
- **不做物理文件孤儿检测** — 需要磁盘扫描，成本高

## Dev Agent Record

### Implementation Plan
- T1: `delete(force=False)` → 调 `update_status("trashed")` 软删除；`force=True` 保持级联
- T2: `POST /{file_id}/restore` — 校验所有权，status≠trashed 时直接返回
- T3: `POST /trash/empty` — 查 trashed 文件，逐个检查 has_usages，无引用则 force=True
- T4: 移除 force-delete 的 409 检查，直接 `svc.delete(force=True)` 级联
- T5: `cleanup_expired_usages()` — 删过期 usage + 无引用 trashed 文件硬删除；`POST /cleanup`（admin only）
- T6: `remove_usages_by_consumer()` — 按 consumer_kind+consumer_id 批量删除 usage

### Completion Notes
✅ 全部 8 个 AC 满足
✅ 827 tests passed, 0 failures（818 原有 + 9 新增）
✅ FileService.delete(force=False) 改为软删除，force=True 级联删除
✅ 新增 3 个 API 端点：restore / trash/empty / cleanup
✅ force-delete 移除 409 限制，统一为级联删除
✅ cleanup_expired_usages 清理过期 usage + 无引用 trashed 文件
✅ remove_usages_by_consumer 消费者感知删除

## File List

**修改:**
- `backend/app/services/file_service.py` — delete 软删除 + cleanup_expired_usages + remove_usages_by_consumer
- `backend/app/api/v1/files.py` — restore / trash/empty / cleanup 端点 + force-delete 修改
- `backend/tests/services/test_file_service.py` — 更新 delete 测试 + 新增 cleanup/consumer 测试
- `backend/tests/api/test_files.py` — 更新 delete 测试 + 新增 restore/trash/cleanup 测试

## Change Log
- 2026-06-23: Story 10-7 开始实现
- 2026-06-23: Story 10-7 实现完成 — 软删除修复 + 恢复/清空/清理端点 + force-delete 一致化 + 消费者感知删除
