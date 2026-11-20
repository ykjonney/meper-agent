# MEPER Agent-Flow 七大规划项 工作进展盘点

- **报告日期**：2026-08-11
- **盘点范围**：Human-in-the-Loop 强化、Token 穿透治理、权限模型深化、多模态输入补全、客户端展示升级、UI/UX 优化、Skills 自学习
- **数据口径**：`dev` 分支当前代码 + `docs/planning-artifacts/`、`docs/implementation-artifacts/` 规划与实现文档
- **用途**：团队内部进度对齐（不含后续实施计划/排期）
- **状态图例**：✅ 已完成 ｜ 🟡 部分完成 ｜ 🔴 未实现 ｜ 📄 仅文档

---

## 一、进展汇总矩阵

| # | 规划项 | 整体状态 | 关键产出 | 主要差距 |
|---|---|---|---|---|
| 1 | Human-in-the-Loop 强化 | 🟡 部分完成 | rewind/重入 + 双轨 checkpoint + 超时扫描 | 节点重试策略未统一、rewind 不穿 Gateway/Parallel |
| 2 | Flow Token 穿透治理 | ✅ 已完成 | MCP 凭证 Broker + interceptor + 全链路穿透 | 无明显出入，规划目标已达成 |
| 3 | 权限模型深化 | 🔴 未实现 | 对象级 RBAC（基线已完成） | 表级/字段级/行级/业务脱敏全未启动 |
| 4 | 多模态输入补全 | 🟡 部分完成 | KB 索引侧全格式解析（Vision+OCR） | **对话侧多模态未做**（不送 Vision） |
| 5 | 客户端展示升级 | 🟡 部分完成 | ECharts + Mermaid + 富文本卡片 + 流式 | 工业场景可视化模板为零；studio 缺图表 |
| 6 | 交互体验 / UI 优化 | 🟡 部分完成 | DESIGN.md 规范 + 编排/配置/审批界面 | **三套前端不统一**是核心矛盾 |
| 7 | Skills 自学习 | 📄 仅文档 | 设计草案 + Skill 上传/注入基线 | 反馈/指标/经验库/自动沉淀全未实现 |

---

## 二、Human-in-the-Loop 能力强化 ｜ 🟡 部分完成

### 规划目标
- 节点 Retry：Agent / Skill / 人工节点可配置重试（次数、退避、终止条件）
- 节点重入（Re-entry）：Flow 在审批或外部事件完成后，可从任意历史节点重新进入并继续
- Checkpoint：保证上下文不丢失，支撑长流程中断/续办

### 实现现状

**节点 Retry ｜ 🟡 部分完成（未统一）**

| 节点类型 | 重试能力 | 配置字段 | 证据 |
|---|---|---|---|
| Agent | ✅ 有 | `max_retry`、`retry_delay_ms`、`timeout_ms` | `backend/app/engine/workflow/node_executor.py:319-321, 393-509` |
| Tool (MCP) | ✅ 有 | `retry_policy.max_retries`、`retry_policy.backoff_ms` | `node_executor.py:856-876` |
| Human | ❌ 无（只有 `timeout_action` 兜底） | — | `backend/app/engine/workflow/nodes/human.py:57-62` |
| Subflow / Gateway / Start / End | ❌ 无 | — | — |

**节点重入 ｜ ✅ 已完成（三条路径）**
- `POST /tasks/{id}/intervene` 支持 7 种 action：`approve / reject / skip / cancel / resume / retry / rewind`（`backend/app/api/v1/tasks.py:177-229`，外部入口 `backend/app/api/v1/ext/tasks.py:157-213`）
- **Resume**：从 checkpoint 续接
- **Retry**：清空运行时数据后从头执行（`backend/app/services/task_service.py:1423-1456`）
- **Rewind（回退到任意历史节点）**：裁掉目标节点及下游子图，原子 `WAITING_HUMAN → RUNNING`，重跑下游（`task_service.py:1010-1235` 的 `rewind_task()`）

