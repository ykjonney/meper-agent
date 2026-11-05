# Backend Gaps — Studio v2 重设计过程中发现的后端缺口

> 规则：前端 v1 不等后端 — 缺什么就在这里记录，前端先做占位/降级展示；
> 后端补上后去掉对应条目前置的 ⏳。

## ⏳ 待后端支持

| # | 页面 | 缺口 | 前端 v1 处理 | 建议后端方案 |
|---|------|------|-------------|-------------|
| G1 | 首页 | 「失败原因 Top」需要按稳定错误码聚合的统计接口 | 空态占位「暂无失败数据」 | `GET /api/stats/failures?range=` 聚合 execution 错误码 |
| G2 | 首页 | Token 消耗/费用估算的聚合接口 | 显示「—」 | request 级事件流已有 token 数，缺 range 聚合 + 单价换算 |
| G3 | 对话 | 上下文水位（当前会话 token 数 / 上限 / 压缩状态）SSE 或轮询接口 | Composer 水位条隐藏 | session 级 usage 快照接口或 SSE 周期事件 |
| G4 | 对话 | 会话内切换模式（计划/深度思考/联网）的运行时开关 API | 仅计划模式开关可存（复用现有字段），其余置灰 | agent 或 session 级 overrides 字段 |
| G5 | 任务 | 看板「排队中」列：任务排队位置/预计等待 | 只显示排队状态不显示位次 | 队列 depth 元数据 |
| G6 | 智能体 | 卡片运营统计（本月运行次数/成功率/费用）聚合接口 | 卡片隐藏统计行 | 按 agent 聚合 executions |
| G7 | 知识库 | 分片级「被引次数」、库级「被 N 个 Agent 挂载」反向引用 | 隐藏该字段 | agent 配置反向索引 |
| G8 | 工具生态 | MCP 连接实时状态灯 | 静态「已接入」 | MCP server healthcheck |
| G9 | 管理 | 模型渠道熔断状态灯 | 只显示启用/禁用 | channel 熔断分级状态已有后端逻辑，缺查询接口 |
| G10 | 对话/任务 | 会话级执行状态（列表「运行中」状态点、进行中分组） | 按时间分组，无状态点 | session 绑定 running execution 状态查询 |
| G11 | 对话 | 工具执行实时 stdout 流（活动组直播终端） | running 态显示 args 摘要，无实时输出 | tool_call SSE 事件附带 chunk 流或轮询沙盒日志 |
| G13 | 对话 | 会话重命名接口（PATCH /sessions/:id title） | 侧栏无重命名入口 | 后端补 PATCH；前端随做随接 |
| G12 | 对话 | timeline 条目级时间（「思考过程 · 8s」的权威耗时） | 前端本地计时（仅当轮流式有效，历史回放无） | timeline_entries 加 started_at / duration_ms 字段并随 SSE/done 下发 |

## ✅ 已确认后端支持（无需处理）

- 会话/消息/Agent/工作流/任务/定时/知识库/工具/技能/MCP/用户/权限 — v1 已有
- 执行过程 SSE（thinking/tool_call/tool_result/interrupt）— v1 已有
- 工具输出回溯（recall_tool_result）— v1 已有
- 计划模式（propose_plan 审批流）— v1 已有
