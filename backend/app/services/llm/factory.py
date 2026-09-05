from typing import ClassVar

from app.core.config import settings
from app.core.exceptions import LLMConfigurationException, LLMInvalidModelException
from app.schemas.llm import LLMConfig
from app.services.llm.base import LLMProvider
from app.services.llm.providers.gemini import GeminiProvider
from app.services.llm.providers.groq import GroqProvider
from app.services.llm.providers.ollama import OllamaProvider


class LLMFactory:
    """Authoritative factory and registry for LLM providers.

    Guarantees provider selection is explicit, validated, and fails closed without
    silent fallbacks.
    """

    SUPPORTED_PROVIDERS: ClassVar[set[str]] = {"ollama", "groq", "gemini"}
    _registry: ClassVar[dict[str, type[LLMProvider]]] = {
        "ollama": OllamaProvider,
        "groq": GroqProvider,
        "gemini": GeminiProvider,
    }

    @classmethod
    def register_provider(cls, name: str, provider_cls: type[LLMProvider]) -> None:
        """Registers a concrete provider adapter class."""
        normalized = name.strip().lower()
        cls._registry[normalized] = provider_cls

    @classmethod
    def unregister_provider(cls, name: str) -> None:
        """Unregisters a provider adapter class (primarily for testing isolation)."""
        normalized = name.strip().lower()
        cls._registry.pop(normalized, None)

    @classmethod
    def create_provider(cls, config: LLMConfig | None = None) -> LLMProvider:
        """Instantiates the specified or configured LLM provider adapter."""
        effective_config = config or settings.get_primary_llm_config()
        target_provider = effective_config.provider.strip().lower()

        if target_provider not in cls.SUPPORTED_PROVIDERS:
            raise LLMConfigurationException(
                f"Unsupported LLM provider '{target_provider}'. Supported: {sorted(cls.SUPPORTED_PROVIDERS)}",
                details={
                    "provider": target_provider,
                    "supported": sorted(cls.SUPPORTED_PROVIDERS),
                },
            )

        provider_cls = cls._registry.get(target_provider)
        if provider_cls is None:
            raise LLMConfigurationException(
                f"Provider '{target_provider}' is supported but no adapter is registered in this runtime.",
                details={"provider": target_provider},
            )

        if not effective_config.model or not effective_config.model.strip():
            raise LLMInvalidModelException(
                f"Model identifier cannot be empty for provider '{target_provider}'."
            )

        return provider_cls(effective_config)

    @classmethod
    def create_fallback_provider(cls) -> LLMProvider | None:
        """Instantiates the optional fallback LLM provider if configured."""
        fallback_config = settings.get_fallback_llm_config()
        if fallback_config is None:
            return None
        return cls.create_provider(fallback_config)