**Checkpoint ｜ ✅ 已完成（双轨 + 可靠性保障）**
- **Workflow 级**：`Checkpoint` 模型含 `paused_at_node / completed_nodes / variable_snapshot / human_context / timeout_deadline / agent_thread_id`（`backend/app/models/task.py:66-83`），保存/恢复逻辑在 `engine.py:371-583, 629-667, 806-849`
- **Agent 节点级**：LangGraph MongoDB checkpointer，`thread_id={task_id}_{node_id}`，worker 启动初始化（`backend/app/workers/celery_app.py:74`）
- **超时扫描**：Celery beat 每 30s 扫描（`celery_app.py:57-60` → `backend/app/workers/tasks/human_timeout.py`）
- **启动恢复**：`backend/app/services/task_recovery.py`（超时任务处理 + 僵尸 RUNNING 清理，60s grace）

### 差距与风险
- **重试策略未统一**：Agent 用 `max_retry/retry_delay_ms`，Tool 用 `retry_policy.{max_retries,backoff_ms}`，字段命名不一致
- **退避是固定延迟**，没有指数退避 / jitter；也没有显式的「终止条件」（max_total_time、错误码白名单）
- **Tool 节点前端缺 retry UI**：`ToolNodeConfig.tsx` 只暴露 `timeout_ms`，`retry_policy` 只能通过 API 配
- **Rewind 局限**（代码注释已承认是 V1 non-goal，`task_service.py:965-977`）：`_compute_downstream_nodes` 只遍历 `config.next_nodes`，**不处理 Gateway（`conditions[].target`）/ Parallel（`branches[].start_node`）的路由**，穿过这类节点的下游会漏裁；且 rewind 仅支持 `waiting_human` 状态，不能从 failed/cancelled 回退

### 参考文档
- `docs/implementation-artifacts/spec-human-node-approval.md`
- `docs/implementation-artifacts/4-10-human-in-the-loop.md`

---

## 三、Flow 跨系统调用与 Token 穿透治理 ｜ ✅ 已完成

### 规划目标
- 所有跨系统认证凭证由 MEPER 统一托管，Flow 仅声明"调用目标"，不持明文 Token
- 通过 MCP Platform 提供标准化的"模型 ↔ 外部系统"通路

### 实现现状（最新落地，commit `71fe31c`）

**MCP Platform ｜ ✅**
- 连接管理：CRUD / test / discover（`backend/app/api/v1/mcp.py`、`backend/app/services/mcp_connection_service.py`）
- 模型：`backend/app/models/mcp_connection.py`（streamable-http/sse、none/api_key/bearer/basic 鉴权、`default_params`、`login_config`）
- 工具加载：`backend/packages/harness/.../mcp/loader.py` 的 `McpToolLoader`，`mcp__{server}__{tool}` 前缀 + TTL 5min 缓存；缓存层 `backend/app/engine/tool/mcp_tool_cache.py`

**统一鉴权层（凭证平台托管）｜ ✅**
- 凭证存储：`backend/app/services/mcp_token_credential_service.py`，集合 `mcp_token_credentials`，**AES-256-GCM 加密**（`enc:` 前缀），支持 token 型直接返回 + 账密型 Redis session 缓存（按 `login_config` 换 session）
- 凭证兑换：`backend/app/engine/mcp/user_credential_resolver.py` 实现 harness 的 `CredentialResolver` Protocol（`server_name → mcp_connection_id → 绑定凭证 → 解密 → 按 auth_type 兑换`）
- 拦截器注入：`loader.py:233-271` 的 `_user_token_interceptor`，从 ContextVar 动态读 `token_record_id`，兑换失败返回 `isError` CallToolResult（不抛异常）
- 启动注入：`backend/app/main.py:38-42` `set_credential_resolver(UserCredentialResolver())`，harness 保持无 DB 依赖

