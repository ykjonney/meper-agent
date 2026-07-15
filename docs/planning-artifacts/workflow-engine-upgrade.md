# Workflow 引擎商用级升级设计文档

**日期:** 2026-07-02
**状态:** 设计中
**决策人:** Logan_hu

---

## 1. 背景与目标

### 1.1 现状分析

当前 Agent Flow 的 Workflow 引擎基于 8 种核心节点（start/end/agent/tool/human/gateway/parallel/subflow），侧重编排控制，缺乏数据操作类节点。与 Dify、n8n、Coze 等商用产品对比，存在以下核心差距：

- 触发机制单一（仅 API/Agent 调用）
- 节点类型不足（缺 HTTP、代码执行、迭代、LLM 独立调用等）
- 工具定位模糊（内置能力与开发者扩展混杂）
- 知识库能力 DEFERRED
- 无消息通知通道
- 无调试测试能力

### 1.2 设计目标

1. **Agent 与 Workflow 解耦但可组合** — 两个模块各自独立可用，也可协作
2. **Workflow 达到商用级** — 补齐核心节点、触发机制、数据操作能力
3. **能力分层清晰** — 工具（内置配置即用）、Skill（Agent 专属技能）、知识库、消息通道各自定位明确
4. **MVP 范围可控** — 优先补齐阻塞性能力，后续迭代完善

---

## 2. 节点体系重新设计

### 2.1 设计原则

- 节点按**职责类型**分为 8 大类，每类有独立的配置面板和执行语义
- 所有操作类节点共享统一的**输入映射 / 输出映射 / 错误处理**机制
- 触发节点是 Workflow 的入口，决定 Workflow 如何被启动
- **工具节点**是 Workflow 中的通用操作节点，调用配置即用的内置工具（HTTP 请求、邮件、通知等）
- **Skill** 是 Agent 的专属技能，依附于 Agent，只能由 Agent 在推理中调用，Workflow 不可直接使用
- **内置节点**（AI 节点、分支节点等）是平台预置的专用节点，每种有独立配置面板

### 2.2 节点分类总表

| 类别 | 节点 | 状态 | MVP优先级 |
|------|------|------|-----------|
| **触发** | 手动触发 | 改造自现有 API 触发 | P0 |
| **触发** | 定时触发（Cron） | 新增 | P0 |
| **触发** | Webhook 触发 | 新增 | P0 |
| **触发** | 事件触发 | 新增 | P1 |
| **触发** | Agent 触发 | 已有（归入此类） | — |
| **触发** | API 触发 | 已有（归入此类） | — |
| **AI** | LLM 调用 | 新增 | P0 |
| **AI** | 知识库检索 | 新增 | P0 |
| **AI** | Agent 节点 | 已有 | — |
| **工具** | HTTP 请求 | 新增 | P0 |
| **工具** | 网页抓取 | 新增 | P0 |
| **工具** | 发送邮件 | 新增 | P1 |
| **工具** | 消息通知 | 新增 | P1 |
| **工具** | Webhook 回调 | 新增 | P1 |
| **工具** | JSON 处理 | 新增 | P0 |
| **工具** | CSV/Excel 处理 | 新增 | P2 |
| **工具** | 文本处理 | 新增 | P0 |
| **工具** | 文件读写 | 新增 | P2 |
| **工具** | 数据库查询 | 新增 | P2 |
| **工具** | 变量存储 | 新增 | P1 |
| **工具** | RSS 读取 | 新增 | P2 |
| **工具** | 图片理解 | 新增 | P2 |
| **执行** | 代码执行（Python 沙箱） | 新增 | P0 |
| **执行** | 变量赋值 | 新增 | P1 |
| **分支** | 条件分支（Gateway） | 已有 | — |
| **分支** | 并行执行 | 已有 | — |
| **分支** | 迭代循环 | 新增 | P0 |
| **分支** | 变量聚合 | 新增 | P0 |
| **分支** | 子流程 | 已有 | — |
| **人工** | 人工审批 | 已有 | — |
| **人工** | 人工输入 | 新增 | P1 |
| **系统** | Start | 已有 | — |
| **系统** | End | 已有 | — |
| **系统** | 延时等待 | 新增 | P2 |

### 2.3 触发节点详细设计

一个 Workflow 有且仅有一个触发节点。

#### 手动触发

用户在页面手动执行，等价于当前的 API 触发。

