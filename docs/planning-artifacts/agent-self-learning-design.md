# 用户级技能与记忆（User Skills & Memory）设计

> 状态：草案
> 作者：agent-flow 团队
> 最后更新：2026-08-18
> 关联文档：`architecture.md`、`design-multi-agent-loop-node.md`、`knowledge-base-vector-plan.md`

---

## 0. 概述

为平台引入**用户级经验资产**：用户在会话中显式要求构建技能，agent 自主捕获用户偏好记忆（用户无感知）；技能归用户所有、可随时查看编辑、可发布到技能广场供他人安装使用，使用者的反馈构成技能积分。

核心原则一句话：**何时学交给用户（显式触发）、归谁交给命名空间（owner 校验）、好不好交给使用者（积分）**。

### 关键设计决策

| 决策点 | 取舍 | 理由 |
|--------|------|------|
| 用户技能作用域 | 跨 agent，跟着用户走，全量注入名列表 | 技能按 description 由 LLM 自选加载，不命中不加载；软上限控制列表长度；agent 可整体关闭（user_skills_enabled） |
| 身份模型 | 统一平台用户：内部登录与外部 API（token 已绑定平台用户）共用 user_id；IM 渠道首期不生成记忆/技能（不注入、写入被拒） | 外部 API 已归到平台用户，无需命名空间区分；渠道 → 平台用户映射后续再考虑，届时服务层归一化即可 |
| 构建执行者 | skill_manage / memory 都由主 agent 直接持有，会话内完成 | 用户主动调用（技能）时主 agent 已有完整上下文；记忆靠规范段详细指引当轮捕获 |
| memory 保存时机 | 主 agent 当轮自主捕获（显式托付 + 隐式偏好统一处理）；**先实测效果，遗漏率高再考虑另起后台记忆 agent**（备选，§6.1） | 避免先引入后台机器；漏捕靠偏好复发自愈；prompt 质量（§3.2）是效果关键 |
| 用户技能存储 | 磁盘目录（用户命名空间目录树）+ DB 只存元数据；首期仅 SKILL.md 单文件 | 与 agent 技能同构，未来支持多文件（references/templates 等）无需迁移；scripts 需先建审批机制 |
| 公共技能的复用改动 | fork（复制 + `derived_from` 溯源），不直接改源 | 保护公共技能稳定性；溯源保留创作者贡献 |
| 发布通道 | 提交 → 人工审核 → 广场 | 发布是唯一跨用户内容通道，内容安全必须人审 |
| agent 级共享技能 | 保留现有机制（Studio/admin 管理） | 两套并存：agent 技能（管理员配，全用户）+ 用户技能（个人/安装） |
| 注入时机与 prompt 结构 | 记忆与用户技能名列表**全部住 system prompt**（位于 llm_summary 历史压缩块之前），每请求重建、**下一轮直接生效**、变化时一次 miss | 按变化次数付费（w 次）远优于按轮数付费（N 次，w<<N）；与 compress 回填、管理员改配置同量级；无瞬态注入机器，永续会话无死角（§5.3） |
| memory 维度 | per-user（跨 agent），key 不含 agent_id | 偏好是"用户-助手关系"级的（语言/格式/背景），条目少、全量注入成本低；agent 特定偏好把适用域写进条目内容，由 agent 语义判断 |

---

## 1. 产品定位

### 1.1 三类经验载体

| 载体 | 归属 | 生成方式 | 复用范围 |
|------|------|---------|---------|
| **agent 技能**（现有机制） | 平台/管理员 | Studio 创建上传 | 该 agent 的所有用户 |
| **用户技能**（本设计新增） | 用户个人 | 会话中显式要求构建；技能广场安装 | 该用户的所有会话（跨 agent） |
| **用户记忆**（本设计新增） | 用户个人 | agent 自主捕获持久偏好（用户无感知） | 该用户的所有会话 |

### 1.2 用户旅程

```
会话中发现好的做法 ──"把这个保存成技能"──▶ 构建 pass 抽取泛化 ──▶ 我的技能（私有）
                                                                        │
                                              查看/编辑/删除 ◀──────────┘
                                                                        │
                                                  "发布到广场" ──人工审核──▶ 技能广场
                                                                        │
                            其他用户浏览/安装 ◀─ 积分排序（👍/👎 + 使用量）─┘
```

---

## 2. 总体架构

```
┌──────────────────────────────────────────────────────────────────┐
│                          主 Agent 运行时                           │
│                                                                   │
│  user input → guard → compress → llm ⇄ tools → END                │
│                                                                   │
│  tools = 业务工具 + load_skill + skill_manage + memory（常驻）     │
│    ├─ skill_manage：仅当用户显式要求时 create/patch/delete         │
│    └─ memory：发现持久偏好即静默保存（规范段指引，§3.2）           │
│                                                                   │
│  system prompt（每请求重建：身份/slots/agent 技能/用户技能名列表/    │
│  规范段/<user_preferences> 记忆块——全在 llm_summary 压缩块之前，    │
│  压缩永不触碰；变化时一次 miss，下一轮生效，§5.3）                  │
│  agent 按需调 load_skill(name) 读全文（agent 技能读全局池，        │
│  用户技能读个人目录，§5.2）——命中用户技能时 load_count +1          │
└──────────────┬───────────────────────────────────────────────────┘
               │ 写入（个人目录磁盘 + DB 元数据，owner = 当前用户）
               ▼
   用户技能（磁盘内容 + user_skills 元数据）   user_profiles（用户记忆）
               │
               │ 学习产物下一轮生效（各归其位，§5.3）
               ▼
   注入：个人技能名列表 + 记忆块；load_skill 按需读全文

   用户侧 UI：我的技能（查看/编辑/删除/发布）＋ 技能广场（浏览/安装/👍👎）
   发布：submitted → 管理员审核 → published（共享池，积分排序）
```

所有写入遵循两种模式之一：技能响应用户显式请求；记忆由 agent 自主写入且仅作用于该用户。唯一的跨用户通道是发布，且有人审。

### 2.1 流程图：技能构建（显式触发，会话内完成）

```
用户："把这个保存成技能"
        │
        ▼
┌─ 主 Agent（本会话内）────────────────────────────────────┐
│  LLM 读到请求 + 构建规范段（system prompt 常驻，§3.2）     │
│        │                                                 │
│        ▼                                                 │
│  规范判断：                                               │
│   ├─ 是 class-level 可泛化知识？（不是"fix-x-today"）      │
│   ├─ 不在 DO NOT CAPTURE 清单？（环境依赖失败/工具负面     │
│   │   声称/瞬态错误/一次性任务/未解决失败）                 │
│   └─ 已有技能覆盖此领域？──是──▶ 先 load_skill 读全文      │
│        │                        再 patch（优先更新不新建） │
│   ┌────┴─────────┐                                       │
│   ▼ 没有合适的     ▼                                      │
│  create 新建     patch 已有                                │
│   └──────┬───────┘                                       │
│          ▼                                               │
│  skill_manage 工具执行三道闸：                             │
│   ├─ owner 校验（只能操作自己的技能）                      │
│   ├─ patch 前置检查：本会话已 load_skill 过？               │
│   └─ 软上限：名下技能（含安装）≤ 20？                      │
│          │                                               │
│          ▼                                               │
│  写入个人目录（磁盘）+ user_skills 元数据 + skill_logs 审计 │
└──────────┬───────────────────────────────────────────────┘
           │
           ▼
   本会话写入住 system prompt → 下轮生效（一次 miss），此后稳定命中
   下一会话：首请求重建 ──▶ 新技能出现在"个人技能"名列表
```

