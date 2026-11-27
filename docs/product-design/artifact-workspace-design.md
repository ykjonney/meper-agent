# Artifact & Workspace 设计

> 状态：**MVP Design Proposal（产品方向已讨论，待代码差距审查）**
>
> 日期：2026-11-27
>
> 本文将 Artifact 与 Workspace 的产品概念、MVP 行为和实现边界收敛为一份设计基线。它不是对现有代码实现状态的描述，也不意味着立即开始重构。

## 1. 设计目标与原则

产品定位是以 Personal Agent 体验为核心、具备企业协作与治理能力的 Agent 产品。Workspace 是 Agent 持续工作的基础设施，文件管理服务于 Work 的执行和交付，不应演变为独立的复杂内容管理平台。

设计原则：

1. 用户只需要理解 Workspace、文件、成果、变更和版本。
2. Workspace 持久化，独立于 Conversation、Work 和 Execution 生命周期。
3. 系统内文件统一使用 Artifact 表示，不另建 WorkspaceFile 业务对象。
4. MVP 不实现跨 Workspace 共享同一 Artifact；跨 Workspace 复用默认复制。
5. 版本、快照和变更记录由 Runtime 管理，用户不需要手动 Commit。
6. 只实现核心文件管理闭环，为未来扩展留接口，不提前实现复杂治理能力。

## 2. 核心概念

### 2.1 Workspace

持久化文件工作空间，定义文件组织边界和默认访问边界。

- 每个 User 有一个 Global Workspace。
- Project 可以配置独立 Project Workspace。
- Project 未配置时，其 Conversation 直接绑定 Global Workspace，不复制文件。
- Conversation 默认有一个 Primary Workspace，可显式绑定 Additional Workspace。
- 同一 Conversation 中的多个 Work 默认共享 Workspace。
- Workspace 不属于 Session、Work 或 Execution。
- Execution 使用 Workspace 时加载运行副本；运行目录不是持久化事实来源。

### 2.2 Artifact

系统中统一的文件实体，包括用户上传、Agent 创建、临时文件、中间文件和最终交付文件。

MVP 中 Artifact 归属于一个 Workspace。稳定 Artifact ID 用于引用该文件及其历史版本。Artifact 不因被 Work 作为成果引用而改变身份或归属。

Artifact 的核心元数据建议包括：

- artifact_id
- workspace_id
- current_path
- filename
- mime_type
- size
- current_version_id
- created_at / updated_at
- created_by（user / agent / system）
- deleted_at（软删除标记，可为空）

不为 Temporary、Intermediate、Persistent、Archived 建立独立实体或复杂状态机。文件是否为某个 Work 的交付成果，由 Work-Artifact 关联表达。

### 2.3 Artifact Version

单个 Artifact 的不可变内容版本。

- 文件内容发生变化时创建新版本。
- 版本引用 Content Blob（内容寻址存储）。
- 记录创建时间、创建者/来源、内容 Hash、大小和 MIME Type。
- 历史版本不可原地修改。
- 恢复历史版本时创建一个新版本，内容可与旧版本相同。

不采用 Git 式分支、Commit、Tag 或 Merge 模型。

### 2.4 Workspace Revision

Workspace 某一时刻的文件状态快照，描述路径、Artifact 和当前 Version 的映射。

- 每次成功提交一组 Workspace 文件变更后产生新 Revision。
- Revision 与 Artifact Version 不同：前者描述整个 Workspace，后者描述单个文件内容。
- Revision 是 Runtime 的一致性和恢复基础，不要求用户理解或手动操作。

### 2.5 Change

文件操作事实记录，用于 Change Viewer、追踪和审计。

MVP 记录 create、update、rename、move、delete、restore 等操作。Change 不存储第二份文件内容；内容由 Artifact Version / Blob 管理。

### 2.6 Work Result

Work 与交付 Artifact 之间的关联，不是新的文件实体或文件存储。

Agent 明确声明交付文件，Runtime 验证文件存在后建立 Work-Artifact 关联。用户也可以从 Workspace Explorer 手动添加或移除成果关联。

## 3. 文件操作语义

