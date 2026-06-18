"""Application configuration via Pydantic Settings."""
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
    APP_NAME: str = "Agent Flow"
    APP_ENV: str = "development"
    DEBUG: bool = False

    # MongoDB
    MONGODB_URI: str = "mongodb://localhost:27017"
    MONGODB_DB_NAME: str = "agent_flow"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT
    JWT_SECRET_KEY: str = "dev-only-not-for-production-replace-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # CORS - comma-separated origins
    # In development, use "*" to allow all origins; in production,
    # restrict to explicit origins (e.g. "https://app.example.com").
    CORS_ORIGINS: str = "*"

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_JSON_FORMAT: bool = False

    # Model API Key encryption (Base64-encoded 32-byte AES-256 key)
    # Generate: python -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"
    MODEL_ENCRYPTION_KEY: str = ""

    # Task concurrency limits
    TASK_GLOBAL_MAX_RUNNING: int = 50
    TASK_USER_MAX_RUNNING: int = 5

    # Task scheduler (poll interval in seconds; set to 0 to disable)
    TASK_SCHEDULER_POLL_INTERVAL: int = 10

    # Skill filesystem — root directory where Skill files are materialized.
    # Each Skill lives under ``{SKILLS_DIR}/{skill_name}/``.
    SKILLS_DIR: str = "~/.agent-flow/skills"

    # Workspace filesystem — root directory for per-Session workspaces.
    # Layout: ``{WORKSPACES_DIR}/{user_id}/{session_id}/{input,output,tmp}``.
    WORKSPACES_DIR: str = "~/.agent-flow/workspaces"

    # Workspace retention — days to keep workspace files after Session deletion.
    WORKSPACE_RETENTION_DAYS: int = 30

    # Workspace quota — max bytes per workspace (default 500 MB).
    WORKSPACE_MAX_BYTES: int = 500 * 1024 * 1024

    # ── Sandbox ──────────────────────────────────────────────────────────
    # Docker image used for bash tool sandbox execution.
    SANDBOX_IMAGE: str = "agent-sandbox:latest"

    # Sandbox resource limits.
    SANDBOX_MEM_LIMIT: str = "512m"
    SANDBOX_CPU_QUOTA: int = 100_000  # 1 CPU core (100000 μs quota per 100000 μs period)
    SANDBOX_TIMEOUT: int = 120  # seconds
    SANDBOX_MAX_OUTPUT_BYTES: int = 50 * 1024  # 50 KB stdout/stderr cap

    # When True, bash runs inside Docker container.
    # When False (default for local dev), bash runs via subprocess.
    SANDBOX_ENABLED: bool = False

    # Network mode for sandbox containers.
    # "none" = no network access (most secure, default)
    # "bridge" = standard Docker bridge network (allows outbound internet)
    # "host" = use host network stack (least isolation)
    SANDBOX_NETWORK_MODE: str = "none"

    # Host-side path prefix for volume mounts.
    # When backend runs inside a container, the Docker daemon (on the host)
    # needs HOST paths for bind mounts, not container-internal paths.
    # Set these to the host-side equivalents of WORKSPACES_DIR / SKILLS_DIR.
    # Leave empty when backend runs directly on the host (local dev).
    SANDBOX_HOST_WORKSPACES_DIR: str = ""
    SANDBOX_HOST_SKILLS_DIR: str = ""

    # Container-internal mount points for sandbox containers.
    # These are the paths *inside* the sandbox container where workspace
    # and skill directories are mounted.
    SANDBOX_CONTAINER_WORKSPACE_DIR: str = "/workspace"
    SANDBOX_CONTAINER_SKILLS_DIR: str = "/data/skills"


settings = Settings()