配置项：
- input_schema：定义输入参数表单（参数名/类型/默认值/必填）

#### 定时触发（Cron）

按 Cron 表达式定时自动执行。

配置项：
- cron 表达式 + 时区
- 输入参数默认值（每次触发使用默认值，可被外部覆盖）

#### Webhook 触发

外部系统通过 HTTP 回调触发。

配置项：
- 监听路径（自动生成唯一 URL）
- 认证方式（无 / API Key / HMAC 签名）
- 请求体 Schema（用于参数校验和自动解析）
- HTTP Method（POST/GET）

#### 事件触发

监听平台内部事件自动执行。

配置项：
- 事件类型（Task 完成 / Agent 错误 / 自定义事件）
- 过滤条件（事件属性匹配规则）
- 输入映射（事件数据 → Workflow 输入参数）

#### Agent 触发 / API 触发

已有设计，归入触发类别统一管理。

### 2.4 AI 节点详细设计

#### LLM 调用节点

独立调用一次大模型推理，不经过完整 Agent 流程。

与 Agent 节点的区别：
- LLM 节点：一次推理，输入→输出，确定性强，无工具调用，无多轮推理
- Agent 节点：完整 Agent 执行，可能多轮推理+工具调用+自主决策

配置项：
- 选择模型（从平台已接入模型中选择）
- System Prompt（支持 `{{变量}}` 模板）
- 用户输入（变量引用）
- temperature / max_tokens
- 输出格式：纯文本 / JSON Schema / 结构化输出
- 输出映射：结果 → 变量池

#### 知识库检索节点

从绑定的知识库中检索相关文档片段。

配置项：
- 选择知识库（支持跨多个知识库检索）
- 查询文本（支持 `{{变量引用}}`）
- 检索模式：向量 / 关键词 / 混合
- TopK（返回结果数量）
- 相似度阈值
- 输出：结果列表（文本 + 来源文档 + 页码 + 评分）→ 变量池

### 2.5 工具节点设计

#### 工具定位

工具 = 平台内置的、配置即用的通用能力。用户只需配置参数，不写代码。

工具与 Skill 是完全不同的东西：

| | 工具（Tool） | Skill |
|---|---|---|
| 定位 | 通用操作能力 | Agent 的专属技能 |
| 使用者 | Agent + Workflow | 仅 Agent |
| 使用方式 | 配置即用 | 依附于 Agent，由 Agent 推理调用 |
| 开发者 | 平台内置 | 用户/开发者编写注册 |
| 独立性 | 独立存在，不依附任何模块 | 依附于 Agent，不能独立存在 |
| 示例 | HTTP请求/发邮件/网页抓取/通知 | 自定义Python脚本/MCP服务 |

#### 统一配置机制

所有工具节点共享统一的配置结构：

```
┌─────────────────────────────────────┐
│ 🔧 工具节点                          │
├─────────────────────────────────────┤
│ 工具选择：[下拉：按分类浏览]         │
│   ├─ 📡 网络（HTTP/抓取/RSS）       │
│   ├─ 📨 通信（邮件/通知/Webhook）   │
│   ├─ 📊 数据（JSON/CSV/文本）       │
│   ├─ 💾 存储（文件/数据库/变量）     │
│   └─ 🤖 AI（图片理解）              │
│                                      │
│ ─── 工具专属配置（因工具而异）───    │
│                                      │
│ 输入映射：                           │
│ ┌──────────┬────────────────────┐   │
│ │ 参数名    │ 值来源              │   │
│ ├──────────┼────────────────────┤   │
│ │ param_a  │ {{上游节点.output}} │   │
│ │ param_b  │ 固定值: xxx         │   │
│ └──────────┴────────────────────┘   │
│                                      │
│ 输出映射：                           │
│ result_field → {{变量名}}           │
│                                      │
│ 错误处理：                           │
│ 重试策略：[最多N次，间隔Ns]          │
│ 失败动作：[走错误分支 / 跳过 / 终止] │
└─────────────────────────────────────┘
```

#### 各工具配置详情

**HTTP 请求**
- Method（GET/POST/PUT/DELETE/PATCH）
- URL（支持变量引用）
- Headers（Key-Value 列表，支持变量）
- Body（JSON/Form/Raw，支持变量）
- 认证：无 / Basic / Bearer Token / API Key
- 超时时间
- 响应映射：状态码 → 变量，Body → 变量，Headers → 变量

