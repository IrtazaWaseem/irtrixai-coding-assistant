from typing import Any

from app.core.config import settings
from app.core.exceptions import LLMConfigurationException
from app.schemas.llm import LLMConfig
from app.services.llm.base import LLMProvider
from app.services.llm.providers.gemini import GeminiProvider
from app.services.llm.providers.groq import GroqProvider
from app.services.llm.providers.ollama import OllamaProvider


class LLMFactory:
    """Registry and factory for constructing provider instances."""

    @classmethod
    def create_provider(cls, config: LLMConfig | None = None, client: Any = None) -> LLMProvider:
        cfg = config or settings.get_primary_llm_config()
        prov = cfg.provider.strip().lower()
        if prov == "ollama":
            return OllamaProvider(cfg, client=client)
        if prov == "groq":
            return GroqProvider(cfg, client=client)
        if prov == "gemini":
            return GeminiProvider(cfg, client=client)
        raise LLMConfigurationException(f"Unsupported LLM provider '{prov}'.")

    @classmethod
    def create_fallback_provider(
        cls, config: LLMConfig | None = None, client: Any = None
    ) -> LLMProvider | None:
        cfg = config or settings.get_fallback_llm_config()
        if cfg is None:
            return None
        prov = cfg.provider.strip().lower()
        if prov == "ollama":
            return OllamaProvider(cfg, client=client)
        if prov == "groq":
            return GroqProvider(cfg, client=client)
        if prov == "gemini":
            return GeminiProvider(cfg, client=client)
        raise LLMConfigurationException(f"Unsupported LLM fallback provider '{prov}'.")