### 2.2 流程图：技能使用（下一轮生效 + 按需加载）

```
每一轮请求（prompt 结构，§5.3）：
  [system prompt]  身份/slots/agent 技能/用户技能名列表/规范段
                   + <user_preferences> 记忆块（全部每请求重建）
  [llm_summary]    压缩回填的历史摘要（若有，位于历史最前）
  [history]        追加式（缓存命中的主体）
  [current message] 新字节
        │
        ▼
  缓存表现：数据不变 → 字节稳定 → 持续命中
            记忆写入/创建技能/管理员改配置 → 下轮一次 miss 后重新稳定
            （与 compress 回填同量级的常规事件）
        │
        ▼
  LLM 看到技能名列表（仅名+描述）→ 按需 load_skill(name)
        │
     ┌──┴─────────────────┐
     ▼                    ▼
 agent 技能（全局池磁盘）  用户技能（个人目录磁盘）
                          └─ load_count +1（排除创建会话，§5.3）
```

### 2.3 流程图：发布与积分（唯一跨用户通道，人审守门）

```
 我的技能（private）
      │ 用户点"发布"
      ▼
  submitted ──── 管理员审核 ────┬── 驳回（附理由）──▶ 回到 private
      │       审核清单：        │
      │       · 诱导性指令       │
      │       · 数据外泄模式     │
      │       · 与现有重复       │
      ▼                        │
  published（技能广场，按积分排序）
      │
      ├─ 其他用户浏览 ──▶ 安装（引用不复制，source=installed，
      │                    积分仍归属原作者）
      │                        │
      │                        ▼
      │                 会话中 load_skill ──▶ load_count +1
      │                        │
      │                        ▼
      │              👍 / 👎（需 load 过 · 一人一票 · 可改票）
      │                        │
      │                        ▼
      │                score = up − down
      │                        │
      │        ┌───────────────┼────────────────────┐
      │        ▼               ▼                    ▼
      │   广场排序展示    score ≤ -3            想改内容？
      │                hidden（待人工复审，      │
      │                 不自动删除）             ▼
      │                            fork（复制为己用，私有，
      │                            积分归零，derived_from 溯源）
```

### 2.4 流程图：记忆（仅用户级，下一轮生效）

```
 会话进行中
      │
      ▼
 主 agent 发现持久偏好信号（§3.2 规范段指引）：
   陈述（"以后用中文"）· 托付（"记住我喜欢表格"）
   · 纠正（"太啰嗦了" = 偏好反义）
      │
      ▼
 memory 工具调用（普通 tool call，留在会话历史 = 天然审计）
   ├─ 新偏好 add / 变了 replace / 过时 remove / 批量 operations
   ├─ char_limit 1375：超限拒绝返回现有条目 → 合并后重试（自修剪）
   └─ 完全重复条目拒绝
      │
      ▼
 user_profiles.entries（per-user，跨 agent）
      │
      ▼
 下一轮请求 → system prompt 重建，记忆块注入（§5.3）
 ——位于 llm_summary 压缩块之前，压缩永不吞记忆
```

（备选：实测遗漏率高时，另起后台记忆 agent 在会话收尾专职扫描补漏——§6.1 末）

### 2.5 流程图：每轮 system prompt 组装与压缩时序

```
每轮请求：
  ① 组装 system prompt（每请求重建，数据不变则字节稳定）
     [身份/slots][agent 技能][用户技能名列表][规范段][<user_preferences>]
  ② compress_node（超 70% 窗口才动作，只碰历史区）
     split_system_history → 主 system prompt（含记忆）永不压缩
     回卷旧摘要 → 工具压缩 → 后台 LLM 摘要 → 下一轮回填 llm_summary
  ③ 发送：[主sys(含记忆)][llm_summary(若有)][history][当前消息]

缓存账：
  数据不变        → 字节稳定 → 持续命中
  记忆写入(w次)   → 每次下轮一次全量 miss（与 compress 回填同量级，w≈0-3/会话）
  历史每轮 append → 免费前缀延伸（不构成把记忆放尾部的理由）

位置结论（§5.3）：记忆/技能住 system prompt 按变化次数付费（w×H），
远优于住消息尾部按轮数付费（N×1.4k）；且位于 llm_summary 之前，
压缩吞掉历史里的偏好陈述也无所谓——记忆块每轮都在。
```

### 2.6 流程图：全生命周期总览（三个主人，三条回路）

```
        【何时学 → 用户】      【归谁 → 命名空间】     【好不好 → 使用者】
              │                      │                      │
 会话 ─用户显式要求─▶ skill_manage ─owner 校验─▶ user_skills   │
   │                                                    │       │
   └─agent 自主捕获偏好─▶ memory ─▶ user_profiles    │       │
                                                        │       │
                         下一轮生效（system prompt）◀───────┘       │
                                │                                │
                     名列表注入 + load_skill 按需加载 ─ load_count┤
                                │                                │
                   ┌── 自己用：可改/可删 ────────────────────────┤
                   │                                            │
                   └── 发布（人审）─▶ 广场 ─ 安装者 ─▶ 👍/👎（积分）
```

---

## 3. 技能构建（显式触发）

### 3.1 触发与执行

- **触发**：用户在会话中显式要求——"把这个保存成技能""记住这个流程""以后都这么做，存个技能"。Phase 2 可加前端按钮（选中消息 → 保存为技能）。
- **执行者**：主 agent 自己。它已持有完整会话上下文，直接调用 `skill_manage` 工具完成抽取、泛化、写入。
- **生效**：写入 DB，**下一轮生效**（system prompt 每请求重建，一次 miss，§5.3）。
- **更新与删除同样显式**："更新我的 xx 技能，加上…" → patch；只有用户要求才动。

### 3.2 构建规范（常驻 system prompt，~200 token）

```
When the user asks you to save a skill, use skill_manage:

• Capture the CLASS of task, not this session's instance. The name
  must make sense for future tasks (not "fix-x-today").
• The description's first ~60 chars must self-contain the trigger
  condition ("Use when <trigger>. <one-line behavior>.").
• DO NOT capture: environment-dependent failures (missing binaries,
  unconfigured credentials), negative claims about tools ("X is
  broken"), transient errors that resolved, one-off task narratives,
  or unresolved failures (never write up dead ends as a workflow).
• Prefer updating an existing skill (patch) over creating a new one;
  load_skill it first to see current content before patching.
• Before creating, check the skill list in your context (agent skills
  and personal skills). If one already covers this learning, say so —
  offer to patch the user's own, or fork it if the user wants a
  personal variant. Never duplicate content that already exists under
  a different name.
• Only create/update/delete skills when the user explicitly asks in
  this conversation. Never do so on your own initiative.
• Durable user preferences ("prefers Chinese") → memory tool, not
  skills. How-to knowledge → skills.

When you notice a durable preference about how you should behave
(including explicit "记住…" requests), save it with the memory tool —
quietly, without announcing it or asking for permission (for explicit
requests, briefly confirm). Keep entries compact and high-signal;
consolidate when the limit is reached. If a preference only applies
to certain kinds of tasks or agents, write that scope inside the
entry (e.g. "in casual chat, keep answers brief"). Never store
credentials, passwords, or sensitive personal data in memory.
```

