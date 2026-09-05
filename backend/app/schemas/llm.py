from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProviderCapabilities(BaseModel):
    """Declarative capability flags for an LLM provider and model."""

    model_config = ConfigDict(frozen=True)

    supports_streaming: bool = Field(
        default=True, description="Indicates if provider supports token streaming"
    )
    supports_structured_output: bool = Field(
        default=True,
        description="Indicates if provider natively supports JSON schema output",
    )
    supports_tools: bool = Field(
        default=True, description="Indicates if provider supports function/tool calling"
    )
    supports_system_messages: bool = Field(
        default=True, description="Indicates if provider accepts system instructions"
    )


class ModelInfo(BaseModel):
    """Provider-neutral model identity and capability metadata."""

    model_config = ConfigDict(frozen=True)

    provider: str = Field(
        ..., description="Normalized provider identifier ('ollama', 'groq', 'gemini')"
    )
    model: str = Field(
        ...,
        description="Configured model identifier (e.g. 'qwen-gpu-tuned', 'deepseek-r1:8b')",
    )
    display_name: str = Field(..., description="Human-readable model name")
    capabilities: ProviderCapabilities = Field(
        default_factory=ProviderCapabilities,
        description="Declared capabilities of this provider/model",
    )


class LLMConfig(BaseModel):
    """Provider-neutral configuration for initializing an LLM provider adapter."""

    model_config = ConfigDict(frozen=True)

    provider: str = Field(
        ..., description="Provider identifier: 'ollama', 'groq', or 'gemini'"
    )
    model: str = Field(..., description="Arbitrary model identifier string")
    api_key: str | None = Field(default=None, repr=False, exclude=True)
    base_url: str | None = Field(
        default=None, description="Endpoint URL for local or self-hosted engines"
    )
    timeout_seconds: int = Field(default=60, description="Request timeout in seconds")
    max_retries: int = Field(
        default=3, description="Maximum retries for transient errors"
    )
    thinking_level: str = Field(
        default="low",
        description="Reasoning/thinking effort level ('low', 'medium', 'high')",
    )

    def get_api_key(self) -> str | None:
        """Authoritative getter for API keys on backend only."""
        return self.api_key


class LLMResponse(BaseModel):
    """Standardized unstructured text generation result from an LLM provider."""

    model_config = ConfigDict(frozen=True)

    content: str = Field(..., description="Generated text content")
    model: str = Field(..., description="Model identifier that produced the content")
    provider: str = Field(
        ..., description="Provider identifier that fulfilled the request"
    )
    finish_reason: str | None = Field(
        default=None, description="Generation completion reason"
    )
    raw_usage: dict[str, Any] | None = Field(
        default=None, description="Token consumption metrics if reported"
    )


class LLMStreamChunk(BaseModel):
    """Normalized token or text chunk emitted during streaming inference."""

    model_config = ConfigDict(frozen=True)

    delta: str = ""
    finish_reason: str | None = None
    provider_switched: bool = False
