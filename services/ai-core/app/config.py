"""Configuration for the ai-core service.

Phase 1 scaffold: only the settings needed to boot and serve health checks
are read here. Feature-specific settings (LLM keys, conversation TTL, etc.)
are consumed by the modules that own them.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_env: str = "development"  # development | production
    tenant_id: str = "default"

    # HTTP
    ai_core_port: int = 8001

    # Event bus
    valkey_url: str = "redis://localhost:6379"

    # Downstream
    db_writer_url: str = "http://localhost:8090"

    # Conversation / LLM (wired in 06_AI_CONVERSATION)
    conversation_state_ttl_hours: int = 2
    ai_max_followup_questions: int = 2
    default_llm_provider: str = "anthropic"
    anthropic_api_key: str = ""
    openai_api_key: str = ""


settings = Settings()