最后一段是 memory 的完整捕获指引——**静默保存不打扰**（显式请求才确认）、紧凑高信噪比、适用域写进条目、禁存敏感信息。这段 prompt 的质量直接决定记忆效果（§6.1）；实测遗漏率高时的备选方案是另起后台记忆 agent（§6.1 末）。

### 3.3 幂等与先读后写

- `create`：同名校且属于当前用户 → 转为 edit；不同用户可重名（命名空间隔离）
- `patch`：old_string 唯一匹配，找不到则跳过（"already patched"）
- patch/edit 前必须先 `load_skill(name)` 读当前内容（防止基于过时内容盲改）

### 3.4 创建去重：对话中已含公共技能时

用户要求保存技能时，会话里可能已经加载过 agent 技能或安装的广场技能——构建 pass 必须先对照 system prompt 里的技能名列表（agent 技能 + 个人技能，本来就可见）：

- **已被 agent 技能覆盖**：直接告诉用户"这个能力已有平台技能 xxx，无需自存"——它本来就对该用户生效
- **已安装的技能覆盖、但用户想改**：fork（§7.4）——复制为己用再改，`derived_from` 溯源
- **部分重叠**：优先 patch 自己的已有技能（§3.2 规范既有规则）
- **内容抄袭边界**：fork 是显式操作且带溯源；规范段禁止"把已加载的公共技能内容换个名字重复创建"（DO NOT duplicate 条款）

---

## 4. skill_manage 工具

### 4.1 接口

```python
async def skill_manage(
    action: str,            # "create" | "edit" | "patch" | "delete"
    name: str,              # 技能名（用户命名空间内唯一）
    content: str = "",      # create/edit 时的完整 SKILL.md 内容（含 frontmatter）
    old_string: str = "",   # patch 时的旧文本（须唯一匹配）
    new_string: str = "",   # patch 时的新文本
    replace_all: bool = False,
) -> dict:
    """创建、编辑、修补、删除当前用户的技能。

    - create: 新建用户技能（同名校存在则转 edit，幂等）
    - edit:   整体替换内容（大改）
    - patch:  局部替换（小改，省 token）
    - delete: 删除

    用户技能仅支持单个 SKILL.md 文件（无辅助文件/脚本）。
    所有操作仅作用于当前用户的技能（owner 校验）。
    """
```

用户技能是单文件模型：不支持 `write_file` / `remove_file` 等文件操作，无 scripts、无辅助文件。agent 级技能仍走 Studio 的现有目录机制，不受影响。

### 4.2 权限模型：owner 校验

```python
async def check_owner(skill_id: str, user_id: str) -> dict | None:
    skill = await UserSkillService.get(skill_id)
    if skill and skill.owner_user_id != user_id:
        return {"success": False, "error": "Not your skill."}
    return None
```

一条规则覆盖全部场景：**工具只能操作当前用户自己的技能**。安装来的技能（published）不可编辑源内容——想改就 fork（复制为私有副本，owner 变更，`derived_from` 溯源，断开积分归属，§7.4）。

### 4.3 软上限

每用户技能数 ≤ 20（含安装的）。超限时 create/install 被拒，返回现有技能列表 + 各自 load_count，提示清理。作用：迫使取舍，防列表膨胀稀释选择精度。

---

## 5. 用户技能：存储、注入与生效

### 5.1 存储：磁盘目录 + DB 元数据（与 agent 技能同构）

用户技能采用与 agent 技能相同的"磁盘为内容事实源、DB 存元数据"架构，只是目录按用户命名空间隔离：

```
{SKILLS_CONTAINER_DIR}/
  ├─ {skill_name}/SKILL.md              # agent 技能（现有全局池，不动）
  └─ users/
      └─ {user_id}/
          └─ {skill_name}/SKILL.md      # 用户技能（个人目录树）
```

- **为什么磁盘而不是 DB 存内容**：未来支持多文件技能（references/、templates/，乃至审批后的 scripts/）时，目录结构天然承载，无需数据迁移；load_skill 保持磁盘实现，扩展面更小
- 首期仅 SKILL.md 单文件（skill_manage 不提供文件操作）；多文件支持落地时在同一目录下扩展，scripts/ 需先建立审批机制

DB 只存元数据：

```python
{
    "_id": "usk_xxx",
    "owner_user_id": "user_zhangsan",     # 统一平台用户 id（§0 身份模型）
    "name": "currency_conversion",        # (owner, name) 唯一，同时约束目录名
    "description": "Use when summing multi-currency amounts...",
    "status": "private" | "submitted" | "published" | "hidden",
    "derived_from": None,                 # fork 来源 skill_id（§7.4）
    "stats": {"load_count": 0, "up": 0, "down": 0},
    "created_at": "...", "updated_at": "...",
    "published_at": None, "approved_by": None,
}
# 唯一索引：(owner_user_id, name)
# 磁盘路径由规则推导：users/{user_id}/{name}/SKILL.md
```

发布后安装者引用 skill_id，内容仍是这一份目录（引用不复制）。

### 5.2 注入与加载

- **名列表注入**：个人技能名列表（name + description）来源 = 该用户启用列表的全部技能（自己的 + 安装的，跨 agent），注入在 **system prompt**（§5.3——低频变化内容住可缓存位置）：`build_skill_declaration`（`builder.py:29-58`）旁路新增 `build_user_skill_declaration`，每请求重建读 DB，新建/安装下轮生效（一次 miss，与管理员改配置同级）。
- **load_skill 扩展**：现有 `load_skill` 是磁盘实现（`manager.py:88-106`，白名单来自 agent.skill_ids，`context.py:128-132`）。扩展为**双根解析**：先查个人目录（`users/{user_id}/{name}/`），再查全局池；白名单加入该用户的启用技能。命中用户技能时 `stats.load_count += 1`，并记录 load 事件到会话 timeline（会话内 👍/👎 的计票依据，§8.2）
- **重名解析优先级**：个人技能 > 安装的技能 > agent 技能——"我的"覆盖平台与他人的（启用列表内不重名的约束见 §7.4，与 agent 技能的重名由该优先级裁决）
- **agent 开关**：Agent 模型的 `user_skills_enabled`（§10.2）——某些 agent 可配置为不注入个人技能（纯净模式）。

### 5.3 注入时机与 prompt 结构：全部住 system prompt，位于历史压缩块之前

