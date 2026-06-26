# 通知提醒服务设计文档

**日期**: 2026-06-26
**状态**: 已批准

## 1. 背景与动机

当前 agent-flow 前端通过 TanStack Query 的 `refetchInterval: 5000` 轮询获取 Task 状态更新，存在以下问题：

- Task 看板 6 列并发轮询，产生大量无效请求
- 活跃任务详情 5 秒轮询，不管状态是否变化
- Workflow 测试运行使用 `setTimeout` 循环轮询
- 用户无法及时感知任务失败、等待审批等关键事件
- 没有通知中心，没有通知持久化

本项目通过引入 WebSocket 实时推送 + MongoDB 通知持久化，彻底消除轮询机制。

## 2. 需求摘要

| 维度 | 决策 |
|---|---|
| 传输协议 | WebSocket |
| 持久化 | MongoDB 存储 + 通知中心 UI |
| 通知范围 | 仅任务相关人（`created_by`） |
| 触发通知的事件 | `task.failed` / `task.waiting_human` / `task.completed` |
| 状态同步 | 所有 task 状态变更实时推送（瞬态，不持久化） |
| 浏览器原生通知 | 不需要 |
| 替换轮询 | 是 |

## 3. 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                      前端 (React)                        │
│                                                         │
│  ┌──────────┐  ┌───────────────┐  ┌─────────────────┐  │
│  │ Task 看板 │  │ 通知中心面板   │  │ WebSocket Client│  │
│  │(TanStack  │  │(notification  │  │ (ws-client.ts)  │  │
│  │  Query)   │  │   -store)     │  │                 │  │
│  └─────┬─────┘  └──────┬────────┘  └────────┬────────┘  │
│        │invalidate      │追加通知             │ 收到消息    │
│        └────────────────┴────────────────────┘           │
└─────────────────────────┬───────────────────────────────┘
                          │ WebSocket 长连接
                          │ ws://api/v1/ws?token=xxx
                          │
┌─────────────────────────┼───────────────────────────────┐
│                     后端 (FastAPI)                        │
│                         │                                │
│  ┌──────────────────────▼──────────────────────────┐    │
│  │           WebSocketConnectionManager             │    │
│  │  user_id → Set[WebSocket] 映射                   │    │
│  │  广播 / 定向推送 / 心跳                            │    │
│  └──────────────────────┬──────────────────────────┘    │
│                         │ push                           │
│  ┌──────────────────────▼──────────────────────────┐    │
│  │           NotificationService                    │    │
│  │  订阅 EventBus → 分类处理:                        │    │
│  │  - 所有 task.* → 推送 task_status (瞬态)          │    │
│  │  - failed/waiting_human/completed → 持久化+推送   │    │
│  └──────┬───────────────────────┬──────────────────┘    │
│         │                       │                        │
│  ┌──────▼──────┐       ┌───────▼────────┐              │
│  │  EventBus   │       │  MongoDB        │              │
│  │ (已有)       │       │  notifications  │              │
│  └─────────────┘       └────────────────┘              │
│                                                         │
│  ┌─────────────────────────────────────────┐           │
│  │  REST API (通知历史)                      │           │
│  │  GET    /notifications                  │           │
│  │  PATCH  /notifications/{id}/read        │           │
│  │  PATCH  /notifications/read-all         │           │
│  │  GET    /notifications/unread-count     │           │
│  └─────────────────────────────────────────┘           │
└─────────────────────────────────────────────────────────┘
```

整体分三层：

1. **WebSocket 层**：连接管理、消息分发
2. **通知服务层**：EventBus 订阅 → 分类 → 持久化 + 推送
3. **REST API 层**：通知历史查询（首次加载、翻页、已读管理）

## 4. WebSocket 后端设计

### 4.1 连接端点

```
GET /api/v1/ws
```

- 使用 FastAPI WebSocket，通过 query param `?token=xxx` 认证
- 连接建立后校验 JWT，提取 `user_id`
- 心跳：每 30 秒服务端发 `{"type": "ping"}`，客户端回 `{"type": "pong"}`，超时 60 秒未收到 pong 则断开

### 4.2 ConnectionManager

```python
class WebSocketConnectionManager:
    """管理所有 WebSocket 连接"""

    def __init__(self):
        # user_id -> set of active connections
        self._connections: dict[str, set[WebSocket]] = {}

    async def connect(self, user_id: str, ws: WebSocket) -> None:
        """注册新连接"""

    def disconnect(self, user_id: str, ws: WebSocket) -> None:
        """移除连接，user_id 无连接时清理 key"""

    async def send_to_user(self, user_id: str, message: dict) -> None:
        """向指定用户的所有连接广播消息"""

    async def broadcast(self, message: dict) -> None:
        """向所有连接广播（预留）"""
```

- 一个用户可能有多个连接（多标签页/多设备），`send_to_user` 向该用户所有连接都发
- 发送失败（连接已断）时自动清理，不影响其他连接
- 模块级单例通过 `get_ws_manager()` 获取

### 4.3 消息格式

```jsonc
// === 服务端 → 客户端 ===

