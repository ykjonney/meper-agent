# Artifact & Workspace 现有代码差距审查

> 对照文档：`docs/product-design/artifact-workspace-design.md`
>
> 审查分支：`feature/execution-model`
>
> 状态：**Initial Code Audit（初步代码审查，非完整实现审计）**
>
> 日期：2026-11-27
>
> 本文基于当前分支关键文件的读取结果。未逐一检查所有 API、前端组件、索引、迁移脚本和测试，因此结论用于确定下一轮审查和实施顺序，不应视为完整代码清单。

## 1. 总体结论

当前代码已经有可复用的文件存储和文件引用基础，但 Workspace 和 File Library 仍是两套体系，且 Workspace 仍主要以 Session 为目录身份。距离目标模型的主要差距不是缺少一个文件表，而是缺少统一的 Workspace 身份、Workspace 与 Conversation 的 Binding、文件内容版本和 Workspace Revision。

建议采取渐进演进，不推倒重来：

- 保留现有 FileStorage 抽象并扩展其能力。
- 评估 FileRef 演进为 Artifact 的路径，优先复用现有 ID、元数据和 FileUsage。
- 保留 WorkspaceLayout / CloudLayout / LocalLayout 的环境策略职责。
- 新增持久化 Workspace 元数据和 Binding。
- 将当前 Session Workspace 作为迁移来源与兼容层，逐步切换到 Workspace ID。
- 不在第一阶段实现复杂 ACL、跨 Workspace Reference 或内容血缘。

## 2. 现状与差距

### 2.1 Workspace 仍是 Session 级目录

相关文件：
- `backend/app/engine/tool/workspace.py`
- `backend/app/services/session_service.py`
- `docs/workspace.md`

现状：
- Cloud Workspace 路径为 `{WORKSPACES_ROOT}/{user_id}/{session_id}/`，包含 input、output、tmp。
- WorkspaceManager 的核心 API 是 get/create/delete_session_workspace 风格，目录路径从 user_id 和 session_id 推导。
- Local 模式通过 Session.local_dir 接入用户指定目录。
- 同一个 Session 多轮执行复用该目录。

差距：
- 目标 Workspace 是独立持久化资源，不能以 Session ID 作为身份。
- 目前缺少 Global Workspace / Project Workspace 的正式持久化记录。
- 缺少 Conversation 到 Primary / Additional Workspace 的正式 Binding。
- Session 生命周期和 Workspace 生命周期仍有耦合风险。

建议：
- 新增 Workspace 元数据模型与 Workspace ID。
- 新增 WorkspaceBinding（Conversation、Workspace、Primary/Additional 等必要字段）。
- Session 创建时不再创建新的持久化 Workspace，而是解析或创建默认 Workspace Binding。
- 迁移期间保留旧路径解析，先将旧 Session Workspace 纳入迁移映射，再逐步切换。
- Local Workspace 应作为 Workspace Backend / Placement 的一种接入方式评估，不应继续只靠 Session.local_dir 表达长期身份。

### 2.2 FileRef / FileUsage 已具备一等文件和引用基础

相关文件：
- `backend/app/models/file_library.py`
- `backend/app/services/file_service.py`

现状：
- FileRef 有稳定 ID、owner_user_id、storage_key、name、size、mime_type、sha256、origin 和 status。
- FileUsage 记录 FileRef 被消息、Workflow、定时任务、知识库等消费者引用。
- FileService 提供创建、读取、按 Owner 查询、软删除/强制删除和 Usage 管理。
- FileRef 的设计本身独立于 Session / Workflow 消费者。

可复用：
- FileRef 是 Artifact 的重要迁移基础，尤其是稳定文件 ID、元数据、来源和内容 Hash。
- FileUsage 可以继续表达消息附件、知识库等业务引用，但不应直接等同于 Workspace Entry 或 Work Result。

差距：
- FileRef 目前没有 workspace_id 和路径作为 Workspace 内身份。
- 没有 Artifact Version 历史；当前 FileRef 代表一个当前文件内容对象。
- FileUsage 是消费者引用，不表达 Workspace 的目录结构、当前 Revision 或文件变更历史。
- 强制删除会级联删除 Usage 和物理文件，需要与未来版本/Blob 引用保护机制协调。

建议：
- 不要另起一套与 FileRef 完全无关的 Artifact 文件表。
- 设计迁移方案，将 FileRef 平滑演进为 Artifact 元数据，或让 Artifact 在初期包装/引用 FileRef；选择前需检查所有调用方和 API 契约。
- Workspace Entry 应是独立的路径记录，不能把 FileUsage 直接改名当 Entry。
- 引入 ArtifactVersion 后，当前 FileRef 的 storage_key / sha256 可以成为初始版本的内容定位信息。
- 物理 Blob 删除必须改为引用计数/可达性检查或等价安全机制，不能简单按单个 FileRef 强删。