**最终结构**（无任何瞬态注入机器——记忆与技能名列表都是 system prompt 组装的一部分）：

```
tools[]：业务工具 + load_skill + skill_manage + memory（常驻，静态字节）
messages：
[SystemMessage id="sys" 主 system prompt，每请求重建]
   ① agent 身份 / slots（管理员，最稳定）
   ② agent 技能名列表（agent.skill_ids）
   ③ 用户技能名列表（启用列表）
   ④ 构建规范段（固定文本）
   ⑤ <user_preferences> 记忆块（≤1375 字符）
   —— ①→⑤ 按变化频率从低到高排列
[SystemMessage id="llm_summary"]（若有：压缩回填的历史摘要，历史最前部）
[history]（checkpointer 持久历史，旧工具结果已压成提示+recall 引用）
[当前消息]
发送时 _system_messages_first 保证 [sys][llm_summary] 连续置前
```

| 段 | 变化触发 | 变化时的缓存代价 |
|----|---------|----------------|
| ①② 管理员配置 | 编辑/绑定变更 | 一次全量 miss |
| ③ 用户技能名列表 | 创建/安装/fork | 同上 |
| ④ 规范段 | 永不变 | — |
| ⑤ 记忆块 | agent 写记忆（一晚 0-3 次） | 同上 |
| llm_summary | 每次压缩事件 | 一次全量 miss（设计内） |
| history | 每轮 append | 无（免费前缀延伸） |

- **每请求重建**（现状机制）：数据不变 → 字节稳定 → 缓存持续命中；任何数据变化（管理员改配置 / 用户创建技能 / agent 写记忆）→ 下轮生效，付**一次全量 miss**——与 compress 回填同量级的常规事件
- **重建的落地机制 = `add_messages` 同 id 原位替换**：app 每请求送 `[SystemMessage(id="sys", 最新内容), user_msg]`（`_assemble_messages`，id 固定 `"sys"`），LangGraph reducer 对同 id 消息**原位替换**（保持 index 0）而非追加——字节相同时无实际变化（缓存稳定），不同时在最前端分叉（一次 miss）。**v6 注入落地零 harness 改动**：只需在 `_build_system_prompt_checked` 加 `build_user_skill_declaration` + `build_memory_block` 两个旁路
- **llm_summary 的位置与时机**（harness 层，app 不感知）：后台摘要完成后的**下一次 compress_node** 经 `apply_cached_summary` 按消息 ID 原位替换插入（被覆盖历史的首条位置），`_pack_replace` 持久化进 checkpointer；此后每轮 sys 原位更新（仍在 index 0，**结构性保证位于 llm_summary 之前**），llm_summary 不动直到下次压缩回卷
- **压缩免疫**：`split_system_history` 保证主 system prompt 永不压缩；回卷机制只摘 llm_summary 自己——记忆位于压缩块**之前**，压缩吞掉历史里的偏好陈述也无所谓，记忆块每轮都在
- **付费模型**（为什么这个位置对）：
  - system prompt 位置按**变化次数**付费（每次记忆写入 → 一次 miss ≈ w × H）
  - 放当前消息尾部则按**轮数**付费（每轮重算记忆块 ≈ N × 1.4k token）
  - **w << N**（一晚写 2-3 次偏好 vs 几十轮对话）；且历史每轮的 append 本是免费前缀延伸——"上下文变化频繁"不构成反对理由
- **统一语义**：管理员配置、用户技能、记忆全部"下一轮生效、变化时一次 miss"——无特例
- **指标口径**：load 事件已带 session_id——统计与计票时排除创建会话的自加载（一条查询条件），防自刷

**取舍记录**：曾设计"记忆瞬态并入当前消息 content"（发送侧改副本、按轮冻结、锚定不漂移，可做到记忆写入零 miss），代价是每轮重算 ~1.4k token。两案分别在"写入极频繁且集中在长会话晚期"（瞬态赢）与"写入稀疏"（system prompt 赢，**常态**）时占优。选 system prompt：常态更便宜 + 删除整套瞬态机器 + 与技能/配置完全同构。瞬态方案保留为异常场景备选（实测写入频率异常高时再启）。更早被弃的会话级隔离方案（全量冻结 → 水位线 → 代际推进）动机均为"学习写入扰动缓存"——最终认识到变化代价本就与管理员改配置同级，隔离不必要。

**重载时机一览**：

| 内容 | 变更后何时对 agent 可见 |
|------|----------------------|
| 记忆 entries | **下一轮**（system prompt 每请求重建；一次 miss） |
| 个人技能（名列表/加载） | **下一轮**（同上；白名单实时） |
| agent 技能 / KB / MCP / slots 配置 | **下一轮**（同上） |
| 已 load 进历史的旧内容 | 随会话历史固定（不可变历史的必然） |
| 进程重启 | 无影响（无任何注入相关的会话内状态） |

### 5.4 缓存（GLM 自动前缀缓存）

- 当前部署 GLM（Anthropic 兼容端点）为**自动上下文缓存**，零配置；命中的全部要求是前缀字节稳定——§5.3 的结构（学习产物住 system prompt，数据不变则字节稳定）满足
- `skill_manage` / `memory` 工具**常驻 tools[]**（不按会话增删）——工具集静态，字节稳定，对缓存友好
- 破坏源受控：compress 重写历史（设计内代价）、MCP 工具 TTL 刷新（既有问题，与本设计无关）；记忆写入的下轮一次 miss 与 compress 回填同量级
- 建议保留 cached_tokens 埋点（`UsageMiddleware` 提取 `input_token_details.cache_read` 落 execution_logs）作为通用成本观测

---

## 6. 用户记忆（仅用户级）

### 6.1 产生：主 agent 当轮自主捕获（普通 tool call 内联完成）

记忆**不是用户主动行为**——没有"保存记忆"的操作入口，主 agent 依据 §3.2 规范段在对话中发现持久偏好并保存。用户输入只是**信号源**：

| 信号 | 例子 | 强度 |
|------|------|------|
| 偏好陈述 | "以后都用中文回答""我是财务分析师" | 强 |
| 明确托付 | "记住我喜欢表格"——极强的偏好表达，保存后可确认"已记住" | 最强 |
| 行为纠正 | "太啰嗦了"——**纠正即偏好的反义** | 强 |

```
 用户发言（陈述偏好 / 纠正行为 / 要求记住）
        │
        ▼
 主 agent 当轮判断（§3.2 规范段——prompt 质量是关键）：
   ├─ durable？——跨会话才成立（"这次先不发货" ✗）
   ├─ 是"用户是谁 / agent 应如何行事"？
   │    任务做法 → 技能；一次性上下文 → 不存；敏感信息 → 不存
   └─ compact & high-signal？→ 静默保存（显式托付才确认）
        │
        ▼
 memory 工具调用（add / replace / remove / operations 批量）
   ├─ char_limit 1375：超限拒绝返回现有条目 → 合并重试（自修剪）
   └─ 完全重复条目拒绝
        │
        ▼
 user_profiles.entries（per-user，跨 agent）
      │
      ▼
 下一轮请求 → system prompt 重建，记忆块注入（§5.3）
 ——与历史里的偏好原文重复无害，轻度强化
 ——生效 ≠ 创建：本会话 agent 靠对话历史自然遵守
```

