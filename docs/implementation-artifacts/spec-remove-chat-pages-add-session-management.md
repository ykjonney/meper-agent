---
title: '删除冗余聊天页面 + 实现会话管理'
type: 'feature'
created: '2026-06-10'
status: 'in-progress'
baseline_commit: 'NO_VCS'
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 聊天测试页（`/chat-test`）和对话页（`/conversations`）功能重复——Agent 详情页（`/agents/:id`）右侧已集成 ChatPanel，且当前所有聊天均无持久化（消息仅存于 React state，刷新即丢失）。对话页更是纯 Mock UI 无后端对接。

**Approach:** 删除两个冗余页面及其路由/菜单。在后端新建 Session + Message 两层模型（MongoDB），提供 RESTful API；前端 ChatPanel 对接 API 实现对话创建、消息持久化、历史加载，替换纯内存 state。

## Boundaries & Constraints

**Always:**
- Session 绑定 `user_id` + `agent_id`，一个用户对一个 Agent 可有多个 Session
- 消息按时间顺序存储，前端按时间线渲染（复用现有 TimelineEntry 渲染逻辑）
- ChatPanel 初始化时加载当前 session 的历史消息（如果传了 sessionId）
- 后端 invoke/stream 端点复用 `body.session_id` 作为 LangGraph `thread_id`，实现上下文连续
- 所有新端点需要认证（`get_current_user`）

**Ask First:**
- Message 模型是否需要分表（按 session_id 嵌入 session 文档 vs 独立 collection）

**Never:**
- 不修改 Agent 详情页的左右分栏布局
- 不实现对话搜索/置顶/归档功能（MVP 后续）
- 不删除 ChatPanel 组件本身（Agent 详情页仍在使用）
- 不修改 SSE 事件结构（thinking/tool_call/final_answer 等已稳定）

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| 创建 session | POST /sessions {agent_id} | 返回 session 对象，status=active | agent 不存在 → 404 |
| 加载 session 列表 | GET /sessions?agent_id=X | 返回该用户该 Agent 下的 session 列表，按 updated_at 降序 | agent_id 可选，空列表返回空 |
| 发送消息（有 session） | POST /stream {input, session_id} | 复用 thread_id，LLM 可访问历史上下文 | session 不存在 → 404 |
| 发送消息（无 session） | POST /stream {input} | 自动创建新 session，首次消息自动持久化 | - |
| 删除 session | DELETE /sessions/:id | 删除 session + 关联 messages | 非 owner → 403 |
| 首次进入 Agent 详情页 | 无已有 session | ChatPanel 显示空状态，首次发消息自动创建 session | - |
| 返回 Agent 详情页 | 已有 sessions | 显示最近 session 的消息历史 | - |

</frozen-after-approval>

## Code Map

**删除目标：**
- `frontend/src/pages/chat-test-page.tsx` -- 待删除
- `frontend/src/pages/conversations-page.tsx` -- 待删除

**后端新建：**
- `backend/app/models/session.py` -- Session 数据模型（MongoDB collection `sessions`）
- `backend/app/schemas/session.py` -- SessionCreate / SessionResponse / SessionListResponse
- `backend/app/services/session_service.py` -- Session CRUD（create / get / list / delete）
- `backend/app/api/v1/sessions.py` -- REST 端点（POST / GET / DELETE）
- `backend/app/api/v1/router.py` -- 注册 sessions_router

**后端修改：**
- `backend/app/api/v1/agents.py` -- invoke/stream 端点：当 `session_id` 存在时持久化 user message + AI events 到 messages collection；当不存在时自动创建 session 并持久化
- `backend/app/schemas/execution.py` -- 无需修改（session_id 已定义）

**前端新建：**
- `frontend/src/services/session-api.ts` -- Session API 类型定义 + 调用方法 + query key factory

**前端修改：**
- `frontend/src/routes/index.tsx` -- 删除 /chat-test 和 /conversations 路由
- `frontend/src/config/menu.ts` -- 删除聊天测试和对话菜单项
- `frontend/src/components/AppLayout.tsx` -- 更新 PATH_TO_GROUP 映射（删除已移除路径）
- `frontend/src/components/chat-panel.tsx` -- 加载 session 历史、自动创建 session、传递 session_id 到 stream/invoke
- `frontend/src/pages/agent-detail-page.tsx` -- 传入 agentId 对应的 session 信息

## Tasks & Acceptance

**Execution:**

**Phase 1: 删除冗余页面**
- [ ] `frontend/src/pages/chat-test-page.tsx` -- 删除文件
- [ ] `frontend/src/pages/conversations-page.tsx` -- 删除文件
- [ ] `frontend/src/routes/index.tsx` -- 移除 /chat-test 和 /conversations 路由及其 import
- [ ] `frontend/src/config/menu.ts` -- 移除聊天测试和对话菜单项
- [ ] `frontend/src/components/AppLayout.tsx` -- 移除 PATH_TO_GROUP 中已删除路径的映射