**Token 穿透全链路 ｜ ✅**
1. 入口：`backend/app/core/auth_apikey.py:117-183` 校验 `Authorization: Bearer af_live_xxx`（API Key）+ `X-User-Token: meper_xxx`（必填，本地查 active 记录）
2. 触发：`backend/app/api/v1/ext/workflows.py:155-164` 把 `ext_user_token` 透传到 Task 文档
3. 执行：`engine.py:246-249` 注入 VariablePool `system.user_token`
4. 节点：`node_executor.py:238-239, 826-829` 取 user_token → `set_token_record_id_context()` 设 ContextVar
5. MCP：interceptor 读 ContextVar → resolver 兑换 → 注入 header
6. 清理：`finally` 块 `reset_token_record_id_context()`（`node_executor.py:892-894`）

**MCP Token 管理 API ｜ ✅**
- `backend/app/api/v1/mcp_tokens.py`（admin only）：create / list / get / update / delete / **rotate** / **reveal**
- 模型：`backend/app/models/mcp_token_credential.py`（`TOKEN_PREFIX = "meper_"`、status active/disabled）
- 设计要点：原始 user_token 只在 ContextVar 生命周期（单次请求）内存在，不写 Redis / 不入日志 / 不入库；绑定凭证是加密入库

### 差距与风险
- 与规划**基本无出入**，"凭证托管 + Flow 只声明调用目标"的立场已达成
- 当前未见独立部署的 "MCP Platform" 服务，而是 MEPER 内的 MCP 管理模块——如未来要解耦为独立平台需评估

### 参考文档
- `docs/planning-artifacts/mcp-credential-broker-design.md`（含架构图、立场转变对照表、流程图）
- `docs/planning-artifacts/external-user-auth-design.v0.3.archived.md`（旧回调模式已废弃）

---

## 四、权限模型深化：表与字段级约束 ｜ 🔴 未实现

### 规划目标
- 从"对象级"（Agent / Flow / 知识库）扩展到**表级与字段级**
- 支持数据脱敏、行级访问控制、字段读写控制

### 实现现状

**对象级 RBAC（基线，✅ 已完成）**
- 手写 RBAC：角色 + 权限点两层，全代码库 **102 处** Depends 装饰器使用
  - `backend/app/core/security.py`（JWT + `require_permission/require_role/require_any_role`）
  - `backend/app/services/role_service.py`（角色 CRUD + Redis 缓存 `role:perms:{name}` TTL 1h）
  - `backend/app/models/role.py`（`permissions: list[str]`，权限点为 `<resource>:<action>` 形态，如 `agent:read/write/invoke`）
  - 4 个系统角色（admin/developer/operator/viewer）+ 自定义角色
- 外部 API 额外一层对象级：`backend/app/core/auth_apikey.py` 的 `ApiKeyPrincipal.can_access_agent/can_access_workflow`，基于 `ApiKey.bindings` 白名单

**表级 / 字段级 / 行级 / 业务数据脱敏（全部 🔴 未实现）**
- 全量 grep `field_level / column_level / table_level / row_level / field_perm / row_perm / column_perm` 在 `backend/app/services/` **零命中**
- 数据模型层无任何"字段/行权限"字段，无"按角色投影字段"能力
- 服务层无 `filter_by_role / project_fields / exclude_field` 逻辑
- **业务数据脱敏不存在**：现有 mask 全是凭证展示脱敏（`backend/app/core/crypto.py:145 mask_api_key`、`mcp_token_credential_service._MASK_FIELDS`、`channel_service.mask_credentials` 等），与"按角色脱敏业务字段"是两回事
- **行级仅硬编码 owner 过滤**：模型普遍带 `owner_user_id/created_by`，查询时硬编码校验（`files.py:35`、`sessions.py:366`），无 RLS 策略引擎、无 policy/acl 表、无租户/部门维度
- 审计日志 `backend/app/models/audit_log.py` 只记录 Task 状态变更/干预，无数据访问审计

### 差距与风险
- 与计划**无出入**：PRD（`prd.md §795`）明确写"MVP 不做细粒度资源权限"，此项是 post-MVP 方向，尚未启动
- 架构决策（`docs/planning-artifacts/architecture.md` Decision 2.3）选了"手写 RBAC 装饰器"，未来深化需要引入策略引擎/字段投影机制，是较大的架构改造