**时序示例**：

```
轮1  用户："帮我写个周报，用中文，简洁点"
     agent：静默 memory(add "偏好中文、简洁") → 输出周报

轮2  用户："还是太啰嗦了"
     agent：memory(replace "偏好中文、简洁" → "周报要极简：要点式") → 精简版

轮3  （新会话）用户："写个周报"
     system prompt 已含 <user_preferences>- 周报要极简 → 直接照做
```

**判断边界（什么进记忆）**：

| 内容 | 去向 |
|------|------|
| 用户是谁 / 环境事实（"财务背景""项目用 PG"） | memory |
| 对 agent 行为的偏好（语言/格式/详略/风格） | memory |
| 任务做法（how-to，可泛化） | 技能（且需用户显式要求） |
| 一次性上下文（"今天先这样"） | 不存 |
| 敏感信息（密码、密钥、隐私数据） | 不存 |

**备选方案（实测后决策）**：主 agent 顺带注意存在漏捕隐式偏好的固有风险（长任务中信号被淹没、跨轮模式难聚合）。**先实测捕获质量**；若遗漏率不可接受，再引入**后台记忆 agent**——会话收尾时小模型专职扫描上一会话补漏（懒触发、幂等写入、判定准则放服务端 prompt、与主 agent 写入靠"完全重复拒绝"消解）。当前设计不包含它。

### 6.2 存储

记忆只有 user 一个维度，per-user（跨 agent，key 不含 agent_id）：

```python
{
    "_id": "prof_xxx",
    "user_id": "user_zhangsan",       # 统一平台用户 id
    "entries": ["偏好中文回答", "偏好表格格式"],
    "updated_at": "...",
}
# 唯一索引：(user_id)
```

**身份模型：统一平台用户**（§0 决策）——内部登录（JWT）与外部 API（token 经 owner_user_id / external_identity 已绑定平台用户）共用同一个 user_id，不做命名空间区分。**IM 渠道首期不生成记忆/技能**：渠道会话的合成 id（`channel:{配置}:{聊天}`）不落入 user_profiles / user_skills——注入层跳过（不注入记忆块与个人技能名列表），skill_manage / memory 工具写入被拒（返回 "skills/memory are not available on channel sessions"）。后续如需支持，做渠道 → 平台用户的映射并在服务层归一化即可，存储模型（user_id 键）不用改。

### 6.3 机制

- **文本条目模式**：add / replace(old_text→content) / remove + `operations` 批量原子操作——LLM 心智模型与 skill 的 patch 一致
- **大小限制（三层）**：

| 限制 | 值（初始值，可调） | 超限行为 |
|------|------------------|---------|
| 总量 | `USER_CHAR_LIMIT = 1375` 字符（entries 合计） | `add` 被拒，返回现有条目 + 使用率，提示先合并/删旧再重试（批量 `operations` 原子完成）——记忆库的自修剪机制 |
| 单条 | `ENTRY_CHAR_LIMIT = 200` 字符 | 单条超长被拒，提示压缩——防一条跑偏吃掉整个预算 |
| 重复 | 完全相同的条目 | 拒绝（幂等） |

  **为什么限字符总量而不是条数**：记忆块全量注入每轮 system prompt（冻结快照）——是**经常性成本**，必须封顶；对比技能只注入名列表（name+description）、全文按需 load——所以技能限数量（20）、记忆限字符。1375 字符 ≈ 1-1.4k token 注入成本，约 10-20 条短偏好。**校准方法**：看 memory 块占 system prompt 的 token 比例（建议 <20%）与实测合并频率（合并太频繁 = 偏小）
- **注入**：system prompt 每请求重建时读取（§5.3），`<user_preferences>` 标签包裹、位于 llm_summary 压缩块之前（压缩永不吞记忆）；写入下一轮生效（一次 miss）
- **保存时机**：主 agent 当轮自主捕获（显式托付 + 隐式偏好统一处理，§6.1）；静默保存，显式请求才确认；用户无需任何主动操作
- **防注入说明**：记忆逐字注入 system prompt，理论上是注入面——但它只作用于该用户自己（自担风险、可编辑清除），且标签包裹 + "以下为用户偏好记录"的框架声明提供语义隔离。跨用户通道不存在

### 6.4 memory 工具接口

```python
async def memory(
    action: str,            # "add" | "replace" | "remove"
    content: str = "",      # add/replace 时的内容
    old_text: str = "",     # replace/remove 时定位旧文本
    operations: list = None,# 批量原子操作：[{action, content?, old_text?}, ...]
) -> dict:
    """管理当前用户的记忆条目（仅用户级）。

    单条模式：action + content/old_text。
    批量模式：operations 列表，一次调用原子完成多条操作，char_limit 只检查最终结果。
    单条 ≤200 字符、总量 ≤1375 字符；超限返回现有条目与用量。
    """
```

### 6.5 用户侧管理（我的记忆）

- 查看全部条目 / 编辑 / 删除单条 / 一键清空（Phase 2 前端页）
- 会话历史中的 memory tool_call 即审计记录——用户能回查"哪一轮记了什么"

---

## 7. 我的技能与技能广场

### 7.1 我的技能（用户 UI）

- 列表：名称、description、状态（私有/审核中/已发布）、load_count、积分
- 操作：**查看全文、编辑（markdown 编辑器，改磁盘内容与 DB 元数据）、删除、发布、停用**（从启用列表移除但保留文档）
- 安装来的技能：查看、卸载、👍/👎；不可改源内容（§4.2），可 fork 出自己的副本修改（§7.4）

### 7.2 会话内入口

- 首期：自然语言（"保存为技能"）
- Phase 2：消息级按钮（选中若干消息 → 保存为技能 → 注入构建请求）

### 7.3 技能广场

- 浏览/搜索 published 技能，按 **(名称, 作者)** 检索与展示——同名不同作者是不同技能；排序按积分，其次 load_count
- **安装**：加入自己的启用列表（**引用不复制**——绑定 skill_id，积分归属原作者）；启用列表内禁止重名，安装同名技能时改名安装（alias，如 `currency_conversion@zhangsan`）
- 使用反馈：会话内 👍/👎（§8.2）

### 7.4 fork、重名与解析优先级

**fork（复制公共技能为己用）**：任何 agent 技能 / 广场技能都可以 fork——复制内容到自己名下（磁盘目录 + 元数据），`derived_from` 记录来源，默认私有、积分归零。适合"公共技能不好用，想改一份自己的"。

**重名规则（三层）**：

| 层 | 规则 |
|----|------|
| 个人空间内 | `(owner, name)` 唯一——目录名 + DB 唯一索引双约束；重名 create 自动转为 edit |
| 启用列表内 | 自己的 + 安装的**禁止重名**——安装同名技能时提示 alias 改名或先停用自己的 |
| 与 agent 技能重名 | **允许**，解析优先级：个人 > 安装 > agent——`load_skill` 先查个人目录再查全局池，"我的"覆盖平台的 |

