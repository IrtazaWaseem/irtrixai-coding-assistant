import json
from collections.abc import AsyncIterator

import pytest
from pydantic import BaseModel, Field

from app.core.exceptions import (
    AppException,
    LLMAuthenticationException,
    LLMConfigurationException,
    LLMConnectionException,
    LLMException,
    LLMInvalidModelException,
    LLMProviderException,
    LLMProviderUnavailableException,
    LLMRateLimitException,
    LLMResponseException,
    LLMTimeoutException,
    LLMUnsupportedCapabilityException,
)
from app.schemas.llm import (
    LLMConfig,
    LLMResponse,
    LLMStreamChunk,
    ModelInfo,
    ProviderCapabilities,
)
from app.services.llm.base import LLMProvider
from app.services.llm.factory import LLMFactory
from app.services.llm.gateway import LLMGateway
from app.services.llm.providers.gemini import GeminiProvider
from app.services.llm.providers.groq import GroqProvider
from app.services.llm.providers.ollama import OllamaProvider


class DummyStructuredModel(BaseModel):
    summary: str = Field(..., description="Summary text")
    confidence: float = Field(..., description="Confidence score")


class MockConfigurableProvider(LLMProvider):
    """Configurable mock provider adapter for deterministic gateway unit tests."""

    def __init__(
        self,
        config: LLMConfig,
        caps: ProviderCapabilities | None = None,
        fail_with: Exception | None = None,
    ) -> None:
        super().__init__(config)
        self._caps = caps or ProviderCapabilities()
        self._fail_with = fail_with

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._caps

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            provider=self.provider_name,
            model=self.model,
            display_name=f"Mock ({self.model})",
            capabilities=self.capabilities,
        )

    async def generate(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> LLMResponse:
        if self._fail_with:
            raise self._fail_with
        return LLMResponse(
            content=f"Generated: {prompt}",
            model=self.model,
            provider=self.provider_name,
            finish_reason="STOP",
            raw_usage={"prompt_tokens": 12, "completion_tokens": 8},
        )

    async def generate_structured[T: BaseModel](
        self,
        prompt: str,
        response_schema: type[T],
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
    ) -> T:
        if self._fail_with:
            raise self._fail_with
        if response_schema is DummyStructuredModel:
            return DummyStructuredModel(summary=f"Processed: {prompt}", confidence=0.99)  # type: ignore[return-value]
        raise ValueError("Unsupported schema")

    async def stream(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> AsyncIterator[LLMStreamChunk]:
        if self._fail_with:
            raise self._fail_with
        yield LLMStreamChunk(delta="Chunk 1: ")
        yield LLMStreamChunk(delta=prompt, finish_reason="STOP")


# --- Unit Tests ---


def test_ollama_configuration_resolution():
    config = LLMConfig(provider="ollama", model="qwen-gpu-tuned")
    provider = LLMFactory.create_provider(config)
    assert isinstance(provider, OllamaProvider)
    assert provider.provider_name == "ollama"
    assert provider.model == "qwen-gpu-tuned"


def test_qwen_model_resolves_correctly():
    config = LLMConfig(provider="ollama", model="qwen-gpu-tuned")
    provider = LLMFactory.create_provider(config)
    info = provider.get_model_info()
    assert info.provider == "ollama"
    assert info.model == "qwen-gpu-tuned"
    assert info.capabilities.supports_streaming is True
    assert info.capabilities.supports_structured_output is True


def test_deepseek_model_resolves_correctly():
    config = LLMConfig(provider="ollama", model="deepseek-r1:8b")
    provider = LLMFactory.create_provider(config)
    info = provider.get_model_info()
    assert info.provider == "ollama"
    assert info.model == "deepseek-r1:8b"


def test_groq_arbitrary_model_accepted():
    config = LLMConfig(
        provider="groq",
        model="llama-3.3-70b-versatile-custom",
        api_key="gsk_dummy_test_key",
    )
    provider = LLMFactory.create_provider(config)
    assert isinstance(provider, GroqProvider)
    assert provider.model == "llama-3.3-70b-versatile-custom"


def test_gemini_arbitrary_model_accepted():
    config = LLMConfig(
        provider="gemini",
        model="gemini-2.5-flash-experimental",
        api_key="AIzaSyDummyTestKey",
    )
    provider = LLMFactory.create_provider(config)
    assert isinstance(provider, GeminiProvider)
    assert provider.model == "gemini-2.5-flash-experimental"


def test_unknown_provider_fails_safely():
    for bad_provider in ["anthropic", "openai", "cohere", "custom_unknown"]:
        config = LLMConfig(provider=bad_provider, model="some-model")
        with pytest.raises(LLMConfigurationException) as exc_info:
            LLMFactory.create_provider(config)
        assert f"Unsupported LLM provider '{bad_provider}'" in str(exc_info.value)
        assert exc_info.value.status_code == 500


def test_missing_required_api_key_handled_safely():
    groq_no_key = LLMConfig(provider="groq", model="llama-3.3-70b-versatile")
    with pytest.raises(LLMAuthenticationException) as exc_info:
        LLMFactory.create_provider(groq_no_key)
    assert exc_info.value.status_code == 401
    assert "Groq API key is required" in str(exc_info.value)

    gemini_no_key = LLMConfig(provider="gemini", model="gemini-2.5-flash")
    with pytest.raises(LLMAuthenticationException) as exc_info:
        LLMFactory.create_provider(gemini_no_key)
    assert exc_info.value.status_code == 401
    assert "Gemini API key is required" in str(exc_info.value)

    ollama_no_key = LLMConfig(provider="ollama", model="qwen-gpu-tuned")
    provider = LLMFactory.create_provider(ollama_no_key)
    assert isinstance(provider, OllamaProvider)


def test_api_keys_not_included_in_serialized_config_objects():
    secret = "AIzaSySecretDoNotLeak999"
    config = LLMConfig(
        provider="gemini",
        model="gemini-2.5-flash",
        api_key=secret,
    )

    dumped = config.model_dump()
    assert "api_key" not in dumped
    assert secret not in str(dumped)

    json_str = config.model_dump_json()
    assert "api_key" not in json_str
    assert secret not in json_str

    assert secret not in repr(config)
    assert secret not in str(config)

    provider = GeminiProvider(config)
    info = provider.get_model_info()
    assert secret not in json.dumps(info.model_dump())


def test_provider_independent_errors_raised():
    assert issubclass(LLMConfigurationException, LLMException)
    assert issubclass(LLMAuthenticationException, LLMException)
    assert issubclass(LLMInvalidModelException, LLMException)
    assert issubclass(LLMProviderUnavailableException, LLMException)
    assert issubclass(LLMConnectionException, LLMException)
    assert issubclass(LLMTimeoutException, LLMException)
    assert issubclass(LLMRateLimitException, LLMException)
    assert issubclass(LLMResponseException, LLMException)
    assert issubclass(LLMUnsupportedCapabilityException, LLMException)
    assert issubclass(LLMProviderException, LLMException)
    assert issubclass(LLMException, AppException)


def test_fallback_configuration_can_be_absent():
    primary = MockConfigurableProvider(LLMConfig(provider="ollama", model="qwen-gpu-tuned"))
    gateway = LLMGateway(primary_provider=primary, fallback_provider=None)
    assert gateway.primary is primary
    assert gateway.fallback is None


@pytest.mark.asyncio
async def test_gateway_generation_and_fallback_dispatch():
    transient_error = LLMTimeoutException("Provider timed out.")
    primary = MockConfigurableProvider(
        LLMConfig(provider="gemini", model="gemini-2.5-flash"),
        fail_with=transient_error,
    )
    fallback = MockConfigurableProvider(LLMConfig(provider="ollama", model="deepseek-r1:8b"))

    gateway = LLMGateway(primary_provider=primary, fallback_provider=fallback)

    res = await gateway.generate("Summarize codebase")
    assert res.provider == "ollama"
    assert res.model == "deepseek-r1:8b"
    assert "Summarize codebase" in res.content

    struct_res = await gateway.generate_structured("Analyze", DummyStructuredModel)
    assert isinstance(struct_res, DummyStructuredModel)
    assert struct_res.summary == "Processed: Analyze"

    chunks = []
    async for chunk in gateway.stream("Stream test"):
        chunks.append(chunk.delta)
    assert "".join(chunks) == "Chunk 1: Stream test"


@pytest.mark.asyncio
async def test_gateway_capability_rejection():
    no_structured_caps = ProviderCapabilities(supports_structured_output=False)
    no_stream_caps = ProviderCapabilities(supports_streaming=False)

    provider_no_struct = MockConfigurableProvider(
        LLMConfig(provider="ollama", model="dummy"), caps=no_structured_caps
    )
    gateway_no_struct = LLMGateway(primary_provider=provider_no_struct)

    with pytest.raises(LLMUnsupportedCapabilityException):
        await gateway_no_struct.generate_structured("test", DummyStructuredModel)

    provider_no_stream = MockConfigurableProvider(
        LLMConfig(provider="ollama", model="dummy"), caps=no_stream_caps
    )
    gateway_no_stream = LLMGateway(primary_provider=provider_no_stream)

    with pytest.raises(LLMUnsupportedCapabilityException):
        async for _ in gateway_no_stream.stream("test"):
            pass