**网页抓取**
- 目标 URL（支持变量）
- 提取方式：CSS 选择器 / XPath
- 提取字段列表（字段名 + 选择器）
- 等待策略：页面加载完成 / 等待特定元素
- 输出：结构化数据 → 变量池

**发送邮件**
- SMTP 配置（复用平台邮件通道配置）
- 收件人（支持变量引用）
- 主题（支持模板）
- 内容（HTML/纯文本，支持模板）
- 附件（文件路径/变量引用）

**消息通知**
- 选择消息通道（从已配置的通道列表中选择）
- 收件人/群组（支持变量引用）
- 内容模板（Jinja2，支持变量引用）
- 依赖消息通道模块

**JSON 处理**
- 操作类型：解析 / 构造 / 字段提取 / 转换
- 输入数据（变量引用）
- 操作配置（JSONPath 提取 / 字段映射 / 模板构造）
- 输出 → 变量池

**文本处理**
- 操作类型：正则匹配 / 替换 / 拼接 / 模板渲染
- 输入文本（变量引用）
- 操作参数（正则表达式/替换规则/模板等）
- 输出 → 变量池

### 2.6 分支节点详细设计

#### 迭代循环节点（新增）

遍历列表数据，对每项执行子流程。

配置项：
- 迭代数据源：`{{上游节点.列表字段}}`
- 子流程定义（迭代体内的节点）
- 并发数限制（默认串行，可配置并行数）
- 中断条件（可选，满足条件提前终止）

输出：
- 每次迭代的结果列表 → 变量池
- 通常与「变量聚合」节点配合使用

#### 变量聚合节点（新增）

合并迭代或并行的结果。

配置项：
- 数据源：`{{迭代节点.results}}`
- 聚合方式：
  - 合并列表（多个列表合并为一个）
  - 拼接字符串（多个文本拼接）
  - 求和/计数（数值聚合）
  - 自定义表达式（Jinja2）
- 输出 → 变量池

### 2.7 人工节点增强

#### 人工输入节点（新增）

暂停 Workflow 等待用户填写表单数据，填写后继续执行。

与人工审批的区别：
- 人工审批：approve/reject/skip（决策型）
- 人工输入：填写表单数据（输入型）

配置项：
- 表单字段定义（字段名/类型/校验规则/默认值）
- 超时时间 + 超时动作
- 通知方式（消息通道通知填写人）

---

## 3. 工具与 Skill 的关系

### 3.1 核心区别

```
工具（Tool）：
  ├── 平台内置的通用操作能力
  ├── 配置即用，不写代码
  ├── Agent 和 Workflow 都可以使用
  ├── 独立存在，不依附任何模块
  └── 例：HTTP请求/网页抓取/邮件/通知/JSON处理

Skill：
  ├── Agent 的专属技能
  ├── 依附于 Agent，只能由 Agent 在推理中调用
  ├── 不能脱离 Agent 独立使用
  ├── 开发者编写注册（Python脚本/MCP服务）
  └── 例：自定义业务脚本/MCP接入的外部服务
```

**关键：工具和 Skill 是两个完全不同的概念，不存在包含关系。**

### 3.2 使用路径

```
Agent 使用工具：
  Agent REACT 推理 → 选择工具 → 配置参数 → 执行 → 结果用于推理

Agent 使用 Skill：
  Agent REACT 推理 → LLM 自主选择 Skill → 执行 → 结果用于推理
  （Skill 绑定在 Agent 上，通过 Agent 的能力配置注入）

Workflow 使用工具：
  工具节点 → 选择工具类型 → 配置参数映射 → 执行 → 结果写入变量池

Workflow 使用 Skill：
  ❌ 不可直接使用
  如需 Skill 能力：通过 Agent 节点调用一个绑定了该 Skill 的 Agent
```

### 3.3 工具层（平台内置）

后端实现：

```
engine/workflow/tools/
├── __init__.py
├── base.py               # BaseTool 抽象类
│   ├── execute(config, inputs) → ToolResult
│   ├── validate_config(config) → bool
│   └── get_schema() → ToolSchema  # 配置面板 Schema
├── network/
│   ├── http_request.py    # HTTP 请求
│   ├── web_scraper.py     # 网页抓取
│   └── rss_reader.py      # RSS 读取
├── communication/
│   ├── email_sender.py    # 发送邮件
│   ├── notification.py    # 消息通知（依赖消息通道模块）
│   └── webhook_callback.py # Webhook 回调
├── data/
│   ├── json_processor.py  # JSON 处理
│   ├── csv_processor.py   # CSV/Excel 处理
│   └── text_processor.py  # 文本处理
├── storage/
│   ├── file_rw.py         # 文件读写
│   ├── database_query.py  # 数据库查询
│   └── variable_store.py  # 变量存储
└── ai/
    └── image_understand.py # 图片理解
```

