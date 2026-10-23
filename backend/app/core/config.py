"""Application configuration via Pydantic Settings."""
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings loaded from environment / .env file.

    Missing required fields (e.g. JWT_SECRET_KEY in production) cause startup failure
    with a clear Pydantic ValidationError.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    APP_NAME: str = "MEPER Agent"
    APP_ENV: str = "development"
    DEBUG: bool = False

    # MongoDB
    MONGODB_URI: str = "mongodb://localhost:27017"
    MONGODB_DB_NAME: str = "agent_flow"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Qdrant (vector store for vector-type knowledge bases).
    # Supports dense+sparse (BM25) hybrid search; requires Qdrant >= 1.10.
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str = ""  # optional; set if Qdrant requires auth

    # JWT
    JWT_SECRET_KEY: str = "dev-only-not-for-production-replace-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # CORS - comma-separated origins for the non-/ext API surface.
    # /api/v1/ext/* is always permissive (third-party embeds); everything
    # else uses this whitelist. Same-origin deployments (Caddy) need no
    # CORS entries; list dev server origins here instead.
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3001,http://localhost:5173"

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_JSON_FORMAT: bool = False

    # LangSmith tracing (optional — set API key to enable).
    # When LANGSMITH_API_KEY is set, LangChain/LangGraph traces are sent to smith.langchain.com.
    LANGSMITH_API_KEY: str = ""
    LANGSMITH_PROJECT: str = "agent-flow"

    # Model API Key encryption (Base64-encoded 32-byte AES-256 key)
    # Generate: python -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"
    MODEL_ENCRYPTION_KEY: str = ""

    # Task concurrency limits
    TASK_GLOBAL_MAX_RUNNING: int = 50
    TASK_USER_MAX_RUNNING: int = 5

    # Session token budget (cumulative tokens per session before the agent is blocked).
    # Agents can override via their own max_tokens field (0 = use this default).
    DEFAULT_SESSION_MAX_TOKENS: int = 20_000_000

    # LangGraph recursion limit — the max number of supersteps per graph run.
    # Each REACT iteration (LLM call + tool execution) consumes ~2 supersteps,
    # so 75 ≈ 37 tool-call rounds. Raise this for agents that legitimately
    # need many steps (multi-file exploration, deep research, etc.).
    AGENT_RECURSION_LIMIT: int = 200

    # Context compression (compress_node).
    # Protected turns: the most recent N user-assistant rounds are never
    # summarised — only older history is eligible. Tool results inside this
    # window are also protected (unless they exceed the threshold and have
    # been consumed by the AI).
    COMPRESSION_PROTECTED_TURNS: int = 5
    # Threshold: compression triggers when estimated context tokens exceed
    # context_window × this ratio.
    COMPRESSION_THRESHOLD: float = 0.7
    # Hard limit: when context tokens exceed context_window × this ratio,
    # early history is discarded to prevent exceeding the model's window
    # (the background LLM summary will backfill once ready).
    COMPRESSION_HARD_LIMIT_RATIO: float = 0.9

    # ── 文档水位线压缩（message / Task 文档的两级水位线，16MB BSON 硬墙）──
    # 阶段1 触发线（MB）：超过开始 preview+外置压缩（可逆），压回该线以下停。
    DOC_COMPACT_HIGH_MB: int = 10
    # 阶段2 丢弃线（MB）：阶段1 压完仍超则丢弃最早载荷条目（不可逆）。
    # 14→16MB 的缓冲留给两次检查之间的文档增长。
    DOC_COMPACT_DISCARD_MB: int = 14
    # 影子账本触发线（MB）：session.compaction_bytes（thread 侧压缩累计掉的
    # 原文体量 = session 永久保留的全文体量）累计超过即异步压缩该会话文档。
    # 取值低于 DOC_COMPACT_HIGH_MB 以预留 BSON 结构开销余量。
    DOC_COMPACT_SHADOW_TRIGGER_MB: int = 8
    # 单条 tool_result 写入硬上限（字符）：超出截断+标记（防极端单文档；
    # recall 走 tool_output_archives 不受影响）。
    TOOL_RESULT_MAX_CHARS: int = 100_000

    # ── 长任务巡检（beat）──
    # 慢任务警告阈值（分钟）：RUNNING 超过此时长发站内信+timeline 警告。
    TASK_SLOW_WARN_MINUTES: int = 30
    # 重复告警间隔（分钟）：同一任务的慢告警最小间隔。
    TASK_SLOW_WARN_REPEAT_MINUTES: int = 60
    # 孤儿判定（分钟）：RUNNING 且 updated_at 超过此时长视为孤儿 → FAILED。
    TASK_ORPHAN_MINUTES: int = 30
    # 完结任务 checkpoint 保留期（天）：completed/failed/cancelled 任务的
    # agent thread checkpoints 到期删除（0=禁用）。代价：到期后前端"节点
    # 执行明细"不可回看（任务结果/timeline 不受影响）。
    TASK_CHECKPOINT_RETENTION_DAYS: int = 30

    # Image multimodal input (chat attachments → LLM image_url blocks).
    # Per-turn image count cap; excess images degrade to text placeholders.
    IMAGE_MAX_PER_TURN: int = 4
    # Downscale long edge (px) before base64-encoding into the LLM message.
    IMAGE_MAX_EDGE: int = 2048
    # Per-image size cap AFTER downscaling (bytes); larger images are
    # re-compressed harder, and give up with a text placeholder.
    IMAGE_MAX_SIZE_BYTES: int = 1024 * 1024
    # Per-turn TOTAL budget (bytes of base64 source bytes, summed). This is
    # the hard guardrail against the 16MB BSON document limit — LangGraph
    # checkpoints serialize the whole message state into a single Mongo
    # document per superstep, so oversized multimodal messages would crash
    # the run with DocumentTooLarge. Tune per-image/count caps freely, but
    # keep this one comfortably below 16MB.
    IMAGE_MAX_TOTAL_BYTES: int = 8 * 1024 * 1024
    # Keep the most recent N images un-degraded when the compression layer
    # downgrades stale images out of context (0 = degrade all stale images;
    # each kept image still costs vision tokens on every turn).
    IMAGE_KEEP_RECENT_N: int = 0

    # Task scheduler (poll interval in seconds; set to 0 to disable)
    TASK_SCHEDULER_POLL_INTERVAL: int = 10

    # Trigger scheduler (poll interval in seconds; set to 0 to disable).
    # The trigger scheduler polls the triggers collection for due cron/once
    # triggers and fires them. Accuracy = poll interval (10s is plenty for
    # scheduled workflows). This replaces the previous Celery eta self-chain
    # design, which suffered from Redis visibility_timeout re-delivery on
    # long-eta (monthly) jobs.
    TRIGGER_SCHEDULER_POLL_INTERVAL: int = 10

    # Trigger 时区 — cron 表达式按此时区解释（"周四16:00"即该时区的 16:00）。
    # 与 celery timezone 保持一致；不依赖容器系统时区（部署容器默认 UTC，
    # 曾导致 next_trigger_at 相差 8 小时、触发钟点漂移到次日凌晨）。
    TRIGGER_TIMEZONE: str = "Asia/Shanghai"

    # Skill filesystem — root directory where Skill files are materialized.
    # Each official Skill lives under ``{SKILLS_CONTAINER_DIR}/{skill_name}/``.
    # 用户个人技能住 ``{HOMES_CONTAINER_DIR}/{uid}/skills/{name}/``（用户资产根，
    # 与 workspace 同级隔离但持久——不参与 workspace 的定期清理；沙箱挂载
    # 时官方池与当前用户的 skills 子目录各自只读挂入，无跨用户泄漏）。
    # None = derive from SKILLS_HOST_DIR (local dev).
    # Docker: set explicitly by docker-compose (e.g. /data/skills).
    SKILLS_CONTAINER_DIR: str | None = None
    # Host-side path for Skills (the one users configure in .env).
    SKILLS_HOST_DIR: str = "~/.agent-flow/data/skills"

    # 用户资产根（个人技能等持久数据）：``{HOMES_CONTAINER_DIR}/{uid}/skills/{name}/``。
    # None = derive from SKILLS_HOST_DIR 的同级目录 ``{parent}/homes``。
    HOMES_CONTAINER_DIR: str | None = None

    # Workspace filesystem — root directory for per-Session workspaces.
    # Layout: ``{WORKSPACES_CONTAINER_DIR}/{user_id}/{session_id}/{input,output,tmp}``.
    # None = derive from WORKSPACES_HOST_DIR (local dev).
    # Docker: set explicitly by docker-compose (e.g. /data/workspaces).
    WORKSPACES_CONTAINER_DIR: str | None = None
    # Host-side path for Workspaces (the one users configure in .env).
    WORKSPACES_HOST_DIR: str = "~/.agent-flow/data/workspaces"

    # Workspace retention — days to keep workspace files after Session deletion.
    WORKSPACE_RETENTION_DAYS: int = 30

    # Workspace quota — max bytes per workspace (default 500 MB).
    WORKSPACE_MAX_BYTES: int = 500 * 1024 * 1024

    # Knowledge Base filesystem — root directory where KB .md files live.
    # Each KB lives under ``{KB_CONTAINER_DIR}/{kb_id}/`` (tree-style: agents
    # explore it at runtime via kb_glob/kb_grep/kb_read, no index, no vector).
    # None = derive from KB_HOST_DIR (local dev).
    # Docker: set explicitly by docker-compose (e.g. /data/knowledge_bases).
    KB_CONTAINER_DIR: str | None = None
    # Host-side path for Knowledge Bases (the one users configure in .env).
    KB_HOST_DIR: str = "~/.agent-flow/knowledge_bases"

    # Agent avatars — root directory where uploaded avatar images live.
    # Each avatar is a single file ``{AVATARS_CONTAINER_DIR}/{agent_id}.png``
    # (overwrite on re-upload). Served read-only via StaticFiles mount.
    # None = derive from AVATARS_HOST_DIR (local dev).
    # Docker: set explicitly by docker-compose (e.g. /data/avatars).
    AVATARS_CONTAINER_DIR: str | None = None
    AVATARS_HOST_DIR: str = "~/.agent-flow/avatars"

    # Skill (Tool) avatars — root directory for uploaded Skill avatar images.
    # Each avatar is a single file ``{SKILL_AVATARS_CONTAINER_DIR}/{tool_id}.png``
    # (overwrite on re-upload). Served read-only via StaticFiles mount.
    # None = derive from SKILL_AVATARS_HOST_DIR (local dev).
    SKILL_AVATARS_CONTAINER_DIR: str | None = None
    SKILL_AVATARS_HOST_DIR: str = "~/.agent-flow/skill_avatars"

    # Knowledge Base tool limits (truncation / caps, aligned with langxin tree KB).
    KB_GLOB_MAX_RESULTS: int = 200
    KB_GREP_MAX_FILES: int = 50
    KB_GREP_MAX_MATCHES: int = 200
    KB_READ_MAX_BYTES: int = 16_384
    KB_MAX_FILE_SIZE: int = 2 * 1024 * 1024  # 2 MB per uploaded .md

    # ── Wiki mode (llmwiki-style compiled wiki on tree KBs) ─────────────
    # Batch read (glob pattern) total char budget + per-file sampling cap —
    # lets the builder skim a whole directory in one tool call.
    KB_WIKI_READ_BUDGET: int = 120_000
    KB_WIKI_READ_SAMPLE: int = 4_000
    # Max bytes a single kb_write may produce (page content safety cap).
    KB_WIKI_WRITE_MAX_BYTES: int = 256 * 1024

    # ── Vector Knowledge Base (RAG) ──────────────────────────────────────
    # Embedding/reranker are configured directly via env vars (base_url +
    # model + api_key) — they are platform-global singletons, so they don't
    # need Model table entries. Embedding is REQUIRED for vector KB to work;
    # reranker is OPTIONAL — retrieval degrades gracefully (skips rerank).
    KB_EMBEDDING_BASE_URL: str = ""
    KB_EMBEDDING_MODEL: str = ""
    KB_EMBEDDING_API_KEY: str = ""
    KB_RERANKER_BASE_URL: str = ""
    KB_RERANKER_MODEL: str = ""
    KB_RERANKER_API_KEY: str = ""

    # Qdrant collection (single shared collection; kb_id payload filters KBs).
    KB_QDRANT_COLLECTION: str = "kb_chunks"

    # Chunking — platform-level fixed defaults (token-based via tiktoken).
    KB_VECTOR_CHUNK_SIZE: int = 800       # tokens per chunk
    KB_VECTOR_CHUNK_OVERLAP: int = 100    # tokens of overlap between chunks
    KB_VECTOR_EMBED_BATCH: int = 64       # chunks per embedding API call

    # Retrieval — two-stage: hybrid recall (dense+sparse, RRF) → rerank → filter.
    KB_VECTOR_TOP_K: int = 5              # final results returned
    KB_VECTOR_RECALL_K: int = 20          # candidates before rerank
    KB_VECTOR_SCORE_THRESHOLD: float = 0.5

    # Vector KB upload limits.
    KB_VECTOR_MAX_FILE_SIZE: int = 50 * 1024 * 1024  # 50 MB per uploaded doc
    KB_VECTOR_ALLOWED_TYPES: str = "pdf,docx,pptx,xlsx,csv,md,markdown,txt,html,htm"

    # ── Vision model (optional, for image/scan PDF recognition) ──────────
    # When configured, images embedded in PDFs and scan-only pages are sent to
    # this OpenAI-compatible multimodal model for text extraction / description.
    # Same pattern as reranker: optional, degrades gracefully when unset.
    KB_VISION_BASE_URL: str = ""
    KB_VISION_MODEL: str = ""
    KB_VISION_API_KEY: str = ""

    # ── OCR fallback (RapidOCR, optional) ────────────────────────────────
    # When the vision model is NOT configured, RapidOCR is used as a local
    # fallback for recognizing text in images / scan pages. Set to False to
    # disable (scan pages will then be skipped like before).
    KB_OCR_ENABLED: bool = True
    KB_OCR_LANGUAGES: str = "ch"  # RapidOCR language: ch (中文+英文) / en / ...

    # ── Image extraction ─────────────────────────────────────────────────
    # Extract & store images from PDF pages into FileRef so they can be viewed
    # later in the chunk viewer / search results.
    KB_EXTRACT_IMAGES: bool = True

    @model_validator(mode="after")
    def _default_internal_dirs_from_host(self) -> "Settings":
        """Default container-internal dirs to host dirs when not explicitly set.

        - Local dev: user sets only ``*_HOST_DIR``; ``*_CONTAINER_DIR`` is None → derive from host.
        - Docker: docker-compose injects ``WORKSPACES_CONTAINER_DIR``/``SKILLS_CONTAINER_DIR`` explicitly.
        """
        import os
        # Expand ~ in host dirs so Docker can use them directly
        self.WORKSPACES_HOST_DIR = os.path.expanduser(self.WORKSPACES_HOST_DIR)
        self.SKILLS_HOST_DIR = os.path.expanduser(self.SKILLS_HOST_DIR)
        self.KB_HOST_DIR = os.path.expanduser(self.KB_HOST_DIR)
        self.AVATARS_HOST_DIR = os.path.expanduser(self.AVATARS_HOST_DIR)
        self.SKILL_AVATARS_HOST_DIR = os.path.expanduser(self.SKILL_AVATARS_HOST_DIR)
        if self.WORKSPACES_CONTAINER_DIR is None:
            self.WORKSPACES_CONTAINER_DIR = self.WORKSPACES_HOST_DIR
        if self.SKILLS_CONTAINER_DIR is None:
            self.SKILLS_CONTAINER_DIR = self.SKILLS_HOST_DIR
        if self.KB_CONTAINER_DIR is None:
            self.KB_CONTAINER_DIR = self.KB_HOST_DIR
        if self.AVATARS_CONTAINER_DIR is None:
            self.AVATARS_CONTAINER_DIR = self.AVATARS_HOST_DIR
        if self.SKILL_AVATARS_CONTAINER_DIR is None:
            self.SKILL_AVATARS_CONTAINER_DIR = self.SKILL_AVATARS_HOST_DIR
        return self

    # ── Transfer（资源导入导出 .afpkg 包）────────────────────────────────
    # 防护上限：包体大小 / 解压后总大小 / 解压文件数（防 zip 炸弹）。
    TRANSFER_MAX_PACKAGE_SIZE: int = 200 * 1024 * 1024   # 200 MB
    TRANSFER_MAX_UNPACKED_SIZE: int = 500 * 1024 * 1024  # 500 MB
    TRANSFER_MAX_FILE_COUNT: int = 10_000

    # ── Sandbox ──────────────────────────────────────────────────────────
    # Docker image used for bash tool sandbox execution.
    SANDBOX_IMAGE: str = "agent-sandbox:latest"

    # Sandbox resource limits.
    SANDBOX_MEM_LIMIT: str = "512m"
    SANDBOX_CPU_QUOTA: int = 100_000  # 1 CPU core (100000 μs quota per 100000 μs period)
    SANDBOX_TIMEOUT: int = 120  # seconds
    SANDBOX_MAX_OUTPUT_BYTES: int = 50 * 1024  # 50 KB stdout/stderr cap

    # 每进程最大并发沙盒容器数（harness DockerSandbox 进程级信号量）。
    # 0 = 不限。按内存估算：每容器 mem_limit（512m）→ 8 ≈ 4GB。注意 Celery
    # prefork 每并发槽位一个子进程，节点总上限 = worker 并发数 × 本值。
    SANDBOX_MAX_CONCURRENT_CONTAINERS: int = 8

    # 孤儿沙盒容器强删阈值（秒）。正常路径容器执行完即删；进程崩溃遗留的
    # 容器由 beat 巡检按此年龄清扫。须大于 SANDBOX_TIMEOUT 留足余量。
    SANDBOX_ORPHAN_MAX_AGE: int = 600

    # API/worker 启动时后台预拉沙盒镜像（缺失才 pull），首笔沙盒执行免付
    # 整镜像拉取耗时。失败只记日志不阻断启动。
    SANDBOX_PREPULL_IMAGE: bool = True

    # 复用模式：每工作区长驻容器（命令经 docker exec 执行），省每命令容器
    # 冷启动。False = 旧行为（每命令一次性容器），一键回退。工作区天然按
    # 用户划分 → 多用户不共容器；复用只发生在同一会话/任务内部。
    SANDBOX_REUSE_CONTAINER: bool = True

    # 进程内存活复用容器上限（LRU 驱逐最久未用；0 = 不限）。节点总量 =
    # worker 并发数 × 本值。须大于 SANDBOX_MAX_CONCURRENT_CONTAINERS
    # （LRU 驱逐需要有空闲容器可逐）。
    SANDBOX_MAX_CONTAINERS: int = 32

    # 复用容器闲置回收（秒）：容器内 last-used 超过此值 → beat 巡检删除。
    # 实际驻留 ≈ 本值 + 巡检周期（sweep-orphan-sandboxes，60s 一轮）。
    SANDBOX_CONTAINER_IDLE_TIMEOUT: int = 300

    # 复用容器寿命兜底（秒）：created-at 超过此值无条件删除。
    SANDBOX_CONTAINER_MAX_LIFETIME: int = 86400

    # When True, bash runs inside Docker container.
    # When False (default), bash degrades to host subprocess execution
    # (see SANDBOX_FALLBACK).
    SANDBOX_ENABLED: bool = False

    # Fallback gate when the sandbox is disabled or Docker is unavailable.
    # "local" (default, backward-compatible) degrades to host subprocess
    # execution — every fallback is logged as ERROR because the isolation
    # guarantees are gone. Set "never" to fail closed (refuse execution),
    # e.g. in production where host execution of LLM commands is unwanted.
    SANDBOX_FALLBACK: str = "local"

    # When True, legacy sessions (created before checkpointer) have their
    # MessageRecord history serialized into the thread on first access.
    # Once migrated the thread is non-empty and subsequent requests use the
    # thread as the single source of LLM context. Disable after all legacy
    # sessions have been migrated.
    MIGRATE_LEGACY_SESSIONS: bool = False

    # Network mode for sandbox containers.
    # "none" = no network access (most secure, default)
    # "bridge" = standard Docker bridge network (allows outbound internet)
    # "host" = use host network stack (least isolation)
    SANDBOX_NETWORK_MODE: str = "none"

    # Network mode for governed-tool code execution (send-email etc.).
    # Tools are reviewed & enabled by admin and functionally need outbound
    # network (SMTP/HTTP), so they default to "bridge" — unlike the LLM bash
    # sandbox which stays network-isolated. Process isolation still applies:
    # tool code cannot read worker env (secrets/keys) or the host filesystem.
    TOOL_SANDBOX_NETWORK_MODE: str = "bridge"

    # Mount the current workspace (input ro / output & tmp rw) into the
    # governed-tool code sandbox so code tools can read uploaded/upstream
    # files and write artifacts to output/ (auto-registered as node files).
    # Governance kill-switch: set False to revert to the no-mount sandbox
    # (code tools compute-only, stdout-only results).
    TOOL_SANDBOX_MOUNT_WORKSPACE: bool = True

    # Container-internal mount points for sandbox containers.
    # These are the paths *inside* the sandbox container where workspace
    # and skill directories are mounted.
    SANDBOX_CONTAINER_WORKSPACE_DIR: str = "/workspace"
    SANDBOX_CONTAINER_SKILLS_DIR: str = "/data/skills"

    # ── run_code（代码即工具编排）───────────────────────────────────────
    # 总开关。False 时 run_code 不注入任何 Agent（名单层直接跳过）。
    RUN_CODE_ENABLED: bool = True

    # True（默认）= 受限模式：builtins 白名单 + import 模块白名单
    # （json/math/re/...），禁文件/网络/os。False = 开放模式，信任生成代码
    # （与 bash 工具同级风险）。
    RUN_CODE_RESTRICTED: bool = True

    # run_code 整体执行超时（秒）。批量查几十人通常几十秒内，180s 留余量。
    RUN_CODE_TIMEOUT: int = 180

    # run_code 内单次工具桥接调用（tools.call / call_many 单批）的超时（秒）。
    RUN_CODE_CALL_TIMEOUT: int = 60

    # run_code stdout 返回给 LLM 的字节上限（超限截断并标记）。
    RUN_CODE_MAX_OUTPUT_BYTES: int = 50 * 1024

    # ── Channels (inbound IM integrations) ──
    CHANNEL_SEND_MAX_RETRIES: int = 3
    CHANNEL_DEGRADED_ON_CONSECUTIVE_FAILURES: int = 5

    # ── Channels / long-connection (no-public-URL receive mode) ──
    # Per-provider master switches. Set to False to disable long-connection
    # entirely for a provider (channels fall back to webhook mode).
    CHANNEL_LARK_LONG_CONNECTION_ENABLED: bool = True
    CHANNEL_DINGTALK_LONG_CONNECTION_ENABLED: bool = True
    CHANNEL_WECOM_LONG_CONNECTION_ENABLED: bool = False  # no SDK yet
    CHANNEL_CONNECTION_RECONNECT_INTERVAL: int = 10  # seconds between retries

    # ── Channels / IM 会话延续 ──
    # channel:{ch}:{chat} 身份域内复用最近活跃 session（单聊连续多轮、群聊
    # 全群共享一条流，对齐行业惯例）。空闲超过该分钟数后开新会话；
    # 0 = 永不因空闲重置。重置指令（#新话题 / /new / /reset）随时可手动开新。
    CHANNEL_SESSION_IDLE_RESET_MINUTES: int = 24 * 60

    # 会话最大寿命（小时）：活满后下一条消息自动开新会话（按天滚动），
    # 防止持续活跃的聊天把单条会话无限累积（messages/token 只增不减）。
    # 0 = 不限寿命（仅受空闲重置与预算轮换约束）。
    CHANNEL_SESSION_MAX_AGE_HOURS: int = 24

    # IM 渠道会话是否落 messages 明细。默认 False：渠道上下文由 checkpointer
    # 承载（多轮压缩在 state 上工作），messages 明细没有消费方、纯占存储。
    # 需要后台审计 IM 聊天记录时打开。
    CHANNEL_PERSIST_MESSAGES: bool = False

    # 渠道旧会话保留天数：轮换后的旧会话（session+checkpointer+workspace）
    # 永不再读，仅保留此天数供排障回溯，超期由每日定时任务级联清理。
    # 0 = 永不清理（Web 会话不受此策略影响，仅用户手动删）。
    CHANNEL_SESSION_RETENTION_DAYS: int = 7

    # 飞书群聊仅在被 @ 时响应（首 token 是 @ 占位符才处理，并清洗占位符）。
    # 钉钉平台侧天然只推送被 @ 的群消息，无需此开关。
    CHANNEL_LARK_GROUP_MENTION_ONLY: bool = True

    # Long-connection mode executes inbound messages directly in the FastAPI
    # process (no Celery). These tune that in-process execution:
    #   - EXECUTION_MAX_RETRIES: retry count for TransientChannelError
    #     (LLM rate limit / tool blip) with exponential backoff.
    #   - MAX_CONCURRENT_EXECUTIONS_PER_CHANNEL: per-channel semaphore cap to
    #     prevent a single busy chat from exhausting the LLM quota. Excess
    #     messages queue inside dispatch_inbound until a slot frees up.
    CHANNEL_EXECUTION_MAX_RETRIES: int = 3
    CHANNEL_MAX_CONCURRENT_EXECUTIONS_PER_CHANNEL: int = 4




settings = Settings()
