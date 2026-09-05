from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from pydantic import BaseModel

from app.schemas.llm import (
    LLMConfig,
    LLMResponse,
    LLMStreamChunk,
    ModelInfo,
    ProviderCapabilities,
)


def sanitize_secret(text: str, secret: str | None) -> str:
    """Removes sensitive credentials from error messages and text representations."""
    if not secret or len(secret) < 4:
        return text
    return text.replace(secret, "[REDACTED]")


def format_display_name(provider: str, model: str) -> str:
    """Generates a dynamic human-readable display name without hard-coding catalogs."""
    clean_provider = provider.strip().capitalize()
    clean_model = model.strip()
    return f"{clean_provider} ({clean_model})"


class LLMProvider(ABC):
    """Authoritative abstract base class for all IrtrixAI LLM provider adapters."""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self.provider_name = config.provider.strip().lower()
        self.model = config.model.strip()

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Returns the capabilities supported by this provider and model."""
        ...

    def get_model_info(self) -> ModelInfo:
        """Returns provider and model metadata without exposing credentials."""
        return ModelInfo(
            provider=self.provider_name,
            model=self.model,
            display_name=format_display_name(self.provider_name, self.model),
            capabilities=self.capabilities,
        )

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> LLMResponse:
        """Asynchronously generates unstructured text from the provider."""
        ...

    @abstractmethod
    async def generate_structured[T: BaseModel](
        self,
        prompt: str,
        response_schema: type[T],
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
    ) -> T:
        """Asynchronously generates structured data strictly validated against a Pydantic schema."""
        ...

    @abstractmethod
    async def stream(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> AsyncIterator[LLMStreamChunk]:
        """Asynchronously yields streaming text chunks from the provider."""
        ...

    def _sanitize(self, message: str) -> str:
        """Helper to sanitize the provider's active API key from strings."""
        return sanitize_secret(message, self.config.get_api_key())