---

## 五、多模态输入补全 ｜ 🟡 部分完成（K 型分裂）

### 规划目标
- 支持文件、图片、PPT、PDF、Excel 等格式识别与解析
- 终端客户端打通"上传即用"
- 与现有知识库 RAG 检索打通，上传内容作为会话级上下文

### 实现现状

**KB 索引侧（RAG 管线）｜ ✅ 已完成且相当完整**
- 解析器全套（`backend/app/engine/kb/vector/parser/`）：`pdf_parser`（PyMuPDF 逐页 + `parse_pdf_with_images` 扫描页）、`word_parser`（docx 结构化）、`xlsx_parser`、`pptx_parser`、`csv/markdown/html/txt_parser`
- **图片识别双引擎**（`image_extractor.py`）：优先 Vision LLM（构造 `HumanMessage(content=[{type:text},{type:image_url}]`）→ 回退 RapidOCR（`ocr_engine.py`，PaddleOCR/ONNX）→ 跳过
- 抽取图片存 FileRef，chunk 带 `image_ref_ids`
- Celery 索引任务：`backend/app/workers/tasks/kb_indexing.py`（load → parse → clean → chunk → embed → Qdrant upsert）
- RAG 检索：`retriever.py`（Qdrant dense+sparse/BM25 混合 + RRF + 可选 rerank + 阈值），通过 `kb_search` 工具注入 Agent（`search_manager.py` + `builder.py:146-148`）
- 配置：`backend/app/core/config.py:160-203`（`KB_VISION_*` / `KB_OCR_*` / `KB_EMBEDDING_*` / `KB_RERANKER_*`，全部可选，未配置时优雅降级）

**对话侧（Agent 直接看上传内容）｜ 🔴 未实现（关键缺口）**
- 文件上传链路已完成：`backend/app/api/v1/sessions.py:269 upload_chat_file`（白名单含图片/PDF/Office，50MB 上限）、`files.py`、`ext/files.py`、`file_service.py`（sha256 去重 + FileUsage 引用计数）
- **但非文本文件不会被解析或送给 Vision**：`backend/app/services/file_rendering.py`
  - `_is_text_mime()` 判定文本；非文本（图片/PDF/Office）走 `content=None` + `unavailable_reason="binary file"`，只是 XML 占位标签
  - 截断上限 `_MAX_ATTACHMENT_CHARS = 50_000`
- **对话消息不构造多模态 content**：`agent_execution_service.py:342-358 _build_user_content` 把附件块**拼成纯文本字符串**塞进 user message，没有 `content=[{type:text},{type:image_url}]` 结构
- 即：**图片/PDF 在对话里只是占位，模型看不到内容**

### 差距与风险 ｜ ⚠️ 与原判断有出入
- 原判断"多模态没做"——实际 **KB 索引侧（含 OCR/Vision/RAG）已完整**，真正没做的是"**对话侧上传图片/PDF 给 Agent 直接看**"
- 补全路径清晰：在 `file_rendering.py` / `_build_user_content` 里对图片/PDF 构造多模态 message（写法可参考 `image_extractor.py:208-213` 已有的 data-URL 写法），并让 builder 选用 Vision-capable 模型
- 前端 workflow 文件上传 UI 已落地（`docs/file-input-enhancement.md`）

---

## 六、客户端（Client）展示能力升级 ｜ 🟡 部分完成

### 规划目标
- 新增图表、表格、富文本卡片等多种展示形态
- 工业场景专用可视化模板（OEE 趋势、异常清单、工单状态）
- 客户端本身开发能力提升（响应速度、交互体验、可访问性）

### 实现现状

> 前置事实：项目有三套前端。**线上** = `frontend-studio/`（管理后台，Tailwind 手写）+ `frontend-client/`（终端客户端，AntD + ECharts）；`frontend/`（在建未上线，AntD + DESIGN.md 规范）。`deploy/Dockerfile.caddy` 只构建 studio + client。