// 1. 状态同步（瞬态，不持久化）
{
  "type": "task_status",
  "data": {
    "task_id": "task_xxx",
    "status": "running",
    "from_status": "pending",
    "workflow_id": "wf_xxx",
    "updated_at": "2026-06-26T10:00:00Z"
  }
}

// 2. 通知（持久化）
{
  "type": "notification",
  "data": {
    "id": "notif_xxx",
    "kind": "task_failed",
    "title": "任务执行失败",
    "body": "Workflow「数据处理」任务失败: 节点 LLM 执行超时",
    "related_task_id": "task_xxx",
    "read": false,
    "created_at": "2026-06-26T10:00:00Z"
  }
}

// 3. 心跳
{ "type": "ping" }

// 4. 认证过期（提示前端刷新 token）
{ "type": "auth_expired" }

// === 客户端 → 服务端 ===
{ "type": "pong" }
```

## 5. 通知数据模型

```python
class NotificationKind(str, Enum):
    TASK_FAILED = "task_failed"
    TASK_WAITING_HUMAN = "task_waiting_human"
    TASK_COMPLETED = "task_completed"

class Notification(BaseModel):
    id: str                          # "notif_xxx"
    user_id: str                     # 接收人
    kind: NotificationKind
    title: str                       # 通知标题
    body: str                        # 通知详情
    related_task_id: str | None      # 关联任务（可选）
    related_workflow_id: str | None  # 关联工作流（可选）
    read: bool = False               # 已读标记
    created_at: datetime
```

MongoDB 集合 `notifications`，索引：

- `user_id` + `created_at` DESC（通知列表查询）
- `user_id` + `read`（未读计数）

## 6. NotificationService（EventBus 桥接层）

### 6.1 职责

订阅 EventBus，将任务事件分类处理：

- **所有 task 状态变更** → 推送 `task_status` 给 Task 的 `created_by` 用户（瞬态）
- **特定事件**（failed / waiting_human / completed）→ 额外创建 Notification 持久化 + 推送给 `created_by`
- 若 `created_by` 为空（历史数据兼容），跳过推送，不报错

### 6.2 核心逻辑

```python
class NotificationService:
    """EventBus → WebSocket 推送 + 通知持久化"""

    NOTIFY_EVENTS = {"task.failed", "task.waiting_human", "task.completed"}

    def __init__(
        self,
        event_bus: EventBus,
        ws_manager: WebSocketConnectionManager,
        notification_repo: NotificationRepository,
    ): ...

    def register(self) -> None:
        """订阅 EventBus 的 task.* 事件"""
        self._event_bus.subscribe("task.*", self._on_task_event)

    async def _on_task_event(self, event: TaskEvent) -> None:
        task = await self._load_task(event.task_id)
        user_id = task.created_by

        # 1. 所有状态变更 → 推送 task_status（瞬态）
        await self._ws_manager.send_to_user(user_id, {
            "type": "task_status",
            "data": {
                "task_id": event.task_id,
                "status": event.to_status,
                "from_status": event.from_status,
                "workflow_id": task.workflow_id,
                "updated_at": event.timestamp.isoformat(),
            }
        })

        # 2. 特定事件 → 额外持久化通知
        if event.event_type in self.NOTIFY_EVENTS:
            notification = self._build_notification(event, task)
            await self._notification_repo.insert(notification)
            await self._ws_manager.send_to_user(user_id, {
                "type": "notification",
                "data": notification.model_dump(),
            })

    def _build_notification(self, event: TaskEvent, task: Task) -> Notification:
        """根据事件类型生成通知标题和正文"""
        # task.failed → "任务执行失败" + 错误摘要
        # task.waiting_human → "任务等待审批" + 审批节点信息
        # task.completed → "任务执行完成" + 耗时统计
        ...
```

### 6.3 生命周期

在 FastAPI lifespan 中初始化并注册：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... 现有初始化 ...

    notification_service = NotificationService(
        event_bus=get_event_bus(),
        ws_manager=get_ws_manager(),
        notification_repo=NotificationRepository(get_db()),
    )
    notification_service.register()

    yield
```

## 7. REST API

```
GET    /api/v1/notifications
       ?page=1&page_size=20&read=false&kind=task_failed
       → 分页查询通知列表（含总数）

GET    /api/v1/notifications/unread-count
       → 返回 { "count": 3 }

PATCH  /api/v1/notifications/{id}/read
       → 标记单条已读

PATCH  /api/v1/notifications/read-all
       → 标记当前用户所有通知已读
```

- 所有接口按 `user_id` 隔离，只能看到自己的通知
- `unread-count` 独立端点，轻量快速，用于页面首次加载时 badge 数字

## 8. 前端设计

### 8.1 WebSocket Client（替换空壳 ws-client.ts）