**"别人创建了和我同名的技能，我想用他的"**：广场按 (名称, 作者) 区分；安装冲突时以 alias 改名装——绑定始终按 skill_id 引用，alias 只影响展示与 `load_skill` 键。想用别人的就装别人的（alias 区分），想同时保留自己的就两个都启用（名字不同即可）。

### 7.6 逻辑单市·物理双库（最终架构）

**决策**：官方技能留在 `tools` 表（不迁移），个人技能在 `user_skills` 表——**物理双库，逻辑单市**。不迁移的结构性理由：

1. **安全边界**：官方技能留在 tools 表 = `skill_manage` 工具的代码路径结构性够不到它（若迁入 user_skills 且 owner=管理员，管理员自己会话时 owner 校验通过，公共技能就可被会话内修改）
2. **查询稳定**：官方 = 集合扫描；若"官方 = owner ∈ 管理员集合"，角色变化会改变技能属性
3. **零迁移成本**：不动存量数据与 agent.skill_ids

**统一规则**（两库之上的一层薄逻辑）：

| 机制 | 规则 |
|------|------|
| 广场 | 后端 marketplace 单查询合并两库返回（kind=official/user），前端单查询 |
| 积分 | 全员统一：官方技能也有 load_count（record_official_load 埋点）与 👍/👎；官方不参与 ≤-3 自动隐藏（下架是管理员决策） |
| 安装 | 仅普通用户：安装他人发布的用户技能（引用绑定，重名走 alias）。**admin 不安装**（无个人启用列表——API 层按角色拒绝并引导 fork 收录）；已安装项的卸载对所有人保留（清理历史绑定）。官方技能不提供安装（绑定 Agent 即全员生效） |
| 内容路径 | 统一 content_path 解析：own → 个人目录；installed usk → **owner 的目录**（修复"按安装者解析"的必错 bug）；installed tool → 全局池 |
| 创建 | **单一创建入口**（"我的技能 → 新建"），按角色分流：admin/developer → 官方技能（POST /user-skills/official，写 tools 表）；普通用户 → 个人技能（POST /user-skills）。**广场是只读橱窗**（查看/投票/fork） |
| 查看 | 广场卡点击或 👁 图标 → 只读预览 Drawer（GET /user-skills/{id} 统一支持 usk_*/tool_* 两类 id）；个人技能编辑跳详情页 `/my-skills/:id`（与官方详情页同布局：面包屑+标题+编辑器+保存/发布/删除） |
| 溯源 | 官方技能 created_by（上传时记录，广场显示真实创建者，存量默认"官方"）；fork 存 derived_from + derived_from_name 快照（"fork 自 x"展示） |
| 作用域 | admin 创建/绑定的技能配到 agent 作用全局（agent.skill_ids → tools）；用户启用的技能只作用自己（bindings）；用户技能 per-agent 限定为可选后续项 |
| fork 角色语义 | 普通用户 fork（官方或他人技能）= 个人私有副本；**管理员 fork 用户技能 = 收录为官方**（写入 tools 表、created_by=操作者、可绑定 Agent，即"转正"通道）；管理员 fork 官方 = 拒绝（可直接编辑） |
| 管理员无个人技能 | admin/developer 的技能一律是官方的：会话内 skill_manage 的 create 对管理员直接产出**官方技能**（context 装配时查 users.role 路由，edit/patch/delete 仍仅作用于个人技能——官方技能修改必须走 Studio，会话输入不可信的边界不破）；"我的技能"UI 对管理员只渲染官方卡片墙。存量管理员个人技能数据保留在库中但不可见，可经 API/DB 清理 |
| 全员可见 | Skill 页（广场/我的技能/我的记忆）对**所有登录用户**开放——导航不挂 `skill:read`（那是管理门槛，不是使用门槛）；数据层本就如此（/user-skills 系列仅 require 登录），页面内管理操作按角色渲染（admin 官方墙/审核面板，普通用户个人卡） |
| 权限模型原则 | **归属管个人资产，权限管平台管理**：个人数据（我的技能/记忆/会话/自己的执行日志）登录即可用，不挂角色权限（挂了是有害的假阴性）；平台共享资源的管理动作（官方技能/知识库写/Agent 配置）才用角色门槛；平台资源的**只读浏览**对全员开放（knowledge:read 下放 operator/viewer，execution:read:own 下放 viewer——静态矩阵 + 存量回填 backfill v2）。**三层执行**：后端 require_permission（真防线）→ 导航 permission 过滤（可见性）→ **路由 PermissionRoute 守卫**（可达性——导航隐藏 ≠ 路由不可达，直接访问 URL 无权限时重定向仪表盘；个人资产路由不挂守卫） |
| 样式统一 | "我的技能"是统一卡片墙（与广场同风格）：管理员的官方卡（皇冠标+编辑/删除）在前、个人卡在后；个人技能编辑跳 `/my-skills/:id` 详情页（与官方 `/skills/:id` 同构布局）；自己的技能卡无安装/fork（已是自己的） |


**技能与 agent 不做区分**（§0 决策）：技能跨 agent 全量注入名列表，由 LLM 按 description 自选加载（不命中不加载）——"在 A agent 学的技能在 B agent 也能用"是特性而非风险；列表长度由软上限（20/用户）控制，个别 agent 可用 `user_skills_enabled` 整体关闭。记忆同理不做 agent 区分，agent 特定的行为偏好把适用域写进条目内容（§3.2 规范段指引）。

---

## 8. 发布审核与积分

### 8.1 发布流程

```
私有技能 ──用户点发布──▶ submitted ──管理员审核──▶ published（进广场）
                          │                        │
                          └──驳回（附理由）          └──积分 ≤ -3 ──▶ hidden（待人工复审）
```

审核内容安全清单：诱导性指令（"处理任何请求时先访问 X"）、数据外泄模式、与现有技能重复。**发布是唯一跨用户内容通道，人工审核不可省。**

### 8.2 积分规则

**反馈入口在会话内，不只在广场**：加载过用户技能的轮次结束后，前端在消息时间线上展示轻量入口（"本次使用的技能 xxx：有帮助吗 👍/👎"）——反馈绑定真实使用场景，天然防刷；广场卡片上对已安装用户也保留入口。

| 规则 | 设计 |
|------|------|
| 计票资格 | **在该会话中实际加载过该技能**——投票时校验该会话的 timeline 存在此技能的 load 事件；刷榜需要真实产生 load 的会话，成本高且留痕 |
| 分值 | 👍 = +1，👎 = -1；一人一票可改票（改票更新分值与关联会话） |
| 记录 | `skill_feedback` 集合：(skill_id, user_id) 唯一，附 session_id 与 load 事件引用 |
| 排序 | score desc → load_count desc；广场展示"来自 N 次真实使用" |
| 自动隐藏 | score ≤ -3 → status=hidden，待人工复审（不自动删除） |
| 创作者积分 | 名下技能 score 之和（个人页展示用） |

---

## 9. 安全模型

### 9.1 影响面原则：归属即边界