**已完成（集中在 `frontend-client/`）**
- **图表（ECharts）**：`frontend-client/src/components/ChartBlock.tsx`（echarts 6 + echarts-for-react，Bar/Line/Pie/Scatter，JSON 流式补全容错、1MB 上限、暗色适配），渲染入口 `MessageContent.tsx:78` 识别 `language-echarts/chart` 围栏
- **Mermaid**：`MessageContent.tsx:85` 用 `@ant-design/x <Mermaid>`
- **表格 / GFM 富文本**：`react-markdown` + `remark-gfm`，table 包横向滚动
- **交互式卡片**：`WorkflowConfirmAnsweredCard` / `ClarificationAnsweredCard` / `ToolRunsGroup`（工具调用 timeline 聚合）/ `WorkflowTaskCard` / 附件卡片（图片预览 + 下载）
- **流式输出**：`frontend-client/src/hooks/use-chat.ts`（817 行）+ `ChatView.tsx`（563 行），完整 SSE 流式（text/thinking/tool_call/tool_result/interrupt）、贴底自动滚动、首 token 前"正在响应"动效，对照 `docs/implementation-artifacts/spec-chat-streaming-thinking.md`（approved）已达标

**未实现 ｜ 🔴**
- **工业场景专用可视化模板完全为零**：全仓 grep `OEE / 异常清单 / 工单状态 / anomaly / industry template` 零命中（仅 `frontend/src/pages/design-reference-page.tsx` mock 数据一处无关提及）
- `ChartBlock` 是通用 echarts option 透传，无按业务语义封装的预制模板
- 另：**`render_chart` 工具后端未实现**（`grep -rni render_chart backend/` 零命中），图表目前只能靠 LLM 在 markdown 里直接写 echarts option，"前端有能力、后端无标准产出工具"

**一致性缺口 ｜ 🟡**
- `frontend-studio/src/components/Markdown.tsx` 仅 `rehype-highlight`，**完全没有图表 / Mermaid**，落后于 client；线上管理后台自带对话页展示形态比客户端弱

---

## 七、交互体验与 UI 整体优化 ｜ 🟡 部分完成

### 规划目标
- 管理后台与终端客户端的界面一致性、信息密度、操作链路整体梳理
- 打磨关键节点（Flow 编排、Agent 配置、审批操作）细节体验

### 实现现状

**设计系统 ｜ ✅**
- 规范文档：`docs/planning-artifacts/ux-designs/ux-agent-flow-2026-06-08/DESIGN.md`（`status: final`，"Professional · Engineering · Restrained"，Indigo `#4F46E5` + Slate surface ladder + 深色侧边栏，DM Sans / JetBrains Mono，8px spacing）+ `EXPERIENCE.md`（UX-DR1～25 交互模式）
- `frontend/`（在建）实现最完整：`ThemeContext.tsx`（6 套主题切换）、`tailwind.config.ts`（语义化 token：txt/canvas/surface/line + primary/accent/...）、`design-system-page.tsx` / `design-reference-page.tsx`（实时预览 + 与 DESIGN.md 对齐的活样本）、`routes/index.tsx`（22 页接入 AppLayout）、`config/menu.ts`（Dify 风格分组菜单）

**关键界面 ｜ ✅**
- Flow 编排：`frontend-studio/src/features/workflow-editor/`（@xyflow/react 完整 DAG 编辑器：Canvas/Palette/ConfigPanel/InputForm/TaskTraceModal/VariableChip/HumanNodeConfig 等）；`frontend/` 内有在建版本
- Agent 配置：`AgentEditorPage.tsx` / `AgentDetailPage.tsx` / `AvatarField`；`frontend/` 内 `agent-form-drawer.tsx` 等在建
- 审批 / HITL：`frontend/src/components/approval-view/ApprovalView.tsx` + `resolveVar.ts`（`{{node.field}}` 模板渲染）、`HumanNodeConfig.tsx`（含单测）、看板审批入口（waiting_human 快捷通过/驳回 + comment）；客户端侧 `clarification-form-card.tsx` + `MessageContent` 内的 answered card