**Phase 2: 后端会话管理**
- [ ] `backend/app/models/session.py` -- 新建 Session 模型（id, user_id, agent_id, title, status, message_count, created_at, updated_at）和 Message 模型（id, session_id, role, content, timeline_entries, created_at）
- [ ] `backend/app/schemas/session.py` -- 新建 SessionCreate / SessionResponse / SessionListResponse / MessageResponse schema
- [ ] `backend/app/services/session_service.py` -- 新建 SessionService（create / get / list / delete + message CRUD）
- [ ] `backend/app/api/v1/sessions.py` -- 新建 sessions router：POST /sessions（创建）、GET /sessions（列表）、GET /sessions/:id（详情+消息）、DELETE /sessions/:id（删除）
- [ ] `backend/app/api/v1/router.py` -- 注册 sessions_router
- [ ] `backend/app/api/v1/agents.py` -- invoke/stream 端点：有 session_id 时复用 thread_id 并持久化消息；无 session_id 时自动创建 session；流式完成后更新 session 的 message_count 和 updated_at

**Phase 3: 前端对接**
- [ ] `frontend/src/services/session-api.ts` -- 新建 Session API 服务（类型定义 + CRUD 方法 + query key factory）
- [ ] `frontend/src/components/chat-panel.tsx` -- 新增 sessionId prop；初始化时加载历史消息；发送消息时传递 session_id；首次发送无 session 时先创建 session
- [ ] `frontend/src/pages/agent-detail-page.tsx` -- 查询当前用户+agent 的 sessions，传最新 sessionId 给 ChatPanel；新增 session 切换/新建按钮

**Acceptance Criteria:**
- Given 用户访问 /chat-test 或 /conversations, when 路由不存在, then 显示 404 或重定向到 /agents
- Given 用户在 Agent 详情页发送消息（无已有 session）, when 发送完成, then 后端自动创建 session 并持久化消息
- Given 用户离开 Agent 详情页后返回, when 页面加载, then 显示最近 session 的历史消息
- Given 用户发送消息时传了 session_id, when 后端处理, then LangGraph 使用相同 thread_id 保持上下文连续
- Given 用户点击删除 session, when 确认删除, then session 和关联消息从数据库删除，前端清空聊天区

## Design Notes

### Session + Message 数据模型

采用 **独立 collection** 方案（messages 不嵌入 session），因为：
- 单次 REACT 执行可能产生多条消息（user → thinking → tool_call → tool_result → answer）
- 消息列表会随对话增长，嵌入会导致 session 文档膨胀
- 查询灵活（可按 session_id 查消息列表）

```python
# Session (collection: "sessions")
{
    "_id": "session_01HXXX",
    "user_id": "user_01HTEST",
    "agent_id": "agent_01HTEST",
    "title": "你好，请介绍...",      # 首条消息前 50 字
    "status": "active",
    "message_count": 3,
    "created_at": "2026-06-10T...",
    "updated_at": "2026-06-10T...",
}

# Message (collection: "messages")
{
    "_id": "msg_01HXXX",
    "session_id": "session_01HXXX",
    "role": "user",               # user / agent
    "content": "你好",
    "timeline_entries": [...],     # agent 消息的 timeline (JSON)
    "created_at": "2026-06-10T...",
}
```

### ChatPanel 会话流程

```
1. ChatPanel 挂载，接收 sessionId prop（可能为空）
2. 如果有 sessionId → GET /sessions/:id 加载历史消息
3. 如果无 sessionId → 显示空状态
4. 用户发送消息：
   a. 如果无 sessionId → POST /sessions 创建，获取新 sessionId
   b. POST /stream { input, session_id } → 流式执行
   c. 流式完成后 → 前端追加消息到 state（后端已持久化）
5. 用户切换 session → 清空 state，加载新 session 历史
```

### 上下文连续性

后端 invoke/stream 端点修改点：
```python
# 当 session_id 存在时，复用它作为 thread_id
if body.session_id:
    thread_id = body.session_id
    # 同时持久化 user message
    await SessionService.add_message(session_id=body.session_id, role="user", content=body.input)
else:
    # 自动创建 session
    session = await SessionService.create_session(user_id=user.id, agent_id=agent_id, title=body.input[:50])
    thread_id = session["_id"]

# 流式完成后持久化 AI 消息
await SessionService.add_message(session_id=thread_id, role="agent", content=..., timeline=events)
```

## Verification

**Commands:**
- `cd backend && uv run pytest tests/ --tb=short -q` -- expected: 全部通过
- `cd frontend && npx tsc --noEmit` -- expected: 零错误

**Manual checks:**
- 访问 /chat-test 和 /conversations → 应 404 或跳转
- Agent 详情页发送消息 → 刷新后消息仍在
- 切换 Agent → 不同 session 列表