### 3.4 Skill 层（仅 Agent）

开发者扩展，需写代码注册。保持现有 Epic 3 设计：

- **内建 Skill**：平台预置的通用代码工具
- **Python Skill**：用户上传 Python 脚本，解析函数签名注册
- **MCP Skill**：通过 MCP 协议接入外部服务

Skill 注册后绑定到 Agent，在 Agent 的 REACT 推理循环中被 LLM 自主选择调用。Workflow 不可直接使用 Skill，如需使用则通过 Agent 节点间接调用。

---

## 4. 消息通道模块（独立模块）

### 4.1 设计定位

消息通道是**平台级基础设施**，独立于 Agent 和 Workflow，两者均可调用。同时支持系统事件自动触发通知。

```
               ┌──────────────────┐
               │   消息通道模块     │
               └────────┬─────────┘
                        │
         ┌──────────────┼──────────────┐
         ▼              ▼              ▼
   ┌──────────┐  ┌──────────┐  ┌──────────┐
   │  Agent   │  │ Workflow │  │  系统事件  │
   │ 系统工具  │  │通知工具节点│ │ 自动告警  │
   └──────────┘  └──────────┘  └──────────┘
```

### 4.2 后端架构

```
notification/
├── __init__.py
├── models.py              # 数据模型
│   ├── Channel            # 通道配置（类型/凭证/参数）
│   ├── Notification       # 通知记录（状态/发送时间/接收人）
│   └── Template           # 通知模板
├── dispatcher.py          # 统一调度器
│   ├── send(channel_id, template, context) → Notification
│   └── send_batch(channel_id, template, recipients[], context)
├── channels/
│   ├── base.py            # BaseChannel 抽象类
│   ├── webhook_channel.py # HTTP POST 回调
│   ├── email_channel.py   # SMTP 邮件
│   ├── feishu_channel.py  # 飞书机器人
│   ├── dingtalk_channel.py # 钉钉机器人
│   ├── wechat_work_channel.py # 企业微信
│   ├── slack_channel.py   # Slack
│   └── internal_channel.py # 站内通知（WebSocket 推送）
├── templates/
│   ├── engine.py          # Jinja2 模板引擎（sandbox 模式）
│   └── presets/           # 预置模板（审批通知/错误告警/执行完成）
└── api/
    ├── channels.py        # 通道 CRUD API
    ├── templates.py       # 模板 CRUD API
    └── notifications.py   # 通知记录查询 API
```

### 4.3 通道抽象

```python
class BaseChannel:
    """消息通道抽象基类"""

    async def send(self, message: NotificationMessage) -> SendResult:
        """发送单条消息"""
        ...

    async def send_batch(self, messages: list[NotificationMessage]) -> list[SendResult]:
        """批量发送"""
        ...

    def validate_config(self, config: dict) -> bool:
        """验证通道配置（如 webhook URL 可达、SMTP 可连接）"""
        ...

    @property
    def channel_type(self) -> str:
        """通道类型标识"""
        ...
```

### 4.4 通道 MVP 优先级

| 优先级 | 通道 | 说明 |
|--------|------|------|
| MVP | 站内通知 | 已有 WebSocket，加通知中心 + 角标 |
| MVP | Webhook | 已有 Epic 8 设计，整合进来 |
| MVP | 邮件（SMTP） | 企业基础通道 |
| Post-MVP | 飞书 | 国内企业高频需求 |
| Post-MVP | 钉钉 | 国内企业补充 |
| Post-MVP | 企业微信 | 国内企业补充 |
| Post-MVP | Slack | 海外/外企 |

### 4.5 使用方式

**Workflow 中（消息通知工具节点）：**

选择通道 → 收件人（支持变量引用）→ 内容模板（Jinja2）→ 发送

**Agent 中（系统工具）：**

`send_notification(channel_id, template, recipients, context)` — Agent 推理过程中主动发送

**系统事件自动触发：**

配置规则：事件类型 + 通道 + 模板 + 触发条件（如 Task 失败次数 ≥ 3 时告警）

---

