import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from pydantic import BaseModel, Field

from app.core.exceptions import (
    LLMAuthenticationException,
    LLMConnectionException,
    LLMInvalidModelException,
    LLMRateLimitException,
    LLMTimeoutException,
)
from app.schemas.llm import LLMConfig
from app.services.llm.gateway import LLMGateway
from app.services.llm.providers.gemini import GeminiProvider
from app.services.llm.providers.groq import GroqProvider
from app.services.llm.providers.ollama import OllamaProvider


class SampleStructuredContract(BaseModel):
    task: str = Field(..., description="Task title")
    priority: int = Field(..., description="Priority scale 1-5")


# --- Ollama Tests ---


@pytest.mark.asyncio
async def test_ollama_qwen_generate():
    """Verifies Ollama sends requests with arbitrary Qwen model and parses response."""
    config = LLMConfig(provider="ollama", model="qwen-gpu-tuned")

    def handle_request(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.read())
        assert data["model"] == "qwen-gpu-tuned"
        assert data["messages"][-1]["content"] == "Write python hello world"
        return httpx.Response(
            status_code=200,
            json={
                "model": "qwen-gpu-tuned",
                "message": {"role": "assistant", "content": "print('hello world')"},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 8,
                "eval_count": 6,
            },
        )

    transport = httpx.MockTransport(handle_request)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OllamaProvider(config, client=client)
        info = provider.get_model_info()
        assert info.provider == "ollama"
        assert info.model == "qwen-gpu-tuned"
        assert info.display_name == "Ollama (qwen-gpu-tuned)"

        res = await provider.generate("Write python hello world")
        assert res.content == "print('hello world')"
        assert res.provider == "ollama"
        assert res.model == "qwen-gpu-tuned"
        assert res.raw_usage["completion_tokens"] == 6


@pytest.mark.asyncio
async def test_ollama_deepseek_reasoning_and_structured():
    """Verifies DeepSeek R1 thinking output is cleaned and parsed to structured contract."""
    config = LLMConfig(provider="ollama", model="deepseek-r1:8b")

    think_response = (
        "<think>\nNeed to output valid json with task and priority.\n</think>\n"
        '```json\n{"task": "Refactor DB pool", "priority": 1}\n```'
    )

    def handle_request(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.read())
        assert data["model"] == "deepseek-r1:8b"
        assert data["format"] == "json"
        return httpx.Response(
            status_code=200,
            json={
                "model": "deepseek-r1:8b",
                "message": {"role": "assistant", "content": think_response},
                "done": True,
            },
        )

    transport = httpx.MockTransport(handle_request)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OllamaProvider(config, client=client)
        res = await provider.generate_structured("Plan task", SampleStructuredContract)
        assert isinstance(res, SampleStructuredContract)
        assert res.task == "Refactor DB pool"
        assert res.priority == 1


@pytest.mark.asyncio
async def test_ollama_streaming():
    """Verifies streaming chunks are yielded in standardized format."""
    config = LLMConfig(provider="ollama", model="qwen-gpu-tuned")
    chunks = [
        json.dumps({"message": {"content": "def "}, "done": False}) + "\n",
        json.dumps({"message": {"content": "foo():"}, "done": False}) + "\n",
        json.dumps(
            {"message": {"content": " pass"}, "done": True, "done_reason": "stop"}
        )
        + "\n",
    ]

    def handle_request(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, content="".join(chunks).encode())

    transport = httpx.MockTransport(handle_request)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OllamaProvider(config, client=client)
        gathered = []
        async for chunk in provider.stream("Write func"):
            gathered.append(chunk.delta)
        assert "".join(gathered) == "def foo(): pass"


@pytest.mark.asyncio
async def test_ollama_error_mapping():
    """Verifies 404 maps to LLMInvalidModelException and timeout maps to LLMTimeoutException."""
    config = LLMConfig(provider="ollama", model="missing-model", timeout_seconds=1)

    transport_404 = httpx.MockTransport(
        lambda _: httpx.Response(404, text="model 'missing-model' not found")
    )
    async with httpx.AsyncClient(transport=transport_404) as client:
        provider = OllamaProvider(config, client=client)
        with pytest.raises(LLMInvalidModelException):
            await provider.generate("hi")

    def timeout_handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Timeout")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(timeout_handler)
    ) as client:
        provider = OllamaProvider(config, client=client)
        with pytest.raises(LLMTimeoutException):
            await provider.generate("hi")