```typescript
class WsClient {
  private ws: WebSocket | null = null
  private reconnectTimer: number | null = null
  private listeners: Map<string, Set<(data: any) => void>> = new Map()

  connect(): void {
    const token = useAuthStore.getState().token
    const wsUrl = `${WS_BASE_URL}/api/v1/ws?token=${token}`
    this.ws = new WebSocket(wsUrl)

    this.ws.onmessage = (event) => {
      const msg = JSON.parse(event.data)
      if (msg.type === 'ping') {
        this.ws?.send(JSON.stringify({ type: 'pong' }))
        return
      }
      this.emit(msg.type, msg.data)
    }

    this.ws.onclose = () => {
      this.scheduleReconnect()  // 指数退避: 1s → 2s → 4s → 8s → 最大 30s
    }
  }

  on(type: string, handler: (data: any) => void): () => void {
    // 注册监听，返回取消函数
  }

  disconnect(): void { ... }
}

export const wsClient = new WsClient()
```

- 全局单例，登录后 `connect()`，登出时 `disconnect()`
- 自动重连带指数退避
- 按消息类型分发事件（`task_status`、`notification`）

### 8.2 前端事件桥接 Hook

```typescript
// hooks/use-task-realtime.ts
export function useTaskRealtime() {
  const queryClient = useQueryClient()

  useEffect(() => {
    const unsubStatus = wsClient.on('task_status', (data) => {
      queryClient.invalidateQueries({
        queryKey: taskKeys.list({ status: data.status })
      })
      queryClient.invalidateQueries({
        queryKey: taskKeys.detail(data.task_id)
      })
      if (data.from_status) {
        queryClient.invalidateQueries({
          queryKey: taskKeys.list({ status: data.from_status })
        })
      }
    })

    const unsubNotif = wsClient.on('notification', (data) => {
      useNotificationStore.getState().addNotification(data)
    })

    return () => { unsubStatus(); unsubNotif() }
  }, [])
}
```

在 App 根组件调用一次，全局生效。

### 8.3 Notification Store（替换占位实现）

```typescript
interface NotificationItem {
  id: string
  kind: 'task_failed' | 'task_waiting_human' | 'task_completed'
  title: string
  body: string
  related_task_id?: string
  read: boolean
  created_at: string
}

interface NotificationState {
  notifications: NotificationItem[]
  unreadCount: number
  loadFromApi: (notifications: NotificationItem[]) => void
  addNotification: (notification: NotificationItem) => void
  markAsRead: (id: string) => Promise<void>
  markAllAsRead: () => Promise<void>
}
```

### 8.4 通知中心 UI

顶部导航栏通知图标 + 下拉面板：

- 铃铛图标上显示未读数 badge
- 点击展开下拉面板，显示最近通知
- 点击通知 → 跳转到关联 Task 详情
- "查看全部" → 进入通知中心完整页面（分页、筛选、全部标记已读）

### 8.5 轮询移除

| 现有轮询 | 替换为 |
|---|---|
| `tasks-page.tsx` 看板列表 `refetchInterval: 5000` | 移除，`useTaskRealtime()` 监听 `task_status` 触发 invalidate |
| `tasks-page.tsx` 活跃详情 `refetchInterval: 5000` | 同上 |
| `tasks-page.tsx` Drawer 条件轮询 | 同上 |
| `workflow-detail-page.tsx` `pollTaskStatus()` setTimeout 循环 | 改为 WebSocket 监听 `task_status`，配合初始一次 HTTP 请求 |

页面首次加载仍通过 HTTP 请求获取完整数据，WebSocket 只负责增量更新。

## 9. 错误处理与边界情况

| 场景 | 处理方式 |
|---|---|
| WebSocket 连接失败 | 指数退避重连，页面顶部 toast 提示"连接中..." |
| 连接断开重连期间 | 不丢失通知，重连后 REST API 补拉未读 |
| EventBus handler 抛异常 | 依赖 EventBus 自带 3 次重试 + dead-letter |
| Notification 写 MongoDB 失败 | 重试期间 task_status 仍然推送（两者独立） |
| 用户多标签页 | 每个标签页独立 WS 连接，都收到推送，TanStack Query 缓存各自刷新 |
| Token 过期 | 服务端发 `auth_expired`，前端 refresh token 后重连 |
| 如何找到通知接收人 | 查 Task 的 `created_by`，无需新增字段 |
| 离线期间的通知 | 用户重连后通过 REST API 拉取未读 |

## 10. 不做的事（YAGNI）

- 多渠道通知（飞书/邮件）— 后续迭代
- 浏览器原生通知 — 不需要
- Redis Pub/Sub 跨实例广播 — 单实例够用
- 通知分组/聚合 — 过度设计
- 用户自定义通知偏好设置 — 后续迭代
- 通知模板引擎 — 直接用代码拼接标题和正文

## 11. 方案选择记录

考虑了三种方案：

- **方案 A：直连模式**（已选）— EventBus → NotificationHandler → ConnectionManager → WebSocket。最简单，利用现有 EventBus，单实例足够。
- **方案 B：Redis Pub/Sub** — 天然支持多实例但当前过度设计。
- **方案 C：Celery 消息队列** — 架构最复杂，通知逻辑很轻量不需要独立 worker。

ConnectionManager 设计为接口，未来需要多实例时只需替换为 Redis Pub/Sub 实现。