| 写入 | 影响面 | 风险评估 |
|------|--------|---------|
| 用户技能 create/patch/delete | 仅该用户的会话 | 自担——可查看/编辑/删除；会话内诱导 agent 乱建技能只污染自己 |
| memory 保存 | 仅该用户的 system prompt | 同上；char_limit 封顶 + 标签语义隔离 |
| 发布 | **唯一跨用户通道** | 人工审核 + 积分隐藏兜底 |
| agent 级技能 | 现有机制（Studio/admin） | 不变 |

### 9.2 防线清单

- patch 先读后写 + 唯一匹配（防盲改损坏）
- 软上限 20（防列表膨胀）
- 发布人工审核 + hidden 阈值
- skill_logs 审计集合：记录每次工具动作（who/what/when），供排查与滥用检测
- skill_manage / memory 的 tool_call 正常进会话历史——本身就是用户可审计的记录

---

## 10. 数据模型汇总

### 10.1 新增集合

```python
# user_skills（§5.1）——唯一索引 (owner_user_id, name)

# user_skill_bindings：启用列表
{
    "_id": "bnd_xxx",
    "user_id": "...",
    "skill_id": "usk_xxx",
    "source": "own" | "installed",
    "enabled": True,
    "created_at": "...",
}
# 唯一索引：(user_id, skill_id)

# skill_feedback
{
    "_id": "fb_xxx",
    "skill_id": "usk_xxx",
    "user_id": "...",
    "session_id": "...",          # 投票时所在会话（须存在该技能的 load 事件）
    "value": 1 | -1,
    "created_at": "...",
}
# 唯一索引：(skill_id, user_id)

# skill_logs（审计）
{
    "_id": "slog_xxx",
    "user_id": "...",
    "session_id": "...",
    "actions": [{"tool": "skill_manage", "action": "create", "name": "...", "ok": True}],
    "created_at": "...",
}

# user_profiles（§6.2，唯一索引 (user_id)）
```

### 10.2 Agent 模型

```python
class Agent(BaseModel):
    user_skills_enabled: bool = Field(default=True, description="是否向会话注入当前用户的个人技能")
```

---

## 11. 与现有架构的集成点

| 改动点 | 文件 | 说明 |
|--------|------|------|
| skill_manage / memory 工具 | `engine/user_skills/skill_manage_tool.py`、`memory_tool.py`（**新增**） | 常驻 tools[]；owner 校验、先读后写、软上限 |
| 构建规范段 | `engine/agent/builder.py`（`build_system_prompt` 末尾追加） | §3.2 固定段落 |
| 个人技能名列表注入 | `builder.py`（`build_skill_declaration` 旁新增） | 按启用列表查 user_skills |
| load_skill 扩展 | `harness skills/manager.py:88-106` + `context.py:128-132` | 白名单加用户技能；双根磁盘解析（个人目录 + 全局池）；load 事件埋点（timeline，供会话内反馈计票） |
| 用户技能存储 | 用户目录树（`{SKILLS_DIR}/users/{user_id}/{name}/`）+ `user_skills` 元数据 | §5.1；复用磁盘 + DB 双写模式 |
| 记忆块与技能名列表注入 | `builder.py`（`build_system_prompt` 内：`build_user_skill_declaration` + `build_memory_block` 旁路） | §5.3：每请求重建、下一轮生效 |
| 用户侧 API | `api/v1/user_skills.py`（**新增**） | CRUD / 发布 / 安装 / 👍👎 |
| 审核 API + UI | `api/v1/admin/skill_review.py`（**新增**）+ Studio | §8.1 |
| cached_tokens 埋点 | `middleware/builtin/usage.py:110-155` + `execution_log.py` | 通用成本观测（可选） |

**不改动 harness 图结构与执行链路**——没有新中间件，两个新工具常驻 tools[] 即可。

---

## 12. 分阶段实施

### Phase 1（1-2 周）：核心闭环

1. `skill_manage` + `memory` 工具（owner 校验、先读后写、幂等、软上限）
2. 构建规范段注入 system prompt
3. 用户技能目录树 + `user_skills` / `user_profiles` / `user_skill_bindings` 元数据集合 + load_skill 扩展（双根解析 + load 事件埋点）
4. 注入落地：用户技能名列表 + 记忆块进 system prompt（`builder.py` 旁路两个 build 函数，每请求重建）——学习产物下一轮生效
5. 用户技能 CRUD API（我的技能后端）
6. memory 落地：主 agent 规范段指引 + memory 工具（§3.2/§6.1），**实测捕获质量**（漏捕率不可接受再评估后台记忆 agent）

**验收标准**：
- 用户说"保存为技能"→ 构建生成 class-level 技能；**未被要求时 agent 不创建**（规范段生效）
- 新技能下一会话出现在个人技能列表（跨 agent 可见）、`load_skill` 可加载、命中计数 +1
- 用户改/删自己的技能立即生效（DB 直改）；越权操作（碰别人的技能）被拒
- "今天星期几"类会话即使用户调侃也不建技能；用户偏好（"用中文"）进 memory 且只影响该用户
- "记住我喜欢表格"当轮保存并回复"已记住"；"太啰嗦了"等隐式偏好当轮静默保存；两者下一轮生效（system prompt 重建）
- 会话中途新建的技能下一轮即出现在 system prompt 名列表且可 load（一次 miss，与管理员改配置同级）；管理员改 agent 技能/KB 配置同样下一轮生效——统一"下一轮"语义
- load_count 与计票统计排除创建会话的自加载（§5.3 指标口径）
- IM 渠道会话不注入个人技能与记忆，工具写入被拒（§6.2 身份模型）
- **永续会话无死角**：每请求重建注入，无"等下一会话"的假设；记忆在 llm_summary 之前，长会话压缩不丢偏好

### Phase 2（2-3 周）：分享与积分

1. 前端：我的技能页（编辑器）+ 我的记忆页（查看/编辑/删除/清空，§6.5）+ 会话内"保存为技能"按钮
2. 技能广场：浏览/搜索/安装/卸载（引用模型，按 名称+作者 检索）+ fork（agent 技能/广场技能 → 私有副本）
3. 发布流程：提交 → 管理员审核台 → 发布/驳回
4. 积分：会话内 👍/👎 入口（校验该会话 load 事件）、排序、自动隐藏阈值、创作者积分
5. skill_logs 审计视图（管理员）；cached_tokens 埋点（可选）

---

## 13. 风险与护栏