### 差距与风险 ｜ ⚠️ 核心矛盾：三套前端不统一
- **studio**（线上管理后台）= Tailwind v4 手写暗色，**无 UI 组件库、无图表库**，UI 元素都是 `<div className="bg-[#18181b]...">` 硬编码
- **client**（线上客户端）= AntD 6 + @ant-design/x，走 AntD 默认主题
- **frontend**（在建未上线）= Tailwind token + AntD 6 + DESIGN.md 规范，是"目标统一"的实现，但 `Dockerfile.caddy` **未部署它**
- 三套前端三套实现，颜色/组件/暗色策略全不一致；`frontend/` 的存在本身就是为了对齐 DESIGN.md，但还没替换 studio 上线
- 信息密度、操作链路的系统性梳理：DESIGN.md / EXPERIENCE.md 已有规范，但落地到线上（studio）尚有差距

---

## 八、Skills 自学习与可持续演进 ｜ 📄 仅文档

### 规划目标
- 允许用户自定义 / 总结新 Skill
- 通过调用频次、采纳率、纠错率等指标反哺 Skills 库
- 高频稳定实践自动沉淀为团队共享 Skills，平台具备自学习、自演进能力

### 实现现状

**设计文档 ｜ 📄**
- `docs/planning-artifacts/agent-self-learning-design.md`（696 行，**状态：草案（Draft）**，2026-08-11）
  - 现状诊断：明确当前是"无状态、无记忆、无反馈的纯 REACT 执行器"，`Message` 无 feedback 字段、`ExecutionLog` 无质量字段、无反思节点、无经验库、无 run-end 回调（诊断与代码一致）
  - 4 层递进：L1 反馈闭环+经验记忆 MVP / L2 在线反思+自动技能 / L3 离线演化 / L4 RLHF（非目标）
  - 数据模型扩展：`Message.feedback`、`Agent.experience_*`、`ExecutionLog.outcome_quality`、新增 `experience_proposals` 集合
  - 关键机制：反馈采集（👍👎 + 纠正表单 + 管理员评审 + 工具隐式信号）、经验沉淀（复用 vector KB）、`ExperienceMiddleware`（before_llm few-shot 注入）、反思节点、自动技能蒸馏、提案式回写
  - 文档质量高，但 **状态明确是"草案"，对应代码改动一行都还没有**

**Skill 基线能力 ｜ ✅ 已完成**
- 用户自定义 Skill 上传/编辑：`backend/app/models/tool.py`（统一 Tool 模型，`source` 区分 markdown/mcp/openapi/code/prebuilt，`files: list[SkillFile]` 支持目录包）
- Skill 声明式注入 Agent：`backend/app/engine/agent/builder.py`（`skill` 工具 + `_build_skill_declaration()` 注入 system prompt）；规范 `docs/implementation-artifacts/spec-skill-injection-into-agent.md`（`status: done`）
- 前端管理：`frontend-studio/src/components/SkillsStore.tsx`（技能商店，注释明说"rating/isAdded/isPaid 是前端 client-side map，后端无字段"）、`frontend/src/pages/skills-page.tsx` + `skill-detail-page.tsx`（文件树 + 编辑器双栏）

**自学习 / 指标反哺 / 自动沉淀 ｜ 🔴 全部未实现**
- backend grep `feedback / thumbs_up / thumbs_down / adoption / acceptance_rate / experience_proposal / self_learning / lesson` **零命中**
- `Message` 无 feedback 字段、`Agent` 无 experience_* 配置、`ExecutionLog` 无 outcome_quality
- 无 `experience_proposals` 集合 / `ExperienceMiddleware` / post_run_hooks / 反思 worker / 技能蒸馏 worker
- `Tool` 模型无任何调用统计 / 采纳率 / team / scope 字段，无团队共享/私有区分机制
- 前端无 experience 评审页（设计文档规划的 `/experience/review`）

