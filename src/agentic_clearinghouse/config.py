"""Application configuration via pydantic-settings.

Reads from .env file or environment variables. All settings are validated
at startup — if a required setting is missing, the app fails fast with a
clear error message.

Usage:
    from agentic_clearinghouse.config import get_settings
    settings = get_settings()
    print(settings.database_url)
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for the Agentic Clearinghouse."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_env: Literal["development", "staging", "production"] = "development"
    app_debug: bool = True
    app_log_level: str = "DEBUG"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # --- Database (PostgreSQL) ---
    database_url: str = (
        "postgresql+asyncpg://clearinghouse:clearinghouse_dev"
        "@localhost:5432/agentic_clearinghouse"
    )
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_echo_sql: bool = False

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"
    redis_idempotency_ttl_seconds: int = 86400  # 24 hours

    # --- E2B Sandbox ---
    e2b_api_key: str = ""
    e2b_timeout_seconds: int = 30

    # --- LLM / LiteLLM ---
    # Supports any LiteLLM-compatible model string.
    # For Gemini: set GEMINI_API_KEY and use "gemini/gemini-2.0-flash"
    # For OpenAI: set OPENAI_API_KEY and use "gpt-4o"
    openai_api_key: str = ""
    gemini_api_key: str = ""
    litellm_model: str = "gemini/gemini-2.0-flash"
    litellm_fallback_models: str = "gemini/gemini-1.5-flash"
    litellm_max_tokens: int = 1024
    litellm_temperature: float = 0.0

    # --- Coinbase AgentKit ---
    cdp_api_key_id: str = ""
    cdp_api_key_secret: str = ""
    cdp_wallet_secret: str = ""
    cdp_network_id: str = "base-sepolia"

    # --- MCP ---
    mcp_transport: str = "streamable-http"

    # --- Escrow Defaults ---
    default_max_retries: int = 3

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def litellm_fallback_model_list(self) -> list[str]:
        """Parse comma-separated fallback models into a list."""
        if not self.litellm_fallback_models:
            return []
        return [m.strip() for m in self.litellm_fallback_models.split(",") if m.strip()]

    @property
    def sync_database_url(self) -> str:
        """Synchronous database URL for Alembic migrations."""
        return self.database_url.replace("+asyncpg", "+psycopg2")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton of the application settings."""
    return Settings()