| 操作 | MVP 行为 | 是否创建 Artifact Version |
|---|---|---|
| 创建文件 | 创建 Artifact 和初始 Version | 是（初始版本） |
| 修改文件内容 | 更新当前 Version 指针并保留历史 | 是 |
| 上传新文件 | 创建 Artifact 和初始 Version | 是（初始版本） |
| 上传覆盖已有文件 | 明确提示覆盖或另存为；覆盖时创建新 Version | 覆盖时是 |
| 重命名 | 更新路径/名称 | 否 |
| Workspace 内移动 | 更新路径 | 否 |
| 复制文件 | 创建新 Artifact，独立版本历史；Blob 可复用 | 新 Artifact 初始版本 |
| 跨 Workspace 复用 | 复制到目标 Workspace，创建新 Artifact | 新 Artifact 初始版本 |
| 删除 | 软删除并进入回收站 | 否 |
| 恢复 | 恢复文件条目；必要时解决原路径冲突 | 通常否 |
| 下载 | 下载当前或指定历史版本 | 否 |

跨 Workspace Reference、跨 Workspace 版本同步、跨 Owner Move 和 Copy-on-Write 不属于 MVP。

## 4. 版本与并发规则

### 4.1 自动版本

Agent、用户和外部工具对文件内容的修改均由 Runtime 统一纳入版本管理。若内容 Hash 未变化，不创建重复版本。仅路径变化不创建 Artifact Version，但会记录 Change 并更新 Workspace Revision。

### 4.2 并发

沿用已确认的乐观并发控制方向：

- 多 Session 并发读取允许。
- 不同文件并行修改允许。
- 同一文件并行修改必须检测冲突，禁止静默覆盖。
- 同一 Conversation 的多个 Work 默认共享 Workspace。
- 需要隔离的并行 Work 使用 Working Copy，基于某个 Workspace Revision 创建。
- Working Copy 完成后检查基础 Revision 和文件版本，检测冲突后再提交。
- 多节点通过 Revision CAS 保证提交一致性；Lease / Fencing Token 可用于阻止失效执行者继续写入。
- 不以 Workspace 全局锁作为默认并发方案。

## 5. 删除与回收站

MVP 采用软删除：

- 删除后从当前文件列表隐藏。
- 保留 Artifact 元数据、历史版本和 Change 记录。
- 用户可从回收站恢复。
- 永久删除是独立操作，并检查必要的引用和保留约束。
- Blob 的物理清理由后台回收机制异步完成；共享 Blob 只有在不再被任何有效版本引用时才可清理。

不引入复杂归档状态机或多级保留策略。

## 6. 用户可见入口

四个入口是同一批 Artifact 的不同视图，不是四套文件系统。

### 6.1 Work Results（Work 级）

展示当前 Work 明确声明的交付成果。提供预览、下载、查看说明，以及从 Workspace Explorer 添加/移除成果关联。

没有成果时显示空状态和添加入口，不自动展示所有文件。

### 6.2 Workspace Explorer（Workspace 级）

展示当前 Workspace 的完整文件树，支持基础文件管理：浏览、预览、上传、下载、创建、重命名、移动、删除、恢复和查看版本历史。

### 6.3 Change Viewer（Work / Execution 级）

展示某个 Work 或执行范围内的文件新增、修改、删除、重命名和移动记录。文本类文件提供基础 Diff；二进制文件展示操作记录和版本信息。

### 6.4 Artifact Library（用户级聚合视图）

统一查找和复用用户有权访问的 Workspace 文件：

- 默认展示 Global Workspace。
- 可以切换到指定 Project Workspace。
- 支持跨 Workspace 搜索，结果标明所属 Workspace。
- 选择其他 Workspace 的文件供当前 Work 使用时，复制到当前 Workspace。
- Library 只是聚合视图，不是新的 Workspace 或存储位置。

## 7. Workspace 归属与访问

MVP 不建设独立、复杂的文件级授权系统。

- Global Workspace 由 User 管理。
- Project Workspace 由 Project 管理。
- 文件默认继承所属 Workspace 的访问边界。
- 用户访问文件必须先有权访问 Workspace。
- Agent 通过 Conversation 的 Workspace Binding 获得工作空间访问能力。
- 跨 Workspace 复制后，目标 Artifact 按目标 Workspace 的访问边界管理。
- 敏感文件操作继续接入统一 Action Governance。

暂缓文件级复杂 ACL、授权继承来源、分享链接、跨 Workspace 共享引用和数据血缘治理。