# --- Groq Tests ---


@pytest.mark.asyncio
async def test_groq_arbitrary_model_and_auth():
    """Verifies Groq adapter accepts arbitrary model strings and enforces API key presence."""
    with pytest.raises(LLMAuthenticationException):
        GroqProvider(
            LLMConfig(provider="groq", model="llama-3.3-70b-versatile", api_key="")
        )

    config = LLMConfig(
        provider="groq",
        model="llama-3.1-8b-instant",
        api_key="gsk_valid_secret_key_123",
    )

    def handle_request(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer gsk_valid_secret_key_123"
        data = json.loads(request.read())
        assert data["model"] == "llama-3.1-8b-instant"
        return httpx.Response(
            status_code=200,
            json={
                "choices": [
                    {
                        "message": {"content": "Fast Groq response"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"total_tokens": 15},
            },
        )

    transport = httpx.MockTransport(handle_request)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GroqProvider(config, client=client)
        info = provider.get_model_info()
        assert info.provider == "groq"
        assert info.model == "llama-3.1-8b-instant"
        assert info.display_name == "Groq (llama-3.1-8b-instant)"

        res = await provider.generate("Generate quick answer")
        assert res.content == "Fast Groq response"
        assert res.model == "llama-3.1-8b-instant"


@pytest.mark.asyncio
async def test_groq_error_mapping():
    """Verifies Groq 401, 429, and 404 status codes map to normalized exceptions."""
    config = LLMConfig(provider="groq", model="test-model", api_key="gsk_key")

    transport_401 = httpx.MockTransport(
        lambda _: httpx.Response(401, text="Invalid API Key")
    )
    async with httpx.AsyncClient(transport=transport_401) as client:
        provider = GroqProvider(config, client=client)
        with pytest.raises(LLMAuthenticationException):
            await provider.generate("hi")

    transport_429 = httpx.MockTransport(
        lambda _: httpx.Response(429, text="Rate limit exceeded")
    )
    async with httpx.AsyncClient(transport=transport_429) as client:
        provider = GroqProvider(config, client=client)
        with pytest.raises(LLMRateLimitException):
            await provider.generate("hi")

    transport_404 = httpx.MockTransport(
        lambda _: httpx.Response(404, text="Model does not exist")
    )
    async with httpx.AsyncClient(transport=transport_404) as client:
        provider = GroqProvider(config, client=client)
        with pytest.raises(LLMInvalidModelException):
            await provider.generate("hi")


# --- Gemini Tests ---


@pytest.mark.asyncio
async def test_gemini_arbitrary_model_generate():
    """Verifies Gemini adapter functions with arbitrary model identifiers."""
    config = LLMConfig(
        provider="gemini",
        model="gemini-2.5-flash",
        api_key="AIzaSyDummyKey",
        thinking_level="low",
    )

    mock_response = MagicMock()
    mock_response.text = "Generated from Gemini Flash"
    mock_response.candidates = [MagicMock(finish_reason="STOP")]
    mock_response.usage_metadata = MagicMock(
        prompt_token_count=10, candidates_token_count=5
    )

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    provider = GeminiProvider(config, client=mock_client)
    info = provider.get_model_info()
    assert info.provider == "gemini"
    assert info.model == "gemini-2.5-flash"
    assert info.display_name == "Gemini (gemini-2.5-flash)"

    res = await provider.generate("Hello Gemini")
    assert res.content == "Generated from Gemini Flash"
    assert res.provider == "gemini"
    assert res.model == "gemini-2.5-flash"
    assert res.raw_usage["completion_tokens"] == 5


@pytest.mark.asyncio
async def test_gemini_structured_output():
    """Verifies Gemini structured output is passed to parse_structured_output."""
    config = LLMConfig(
        provider="gemini",
        model="gemini-3.5-flash-lite",
        api_key="AIzaSyDummyKey",
    )

    mock_response = MagicMock()
    mock_response.text = '{"task": "Run tests", "priority": 2}'
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    provider = GeminiProvider(config, client=mock_client)
    res = await provider.generate_structured("Get task", SampleStructuredContract)
    assert isinstance(res, SampleStructuredContract)
    assert res.task == "Run tests"
    assert res.priority == 2


@pytest.mark.asyncio
async def test_gemini_error_mapping():
    """Verifies Gemini SDK errors map cleanly to normalized exceptions."""
    config = LLMConfig(provider="gemini", model="gemini-2.5-flash", api_key="AIzaKey")

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(
        side_effect=Exception("API_KEY_INVALID: User not authenticated")
    )
    provider = GeminiProvider(config, client=mock_client)
    with pytest.raises(LLMAuthenticationException):
        await provider.generate("hi")

    mock_client.aio.models.generate_content = AsyncMock(
        side_effect=Exception("models/gemini-old is not found for API version")
    )
    with pytest.raises(LLMInvalidModelException):
        await provider.generate("hi")

    mock_client.aio.models.generate_content = AsyncMock(
        side_effect=Exception("RESOURCE_EXHAUSTED: Rate limit reached")
    )
    with pytest.raises(LLMRateLimitException):
        await provider.generate("hi")


# --- Gateway Fallback & Secret Isolation Tests ---


@pytest.mark.asyncio
async def test_gateway_transient_fallback_success():
    """Verifies primary transient failure falls back to secondary and records actual model."""
    primary_config = LLMConfig(
        provider="groq", model="llama-3.3-70b-versatile", api_key="gsk_key"
    )
    fallback_config = LLMConfig(provider="ollama", model="qwen-gpu-tuned")

    def groq_fail(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="Rate limit exceeded")

    def ollama_ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={
                "model": "qwen-gpu-tuned",
                "message": {"role": "assistant", "content": "Fallback Ollama Success"},
                "done": True,
            },
        )

    groq_client = httpx.AsyncClient(transport=httpx.MockTransport(groq_fail))
    ollama_client = httpx.AsyncClient(transport=httpx.MockTransport(ollama_ok))

    primary = GroqProvider(primary_config, client=groq_client)
    fallback = OllamaProvider(fallback_config, client=ollama_client)

    gateway = LLMGateway(primary_provider=primary, fallback_provider=fallback)
    res = await gateway.generate("Execute plan")

    assert res.content == "Fallback Ollama Success"
    assert res.provider == "ollama"
    assert res.model == "qwen-gpu-tuned"


@pytest.mark.asyncio
async def test_gateway_non_transient_does_not_fallback():
    """Verifies non-transient error (e.g. 401 Auth) raises immediately without fallback."""
    primary_config = LLMConfig(
        provider="groq", model="llama-3.3-70b-versatile", api_key="gsk_bad"
    )

    def groq_401(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Unauthorized key")

    groq_client = httpx.AsyncClient(transport=httpx.MockTransport(groq_401))
    ollama_mock = MagicMock(spec=OllamaProvider)

    primary = GroqProvider(primary_config, client=groq_client)
    gateway = LLMGateway(primary_provider=primary, fallback_provider=ollama_mock)

    with pytest.raises(LLMAuthenticationException):
        await gateway.generate("Run")

    ollama_mock.generate.assert_not_called()


def test_secrets_never_appear_in_exceptions_or_metadata():
    """Verifies API keys are sanitized if provider errors echo them."""
    secret = "AIzaSySuperSecretToken12345"
    config = LLMConfig(provider="gemini", model="gemini-2.5-flash", api_key=secret)

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(
        side_effect=Exception(f"Connection failed for key {secret}")
    )
    provider = GeminiProvider(config, client=mock_client)

    with pytest.raises(LLMConnectionException) as exc_info:
        asyncio.run(provider.generate("test"))

    err_str = str(exc_info.value)
    assert secret not in err_str
    assert "[REDACTED]" in err_str
