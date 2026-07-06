# Story 8.6: Rate Limiting 与监控

**Epic**: 8 — 外部 API 集成
**状态**: backlog
**依赖**: Story 8.1
**设计文档**: `docs/planning-artifacts/external-api-design.md`

## 用户故事

As a 平台管理员，
I want 对每个 API Key 进行请求限流并查看调用统计，
So that 平台不会被单个外部系统过载，且能追踪使用情况。

## Acceptance Criteria

### AC-1: Redis 滑动窗口限流

**Given** API Key 配置了 `rate_limit: 60`（次/分钟）
**When** 第 61 次请求在 1 分钟窗口内到达
**Then** 返回 429 Too Many Requests
**And** 响应头包含：
```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1720252860
```

**Given** 请求在限流范围内
**When** 请求通过
**Then** 响应头包含剩余配额：
```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 45
X-RateLimit-Reset: 1720252860
```

### AC-2: 限流粒度

**Given** 限流基于 API Key
**When** 不同 API Key 的请求到达
**Then** 各自独立计算配额，互不影响

### AC-3: 实现方式

**Given** 限流中间件
**When** 请求经过 `/api/v1/ext/` 路由
**Then** 使用 Redis sorted set 实现滑动窗口：
- Key: `ratelimit:{api_key_id}:{minute_timestamp}`
- 过期时间: 120s（自动清理）
**And** 限流检查在认证之后执行（先验证 Key 有效，再检查配额）

### AC-4: API Key 调用统计

**Given** API Key 的请求被处理
**When** 查看统计信息
**Then** 记录以下指标到 Redis（或 MongoDB 聚合）：
- 总请求数
- 成功请求数（2xx）
- 失败请求数（4xx/5xx）
- 按端点分组的请求数
- 最近调用时间

### AC-5: 统计查询 API（可选）

```
GET /api/v1/api-keys/{id}/stats
```

**Given** 管理员查询某个 API Key 的统计
**When** 请求
**Then** 返回调用统计摘要：
```json
{
  "api_key_id": "key_01H...",
  "total_requests": 1523,
  "successful": 1490,
  "failed": 33,
  "by_endpoint": {
    "agents:invoke": 800,
    "agents:read": 500,
    "workflows:invoke": 223
  },
  "last_used_at": "2026-07-06T10:00:00Z"
}
```

### AC-6: 实现文件

**Given** 开发完成
**Then** 以下文件已创建并通过测试：
- `app/core/rate_limiter.py` — 滑动窗口限流器
- `app/api/middleware/rate_limit.py` — FastAPI 中间件
- `app/services/api_key_stats_service.py` — 调用统计服务（可选）
