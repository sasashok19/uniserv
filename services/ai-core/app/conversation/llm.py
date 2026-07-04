"""LLM gateway (Feature 06).

Routes to the tenant's configured provider. In Phase 1 dev no API keys are set,
so the gateway reports unavailable and callers fall back to rule-based logic
(classification, summary). PII scrubbing wraps every real call (Feature 07).
"""

import logging
from typing import Optional

from app.config import settings

logger = logging.getLogger("ai-core")

SUPPORTED_PROVIDERS = {"anthropic", "openai", "gemini", "ollama"}


class LLMUnavailableError(RuntimeError):
    pass


class LLMGateway:
    def __init__(self, provider: Optional[str] = None):
        self.provider = (provider or settings.default_llm_provider).lower()

    def is_available(self) -> bool:
        """True when the configured provider has credentials/endpoint available."""
        if self.provider == "anthropic":
            return bool(settings.anthropic_api_key)
        if self.provider == "openai":
            return bool(settings.openai_api_key)
        # gemini/ollama are not configured in Phase 1 dev.
        return False

    async def complete(self, system_prompt: str, messages: list[dict], max_tokens: int = 500) -> str:
        if not self.is_available():
            raise LLMUnavailableError(f"LLM provider '{self.provider}' is not available")
        # PHASE_1: real provider dispatch is added when keys are provisioned; the
        # pipeline runs on rule-based fallbacks until then.
        raise LLMUnavailableError("LLM dispatch not wired in Phase 1 dev")