## 5. 知识库（完整本地实现，考虑到时间问题可以直接在第三方rag上做二次开发）

### 5.1 设计定位

知识库是**平台级基础设施**，Agent 和 Workflow 均可使用。MVP 采用本地完整实现，基于 MongoDB Atlas Vector Search。

### 5.2 后端架构

```
knowledge/
├── __init__.py
├── models.py                  # 数据模型
│   ├── KnowledgeBase          # 知识库
│   ├── Document               # 文档
│   ├── Chunk                  # 切片
│   └── RetrievalResult        # 检索结果
├── parser/                    # 文档解析层
│   ├── base.py                # BaseParser 抽象类
│   ├── pdf_parser.py          # PDF → 文本（pymupdf）
│   ├── word_parser.py         # Word → 文本（python-docx）
│   ├── markdown_parser.py     # Markdown → 文本
│   ├── txt_parser.py          # 纯文本
│   └── pipeline.py            # 解析 Pipeline：上传→解析→切片→嵌入→存储
├── chunker/                   # 切片策略层
│   ├── base.py                # BaseChunker 抽象类
│   ├── fixed_size_chunker.py  # 固定长度 + 重叠切片
│   └── config.py              # chunk_size / overlap / separator
├── embedder/                  # 嵌入层
│   ├── base.py                # BaseEmbedder 抽象类
│   ├── llm_embedder.py        # 调用 LLM 嵌入模型
│   └── config.py              # 嵌入模型选择 + 维度配置
├── retriever/                 # 检索层
│   ├── base.py                # BaseRetriever 抽象类
│   ├── vector_retriever.py    # 向量检索（MongoDB Atlas Vector Search）
│   ├── keyword_retriever.py   # 关键词检索（MongoDB text search）
│   ├── hybrid_retriever.py    # 混合检索 + RRF 融合排序
│   └── config.py              # TopK / 阈值 / 检索模式
├── api/
│   ├── knowledge_bases.py     # 知识库 CRUD
│   ├── documents.py           # 文档上传/删除/查询
│   └── retrieval.py           # 检索 API（内部调用）
└── services/
    ├── kb_service.py          # 知识库业务逻辑
    └── document_service.py    # 文档处理业务逻辑
```

### 5.3 数据模型

#### KnowledgeBase 集合

```json
{
    "_id": "kb_xxx",
    "name": "产品手册",
    "description": "公司产品使用手册知识库",
    "config": {
        "chunk_size": 500,
        "chunk_overlap": 50,
        "embedding_model": "text-embedding-3-small",
        "embedding_dimensions": 1536,
        "separator": "\n\n"
    },
    "stats": {
        "document_count": 12,
        "chunk_count": 1456,
        "total_size_bytes": 5242880
    },
    "status": "active",
    "created_by": "user_xxx",
    "created_at": "2026-07-02T10:00:00Z",
    "updated_at": "2026-07-02T10:00:00Z"
}
```

#### Document 集合

```json
{
    "_id": "doc_xxx",
    "knowledge_base_id": "kb_xxx",
    "name": "用户手册v2.pdf",
    "file_type": "pdf",
    "file_size": 1048576,
    "file_path": "/data/uploads/kb_xxx/doc_xxx.pdf",
    "parse_status": "completed",
    "parse_error": null,
    "chunk_count": 120,
    "uploaded_by": "user_xxx",
    "created_at": "2026-07-02T10:00:00Z"
}
```

#### Chunk 集合

```json
{
    "_id": "chunk_xxx",
    "knowledge_base_id": "kb_xxx",
    "document_id": "doc_xxx",
    "index": 0,
    "text": "这是一段切片文本...",
    "embedding": [0.012, -0.034, "..."],
    "token_count": 380,
    "metadata": {
        "page": 1,
        "section": "第一章",
        "source_file": "用户手册v2.pdf"
    },
    "created_at": "2026-07-02T10:00:00Z"
}
```

#### MongoDB Atlas Vector Search Index

```json
{
    "mappings": {
        "dynamic": false,
        "fields": {
            "embedding": {
                "type": "knnVector",
                "dimensions": 1536,
                "similarity": "cosine"
            },
            "knowledge_base_id": { "type": "token" }
        }
    }
}
```

### 5.4 文档处理 Pipeline