### 2.3 FileStorage 已有抽象，但能力偏单文件 CRUD

相关文件：
- `backend/app/services/file_storage.py`

现状：
- FileStorage 抽象 save/load/delete/exists/get_size。
- LocalFileStorage 使用安全路径解析，复用 WorkspaceManager 的工作区根目录。
- 当前实现以 storage_key 定位文件，适合做第一阶段 Local Backend。

可复用：
- Storage Provider 的基本抽象已经存在。
- LocalFileStorage 可作为 MVP 的初始 Provider。

差距：
- 没有显式 Blob / Content Addressed Storage 接口。
- save 当前是按 key 写入单份内容，尚无不可变 Blob 语义。
- 缺少原子提交、临时写入后发布、Blob 元数据/校验等 Revision 提交所需能力。

建议：
- 保留 FileStorage 接口并逐步演进，不要再建立平行的 Storage Provider。
- 第一阶段可先实现不可变版本对象的存储 key；内容寻址去重可以作为后续优化，不必阻塞统一 Artifact。
- 后续补充原子写入/校验与 Blob 生命周期管理。

### 2.4 input / output / tmp 是执行环境布局，不应继续成为三种文件实体

相关文件：
- `backend/app/engine/tool/workspace.py`
- `docs/workspace.md`

现状：
- CloudLayout 使用 input（只读附件）、output（产物）、tmp（工作目录）三种目录角色。
- LocalLayout 是用户指定 root 的本地目录树。
- WorkspaceLayout 负责路径解析、角色校验和环境描述；Sandbox 负责执行。

判断：
- 这些目录是当前 Agent 执行环境的路径/安全策略，不应因此产生三种不同 Artifact 类型。
- 统一 Artifact 后，文件仍可记录在 Workspace 的普通目录树中；工具可继续按路径和策略限制访问。

建议：
- 保留 Layout 的环境描述和路径安全职责。
- 逐步弱化 output-only 写入规则，改为明确的 Workspace 路径写权限策略；但需要结合现有 Prompt、工具和 Sandbox 测试迁移，不能直接删除旧规则。
- input 附件的只读约束可作为文件/路径访问策略继续保留，不要求独立文件实体。

### 2.5 Session 删除目前承担 Workspace 清理职责

相关文件：
- `backend/app/services/session_service.py`

现状：
- Session 创建时（非 local 模式）自动创建 Session Workspace。
- Session 删除路径包含 Workspace 清理逻辑（应继续检查完整函数与关联调用，确认所有清理分支和失败策略）。

差距：
- 目标要求 Workspace 生命周期独立于 Session。
- 直接移除清理可能造成旧 Session Workspace 孤儿目录；继续级联删除又会违反新生命周期。

建议：
- 新旧 Workspace 分阶段兼容。
- 对新 Workspace Binding，删除 Session 只解除 Binding，不删除 Workspace。
- 旧 Session Workspace 在迁移完成前按旧策略或明确的保留策略处理。
- 数据迁移必须先建立 Workspace 元数据与 Session 目录映射，并验证文件清单和内容 Hash，再切换读取路径。
- 不要在同一个发布步骤中同时改目录身份、删除逻辑和存储布局。

### 2.6 Execution ResourceBinding 已有资源关联机制，但缺少 Workspace Revision 语义

相关文件：
- `backend/app/engine/execution/models.py`

现状：
- Execution 有 ResourceBinding，resource_type 可为 workspace，包含 resource_id、provider、provider_resource_id、fencing_token 和 lifecycle_state。
- 这是 Execution 与 Workspace 资源显式关联的良好基础。

差距：
- Execution 模型本身没有明确的 workspace_id / workspace_revision_id 快照字段。
- ResourceBinding 目前描述资源绑定和生命周期，不表达本次执行基于哪个 Workspace Revision 读取、提交到哪个 Revision。

建议：
- ResourceBinding 继续负责 Execution 与 Workspace Runtime/Provider 资源关联。
- 在需要时为 Workspace 使用上下文补充 workspace_id、base_revision_id、committed_revision_id 等信息；具体放在 ResourceBinding metadata、Execution context 还是独立 WorkspaceExecutionBinding，应在实现设计时选最小方案。
- 保留 fencing 机制，避免再造一套执行租约系统。

## 3. 建议复用与新增清单