## 8. 存储与运行时架构

- Metadata 存数据库。
- 文件字节通过 Storage Provider 存储。
- MVP 使用 Local Filesystem Backend；未来可扩展 Shared Filesystem / Object Storage。
- Content Blob 使用内容寻址，Artifact Version 引用 Blob；相同字节可去重。
- Workspace Revision 保存整体文件清单和版本映射。
- Execution 节点上的 Runtime Workspace 是可重建副本，不是持久化事实来源。
- 节点迁移、Execution 重试或 Runtime 重建不能导致已提交文件丢失。

Workspace Storage 与 Runtime Placement 分离。不要把某个 Worker 本地目录路径作为 Workspace 的持久化身份。

## 9. MVP 范围

### 实现

- Global / Project Workspace 及 Workspace Binding。
- Workspace 持久化和 Storage Provider 抽象。
- Artifact 与 Artifact Version。
- 文件上传、下载、浏览和基础管理。
- Workspace Revision 与 Change。
- 自动版本、历史版本查看/下载/恢复。
- 回收站与恢复。
- 基础 Working Copy 和同文件冲突检测。
- Work Results 与成果关联。
- Workspace Explorer。
- 基础 Change Viewer。
- Artifact Library 的 Workspace 切换、搜索和跨 Workspace 复制。

### 暂缓

- 跨 Workspace Reference 和共享同一 Artifact。
- 跨 Workspace 版本同步、合并和 Copy-on-Write。
- 跨 Owner Move / 所有权转移流程。
- 复杂文件级 ACL、分享链接和外部协作。
- 在线 Office 编辑和多人实时协同编辑。
- Git 式分支、Commit、Merge。
- 复杂 Artifact 生命周期状态机。
- 高级数据血缘与企业内容治理。

“暂缓”表示不纳入当前 MVP，不代表产品永久不做。

## 10. 实施阶段建议

1. **代码盘点与差距确认**：检查现有 Workspace、File Library、Storage、Session 生命周期和 Execution 资源绑定，形成迁移与兼容方案。
2. **统一文件模型**：建立 Artifact / Version，明确现有 FileRef 的复用、演进或兼容方式。
3. **Workspace 持久化改造**：从 Session 级目录过渡到 Workspace 资源及 Binding；确保删除 Session 不误删 Workspace。
4. **版本与变更**：接入 Blob、Artifact Version、Workspace Revision、Change、冲突检测和回收站。
5. **Work 集成**：建立 Work Results 关联与 Agent 成果声明协议。
6. **用户体验**：实现 Explorer、Change Viewer 和 Artifact Library。

阶段顺序是建议；具体拆分需以代码审查结果为准。

## 11. 现有实现审查关注点

审查现有代码时重点回答：

- 当前 Workspace 目录是否仍以 user_id/session_id 为身份？如何兼容迁移？
- FileRef / FileUsage 能否演进为 Artifact / 引用关系，避免重复文件系统？
- FileStorage 是否已具备 Storage Provider 所需接口？
- input / output / tmp 目录角色如何映射到统一 Artifact？是否需要保留环境语义但取消业务对象差异？
- Session 删除是否会清理应当持久化的 Workspace？
- Workflow Task Workspace 与新的 Work / Conversation / Workspace 关系如何区分？
- Execution ResourceBinding 是否能显式关联 workspace_id / revision，而不依赖路径推断？
- 当前文件操作如何产生可追溯 Change，如何确保 Agent、用户和外部工具走统一提交路径？
- 现有 local workspace 模式如何纳入统一 Workspace 身份和安全边界？

审查结果应区分：可复用、需调整、需新增、可淘汰；不预设必须整体重写。

## 12. 关键领域边界

- Project：跨 Conversation 的协作边界。
- Conversation：Work 的唯一归属边界。
- Work：任务、计划与交付成果的归属。
- Workspace：持久化文件工作空间。
- Artifact：统一文件实体。
- Artifact Version：单文件内容历史。
- Workspace Revision：整体文件状态快照。
- Change：文件操作事实。
- Execution：运行边界，使用 Workspace 的临时运行副本。

本文是 Artifact & Workspace 的 MVP 设计基线。若代码审查发现真实需求或技术约束与本文冲突，应先记录差异并讨论，再修改设计或实施，不应在实现中暗自增加新的业务抽象。