```
上传文档 → 解析 → 切片 → 嵌入 → 索引完成

1. 上传
   ├── 接收文件（单文件 ≤ 50MB）
   ├── 支持格式：PDF / Word / Markdown / TXT
   ├── 存入文件系统
   └── 创建 document 记录（status=pending）

2. 解析（异步 Celery 任务）
   ├── 根据 file_type 选择对应 Parser
   ├── 提取纯文本 + 元数据（页码/章节等）
   └── 更新 document 记录

3. 切片
   ├── 根据知识库 config（chunk_size / overlap / separator）
   ├── 每个切片记录 source metadata
   └── 批量创建 chunk 记录

4. 嵌入（异步，批量）
   ├── 调用配置的 embedding 模型
   ├── 批量嵌入（batch_size 可配置）
   └── 更新 chunk 的 embedding 字段

5. 索引完成
   ├── MongoDB Atlas Vector Search 自动索引
   └── 更新 knowledge_base stats + status
```

### 5.5 检索实现

```python
class HybridRetriever:
    """混合检索：向量 + 关键词 + RRF 融合"""

    async def retrieve(
        self,
        knowledge_base_id: str,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.5,
        mode: str = "hybrid"  # vector / keyword / hybrid
    ) -> list[RetrievalResult]:
        if mode in ("vector", "hybrid"):
            query_embedding = await self.embedder.embed(query)
            vector_results = await self.vector_retriever.search(
                knowledge_base_id, query_embedding, top_k=top_k * 2
            )

        if mode in ("keyword", "hybrid"):
            keyword_results = await self.keyword_retriever.search(
                knowledge_base_id, query, top_k=top_k * 2
            )

        if mode == "hybrid":
            results = self._rrf_fusion(vector_results, keyword_results, k=60)
        elif mode == "vector":
            results = vector_results
        else:
            results = keyword_results

        results = [r for r in results if r.score >= score_threshold]
        return results[:top_k]

    def _rrf_fusion(self, *result_lists, k=60):
        """RRF: score = sum(1 / (k + rank_i))"""
        scores = {}
        for results in result_lists:
            for rank, result in enumerate(results):
                key = (result.chunk.document_id, result.chunk.id)
                scores[key] = scores.get(key, 0) + 1.0 / (k + rank + 1)
        sorted_keys = sorted(scores, key=scores.get, reverse=True)
        return [self._build_result(key, scores[key]) for key in sorted_keys]
```

### 5.6 使用方式

**Agent 使用：**
- Agent 配置中绑定知识库 → 推理时自动检索，结果注入 System Prompt context
- Agent 也可通过工具主动检索：`knowledge_search(query, kb_ids[], top_k)`

**Workflow 使用：**
- 知识库检索节点 → 选择知识库 + 查询文本（变量引用）+ TopK + 阈值
- 检索结果输出到变量池，可传递给 LLM 节点作为 context

### 5.7 MVP 范围

**MVP 做：**
- 知识库 CRUD
- 文档上传（PDF / Word / Markdown / TXT，≤ 50MB）
- 自动解析 → 切片 → 嵌入 → 存储
- 向量 + 关键词混合检索（RRF 融合）
- 检索结果带相关度评分和来源引用
- Workflow 知识库检索节点
- Agent 绑定知识库自动检索

**MVP 不做（Post-MVP）：**
- 多模态文档（图片 OCR、表格解析）
- 文档级权限控制
- 知识库 MCP Server 对外暴露
- 增量更新（文档修改后只更新变化切片）
- 重排序（Reranker 二次精排）
- 语义切片（按段落/标题自动切分）

---

## 6. Agent 与 Workflow 协作模式

### 6.1 三种协作模式

```
模式 A：Agent 调用 Workflow（已有设计）
  Agent → create_task → Workflow 执行 → 结果返回 Agent
  适用：标准化流程（审批、报告生成），需要 Task 生命周期管理

模式 B：Workflow 调用 Agent（已有设计）
  Workflow 中 Agent 节点 → 调用 Agent 推理 → 结果写入变量池
  适用：流程中某个环节需要 AI 自主决策
  间接使用 Skill：Agent 内部可使用 Skill

模式 C：Workflow 作为 Agent 的轻量工具（新增思路）
  把工作流注册为 tool，Agent 在 REACT 循环中直接调用
  与模式 A 的区别：不创建 Task，同步执行，轻量级
  适用：简单的数据处理流程，不需要人工审批和 Task 管理
```

### 6.2 能力边界