| 领域 | 现有基础 | 建议 |
|---|---|---|
| 文件实体 | FileRef | 演进/兼容为 Artifact，不平行重建 |
| 文件业务引用 | FileUsage | 保留，用于消费者引用 |
| 存储抽象 | FileStorage / LocalFileStorage | 复用并扩展不可变版本/Blob 能力 |
| Workspace 路径策略 | WorkspaceLayout / CloudLayout / LocalLayout | 保留 |
| Workspace 身份 | 目前主要由路径推导 | 新增 Workspace 元数据和稳定 ID |
| Conversation 绑定 | Session ID 隐式决定目录 | 新增 WorkspaceBinding |
| 目录项 | 当前文件路径存在于物理目录 | 新增 Workspace Entry 元数据/Revision 清单 |
| 文件版本 | FileRef 当前内容 | 新增 ArtifactVersion |
| Workspace 快照 | snapshot 仍为预留 | 实现 WorkspaceRevision |
| 文件变更 | 部分文件操作和日志 | 新增统一 Change 事实记录 |
| Work 成果 | 尚需核实 Work 数据模型与文件调用 | 新增 Work-Artifact 关联 |
| Execution 资源 | ResourceBinding | 复用，补充 Revision 关联上下文 |

## 4. 推荐实施顺序

### Phase 0：补齐代码审查

在写迁移代码前，还需要检查：
- 所有 FileService / FileRef / FileUsage 调用点和 API。
- 上传、下载、消息附件、Workflow 输出和知识库导入路径。
- Workspace 创建、删除、扫描、读写、Sandbox bind mount 的所有调用点。
- Work 领域模型及 Work Result 的现有实现。
- 当前 MongoDB 索引和数据迁移/回填方式。
- 对应前后端文件列表、下载和结果展示页面。

### Phase 1：建立 Workspace 身份，不改变现有文件读写行为

- 新增 Workspace 元数据。
- 新增 WorkspaceBinding。
- Global Workspace / Project Workspace 创建和解析。
- Session 通过 Binding 获取 Workspace。
- 旧 Session Workspace 仍可兼容运行。

### Phase 2：统一 Artifact 与 Workspace Entry

- 确认 FileRef 到 Artifact 的兼容方案。
- 建立 Workspace Entry（路径、Artifact、当前 Version）。
- 让 Workspace Explorer 与 File Library 逐步读取统一模型。
- 旧 input/output/tmp 目录先通过适配层接入，不立即改变物理布局。

### Phase 3：版本、Revision 与 Change

- 新增 ArtifactVersion。
- 新增 WorkspaceRevision。
- 建立统一文件变更提交通道。
- 实现冲突检测、历史版本和回收站。
- 再逐步引入内容寻址和 Blob 去重。

### Phase 4：Work 与用户体验

- Work-Artifact 交付关联。
- Agent 声明成果协议。
- Work Results、Change Viewer、Artifact Library。
- 完成 Session 删除只解绑、不删除正式 Workspace 的行为切换。

## 5. 风险与注意事项

1. **双系统并存风险**：迁移期间 FileRef、Workspace 物理文件和 Artifact Entry 可能短期并存，必须定义唯一事实来源和回填校验。
2. **数据丢失风险**：Session 删除逻辑和文件强制删除必须在版本/Blob 引用保护到位前保持谨慎。
3. **路径语义风险**：CloudLayout 的 input/output/tmp 权限规则已注入 Agent Prompt，改变前必须更新工具行为、Prompt 和测试。
4. **本地 Workspace 风险**：LocalLayout 直接操作用户指定目录，不能未经安全审查就纳入与托管 Workspace 相同的写入/版本流程。
5. **并发风险**：当前文件锁和执行 fencing 各有职责，Workspace Revision CAS 不能仅依赖进程内锁。
6. **范围膨胀风险**：不要把跨 Workspace Reference、复杂 ACL、实时协同编辑或完整企业内容治理带入本轮实现。

## 6. 初步审查结论

当前最重要的架构缺口按优先级排列：

1. Workspace 从 Session 级目录身份转为独立持久化资源。
2. 建立 Conversation 与 Workspace 的显式 Binding。
3. 统一 FileRef / Workspace 物理文件为 Artifact 视图和引用模型。
4. 建立 Artifact Version 与 Workspace Revision 的版本事实。
5. 统一文件操作变更通道，并安全处理 Session 删除与回收站。
6. 最后实现 Work Results / Explorer / Change Viewer / Library 的体验闭环。

不要先做 UI，也不要先全面重写 FileService。应先把 Workspace ID、Binding 和旧数据迁移策略定清楚。