### 差距与风险
- 自学习完整链路（反馈 → 经验 → 反思 → 蒸馏 → 共享）**完全在文档阶段**，未启动编码
- 已落地的"用户自定义 Skill"是被动上传，不含"自学习/自演进"语义

---

## 九、一致性说明与需重点决策的"计划出入"

盘点过程中识别出三处与原始规划表述存在**认知偏差或需重点决策**的点：

1. **HITL 重试策略未统一**
   原规划把 Retry 作为统一能力描述，实际实现里 Agent / Tool 的重试字段命名、退避策略各做各的，Human 节点完全无重试。是否抽出统一 `RetryPolicy`、是否引入指数退避/jitter/终止条件，需决策。

2. **多模态"没做"是误判 ｜ 真正缺口在对话侧**
   原判断"多模态输入补全没做"不准确：**KB 索引侧（PDF/Word/Excel/PPT/图片 + Vision/OCR + RAG）已完整**。真正未做的是"**对话侧上传图片/PDF 给 Agent 直接看**"（当前只渲染成 XML 占位，不送 Vision、不构造多模态 content）。补全这一半即可达成"上传即用"全链路。

3. **UI 一致性的核心矛盾是"三套前端不统一"**
   原规划只提"一致性优化"，但实际现状是 studio（Tailwind 手写）/ client（AntD）/ frontend（Tailwind token + AntD + DESIGN.md，**在建未上线**）三套并存。是否推进 `frontend/` 替换 `frontend-studio/` 上线，是 UI 治理的前置决策。

---

## 十、复盘口径（关键证据索引）

便于团队复核，以下为本报告结论所依据的关键文件：

- **HITL / 引擎**：`backend/app/engine/workflow/engine.py`、`node_executor.py`、`nodes/human.py`、`backend/app/services/task_service.py`、`task_recovery.py`、`backend/app/workers/tasks/human_timeout.py`、`backend/app/models/task.py:66-83`
- **MCP / Token**：`backend/app/api/v1/mcp.py`、`mcp_tokens.py`、`backend/app/services/mcp_connection_service.py`、`mcp_token_credential_service.py`、`backend/app/engine/mcp/user_credential_resolver.py`、`backend/packages/harness/src/agent_flow_harness/mcp/loader.py`、`user_token_context.py`、`backend/app/core/auth_apikey.py`、`backend/app/api/v1/ext/workflows.py`
- **权限**：`backend/app/core/security.py`、`backend/app/services/role_service.py`、`backend/app/models/role.py`、`backend/app/core/auth_apikey.py`、`backend/app/core/crypto.py`
- **多模态**：`backend/app/engine/kb/vector/parser/`（全格式）、`image_extractor.py`、`ocr_engine.py`、`factory.py`、`retriever.py`、`search_manager.py`、`backend/app/services/file_rendering.py`（对话侧缺口）、`agent_execution_service.py:342-358`（对话侧缺口）、`backend/app/api/v1/sessions.py:269`
- **客户端展示**：`frontend-client/src/components/ChartBlock.tsx`、`MessageContent.tsx`、`ChatView.tsx`、`hooks/use-chat.ts`、`frontend-studio/src/components/Markdown.tsx`（对比缺口）
- **UI/UX**：`docs/planning-artifacts/ux-designs/ux-agent-flow-2026-06-08/DESIGN.md`、`frontend/src/contexts/ThemeContext.tsx`、`frontend/tailwind.config.ts`、`frontend/src/features/workflow-editor/`、`frontend/src/components/approval-view/`、`deploy/Dockerfile.caddy`（部署范围）
- **Skills 自学习**：`docs/planning-artifacts/agent-self-learning-design.md`（草案）、`backend/app/models/tool.py`、`backend/app/engine/agent/builder.py`、`docs/implementation-artifacts/spec-skill-injection-into-agent.md`（done）、`frontend-studio/src/components/SkillsStore.tsx`