| 能力 | Agent | Workflow |
|------|-------|----------|
| 工具（内置） | ✅（REACT 推理中调用） | ✅（工具节点配置调用） |
| Skill（专属技能） | ✅（REACT 推理自主选择） | ❌（通过 Agent 节点间接使用） |
| 知识库 | ✅ | ✅ |
| 消息通道 | ✅（系统工具） | ✅（消息通知工具节点） |
| 多轮推理 | ✅ | ❌（通过 Agent 节点） |
| 定时执行 | ❌ | ✅（触发节点） |
| 人工审批 | ❌ | ✅（人工节点） |
| 条件分支 | ❌ | ✅（分支节点） |
| 并行执行 | ❌ | ✅（分支节点） |

---

## 7. 平台模块总览

```
┌─────────────────────────────────────────────────────────┐
│                       Agent Flow                         │
│                                                          │
│   ┌──────────┐                  ┌──────────┐            │
│   │  Agent   │◄────────────────►│ Workflow │            │
│   │  引擎    │     协作          │  引擎     │            │
│   └────┬─────┘                  └────┬─────┘            │
│        │                              │                   │
│        │         ┌────────────────────┤                   │
│        │         │                    │                   │
│   ┌────▼─────────▼──┐  ┌─────────────▼──┐              │
│   │  工具（内置）     │  │  Skill（Agent   │              │
│   │  HTTP/邮件/通知   │  │  专属技能）     │              │
│   │  抓取/JSON/...   │  │  Python/MCP    │              │
│   │  Agent+Workflow  │  │  仅Agent可用    │              │
│   │  均可使用        │  │  依附于Agent    │              │
│   └─────────────────┘  └────────────────┘              │
│                                                          │
│   ┌─────────┐  ┌───────┐                                │
│   │ 知识库   │  │消息通道│                               │
│   │ (平台级) │  │(平台级)│                               │
│   └─────────┘  └───────┘                                │
│       ▲  ▲        ▲  ▲                                  │
│       │  │        │  │                                  │
│    Agent Workflow Agent Workflow                         │
└─────────────────────────────────────────────────────────┘
```

---

## 8. MVP 实施优先级

### P0 — 核心能力（必须做）

| # | 项目 | 说明 |
|---|------|------|
| 1 | 触发节点 | 手动 + 定时 + Webhook |
| 2 | AI 节点 | LLM 调用 + 知识库检索 |
| 3 | 核心工具 | HTTP 请求 + 网页抓取 + JSON 处理 + 文本处理 |
| 4 | 分支节点 | 迭代循环 + 变量聚合 |
| 5 | 代码执行 | Python 沙箱 |
| 6 | 知识库 | 完整本地实现（解析+切片+嵌入+混合检索） |
| 7 | 统一映射 | 所有节点的输入/输出映射 + 错误处理机制 |

### P1 — 商用体验（紧跟 P0）

| # | 项目 | 说明 |
|---|------|------|
| 8 | 通信工具 | 发送邮件 + 消息通知 + Webhook 回调 |
| 9 | 消息通道 MVP | 站内通知 + Webhook + 邮件（SMTP） |
| 10 | 执行节点 | 变量赋值 |
| 11 | 人工增强 | 人工输入节点 |
| 12 | 触发扩展 | 事件触发 |
| 13 | 存储工具 | 变量存储 |

### P2 — 完善度（Post-MVP）

| # | 项目 | 说明 |
|---|------|------|
| 14 | 文件处理 | CSV/Excel 处理 + 文件读写 |
| 15 | 数据库查询 | SQL 只读查询 |
| 16 | 延时等待 | 等待指定时间/时间点 |
| 17 | 消息通道扩展 | 飞书 / 钉钉 / 企业微信 / Slack |
| 18 | 知识库增强 | 语义切片 + Reranker + 多模态 |
| 19 | 更多工具 | RSS 读取 + 图片理解 |

---

## 9. 技术依赖

| 组件 | 用途 | 备注 |
|------|------|------|
| pymupdf | PDF 文本提取 | 性能优于 pdfplumber |
| python-docx | Word 文档解析 | — |
| httpx | HTTP 请求工具底层 | 异步支持好 |
| playwright / beautifulsoup4 | 网页抓取 | 按需选择 |
| jinja2 (sandbox) | 模板渲染（通知/变量） | 已有 |
| MongoDB Atlas Vector Search | 向量检索 | 已有基础设施 |
| Celery | 文档处理异步任务 | 已有 |
| redis | 任务队列 | 已有 |