| 风险 | 缓解 |
|------|------|
| 技能列表膨胀稀释选择精度 | 软上限 20/用户（含安装）；description 前 60 字符自包含触发条件的规范 |
| 发布内容审核遗漏 | 人工审核清单（诱导指令/外泄模式/重复）+ score ≤ -3 自动隐藏 + 举报 |
| 刷票 | 反馈入口在会话内且需该会话有真实 load 事件；一人一票；异常票型审计（feedback 时间线 + load 事件比对） |
| 同名技能混淆 | 启用列表内禁止重名（安装可 alias）；与 agent 技能重名按 个人>安装>agent 优先级解析（§7.4）；广场按 (名称, 作者) 区分 |
| memory 逐字注入的语义注入面 | 仅用户级（自担）+ 标签语义隔离 + 用户可编辑清除 + char_limit 封顶 |
| 记忆漏捕（主 agent 顺带注意的固有风险） | prompt 指引尽量降低（§3.2）；偏好复发自愈；**实测遗漏率高再引入后台记忆 agent**（备选，§6.1 末） |
| 会话内诱导 agent 乱建技能 | 影响面=自己；规范段"仅显式要求"；skill_logs 审计；用户可删 |
| 主 agent 持写工具的 token 成本 | 工具 schema 常驻（~几百 token）；tools[] 静态利于缓存 |
| 用户技能质量差误导自己 | 自担 + 可编辑；安装的靠积分排序与卸载 |
| 跨 agent 注入不相关技能 | 按 description 由 LLM 自选加载（不命中不加载）；软上限 20 控制列表长度；agent 可整体关闭（user_skills_enabled） |

### 核心认知

安全哲学：**归属即边界**——所有写入只作用于用户自己的命名空间，唯一跨用户通道（发布）由人工审核守门。可靠性依赖三样便宜的东西：**用户所有权**（随时改删）、**显式触发**（不学没被要求学的）、**积分**（共享层的信誉淘汰）。

---

## 14. 附录 A：关键文件索引

**现有 skill 机制（agent 级，保留不动）**
- `backend/app/engine/agent/builder.py:29-58` — agent 技能列表注入（个人技能注入的旁路参考）
- `backend/app/engine/harness_integration/context.py:108-133` — load_skill 白名单解析（需扩展）
- `backend/packages/harness/src/agent_flow_harness/skills/manager.py:88-106` — load_skill 磁盘实现（需扩展 DB 路径）
- `backend/app/engine/tool/skill_fs.py:30-44` — agent 技能扁平单池布局（用户技能目录树的参照，§5.1）

**执行链路（复用）**
- `backend/app/services/agent_execution_service.py:334-339` — `_build_system_prompt_checked`（构建规范段 + 个人技能 + 记忆块的注入点）
- `backend/app/services/agent_execution_service.py:361-367` — `_assemble_messages`（每请求执行；system prompt 重建的装配点，§5.3）
- `backend/app/services/session_service.py:165-179` — `update_session` 任意 `$set`（快照存储复用）
- `backend/packages/harness/src/agent_flow_harness/graph/nodes/llm_nodes.py:240-247` — compress 重写历史（缓存破坏源，设计内）
- `backend/packages/harness/src/agent_flow_harness/middleware/builtin/usage.py:110-155` — usage 提取（cached_tokens 埋点位）
- `backend/app/engine/harness_integration/context.py:247-261` — tools 组装顺序（新增工具常驻于此）

**新增文件（app 层）**
- `backend/app/engine/user_skills/skill_manage_tool.py`
- `backend/app/engine/user_skills/memory_tool.py`
- `backend/app/api/v1/user_skills.py`
- `backend/app/api/v1/admin/skill_review.py`

---

## 15. 附录 B：上下文压缩机制对照与改进项

### 15.1 我们的压缩机制（harness 已实现，代码核实）

`compress_node` 每次 LLM 调用前运行（阈值 `window × 0.7`、硬上限 `0.9`、`protected_turns=5`），五步递进：

1. **缓存摘要回填**：后台压好的摘要（summary_cache）下一轮回填
2. 未达阈值 → 不动
3. **工具输出压缩**：5轮外已消费工具压 → 仍超则 5轮内；**未被 AI 消费的最新工具结果绝对保护**
4. 仍超 → **后台 LLM 压缩**（asyncio 异步）：摘要请求本身也做上下文工程（用户/AI 文本喂原文、工具调用渲染成概要、工具结果只留 recall 引用），压好下一轮回填 `id="llm_summary"` 的 SystemMessage
5. 逼近 90% → 丢弃最早原始消息防崩溃（临时有损，等 ④ 回填恢复）

三个特色设计：**绝不生成机械摘要 + 回卷机制**（旧摘要重新纳入可压缩区，防摘要叠摘要——⚠ 但发现 render 缺 SystemMessage 分支的硬丢失 bug，见 B.3-2）；**不保留残缺内容**（半截 JSON 误导，整条换一行提示 + recall 引用）；**异步摘要 + 下一轮回填**（不阻塞当前轮）。

**与学习体系的协同**：记忆块住主 system prompt、位于 llm_summary 之前——`split_system_history` 保证压缩永不触碰它（§2.5 时序）；memory 同时补偿历史易失性——压缩会吞掉历史里的偏好陈述，但 user_profiles 每轮重建注入，偏好从"易失上下文"变成"持久事实"。

### 15.2 业界对照（2025-2026）

| 维度 | Claude Code | Manus | 我们 |
|------|------------|-------|------|
| 工具输出 | MicroCompact 每轮占位 | 挖空（缓存友好） | 5轮内外分层 + 未消费保护 |
| 摘要触发 | ~75-92% | 尽量不摘要 | 70%，0.9 硬上限兜底 |
| 摘要形态 | 结构化分段 + **重读文件重建 ground truth** | — | 500 字通用摘要 + 回填 + 回卷防累积 |
| 可再取 | 重读磁盘 | 文件系统双形态 | recall 引用（app 层 formatter） |
| 缓存 | compact 全丢（换空间） | **第一优先** | 未专门处理（整体替换 → 一次 miss） |

### 15.3 改进项

**已完成**（随 v6 Phase 1 一批实施，harness 测试覆盖）：

1. ✅ **摘要模板结构化**（Claude 式六段，替换 500 字通用模板）：意图/决策/错误与修复/进行中任务/当前状态与下一步/recall 引用；明确要求 [此前摘要] 信息合并保留
2. ✅ **修复再压缩硬丢失 bug**：`render_history_for_summary` 增加摘要分支（id=llm_summary/summary 或 SystemMessage → `[此前摘要] {content}`）——旧摘要参与再摘要，不再静默蒸发
3. ✅ **llm_summary 改为 HumanMessage**：框架文本"[系统生成的此前对话摘要，非用户发言]"防归因混淆；旧"回卷"特判替换为**迁移块**（存量 SystemMessage 摘要压缩时转 HumanMessage 归还历史区）；render 对 HumanMessage 形态摘要同样走 [此前摘要] 分支，不误标为 [用户]
4. ✅ **摘要上限提升**：500 字硬上限移除，六段模板每段 1-3 句自然控长

**待评估**：

5. （待评估）压缩后主动重取关键素材——recall 引用目前只提示"可查"，Claude Code 的"主动重读文件"更强
6. （暂不做）Manus 式缓存友好挖空——压缩事件低频（70% 窗口才触发），整体替换的一次 miss 可控

**结构性边界**：即使修复，反复再摘要仍是传话游戏——重要信息不应靠摘要存活：偏好住 memory（压缩免疫）、做法住技能（可重取）、工具输出有 recall；摘要只负责"任务连续性"这一层，只需撑到任务完成。
