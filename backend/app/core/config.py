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
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
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


settings = Settings()
