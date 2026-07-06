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

    # Event bus (Feature 01)
    valkey_url: str = "redis://localhost:6379"
    event_bus_max_retries: int = 3
    event_bus_retry_delay_ms: int = 1000
    event_bus_consumer_group: str = "uniserve"

    # Downstream
    db_writer_url: str = "http://localhost:8090"
    db_writer_internal_api_key: str = ""

    # Identity resolver (Feature 03)
    identity_merge_confidence_threshold: float = 0.85
    identity_pending_timeout_hours: int = 48
    identity_anon_ref_prefix: str = "ANON"
    default_region: str = "IN"  # for phone normalisation

    # Conversation / LLM (Feature 06)
    conversation_state_ttl_hours: int = 2
    ai_max_followup_questions: int = 2
    default_llm_provider: str = "anthropic"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openai_assistant_id: str = ""
    openai_model: str = "gpt-4o-mini"

    # PII scrubber (Feature 07)
    pii_scrubber_enabled: bool = True
    pii_token_ttl_minutes: int = 10
    presidio_language: str = "en"


settings = Settings()
