import asyncio
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel

from app.core.exceptions import (
    LLMAuthenticationException,
    LLMConfigurationException,
    LLMConnectionException,
    LLMInvalidModelException,
    LLMProviderException,
    LLMProviderUnavailableException,
    LLMRateLimitException,
    LLMResponseException,
    LLMTimeoutException,
)
from app.schemas.llm import (
    LLMConfig,
    LLMResponse,
    LLMStreamChunk,
    ProviderCapabilities,
)
from app.services.llm.base import LLMProvider
from app.services.llm.parser import parse_structured_output

try:
    from google import genai  # type: ignore[import-not-found, import-untyped]
    from google.genai import types  # type: ignore[import-not-found, import-untyped]
except ImportError:
    genai = None  # type: ignore[assignment]
    types = None  # type: ignore[assignment]


class GeminiProvider(LLMProvider):
    """Adapter for Google Gemini cloud execution via modern google-genai SDK."""

    def __init__(
        self,
        config: LLMConfig,
        client: Any = None,
    ) -> None:
        super().__init__(config)
        api_key = config.get_api_key()
        if not api_key:
            raise LLMAuthenticationException("Gemini API key is required but missing.")
        if not self.model:
            raise LLMInvalidModelException("Gemini model ID cannot be empty.")

        if client is not None:
            self._client = client
        elif genai is not None:
            self._client = genai.Client(api_key=api_key)
        else:
            raise LLMConfigurationException(
                "google-genai SDK is not installed. Please install google-genai."
            )

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_streaming=True,
            supports_structured_output=True,
            supports_tools=True,
            supports_system_messages=True,
        )

    def _build_config(
        self,
        system_instruction: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        response_mime_type: str | None = None,
        response_schema: Any = None,
    ) -> Any:
        if types is None:
            return None

        kwargs: dict[str, Any] = {}
        if system_instruction and system_instruction.strip():
            kwargs["system_instruction"] = system_instruction.strip()
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_output_tokens is not None:
            kwargs["max_output_tokens"] = max_output_tokens
        if response_mime_type is not None:
            kwargs["response_mime_type"] = response_mime_type
        if response_schema is not None:
            kwargs["response_schema"] = response_schema

        if self.config.thinking_level and hasattr(types, "ThinkingConfig"):
            tier = self.config.thinking_level.lower().strip()
            budgets = {"low": 1024, "medium": 4096, "high": 8192}
            budget = budgets.get(tier, 1024)
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=budget)

        return types.GenerateContentConfig(**kwargs)

    def _map_error(self, err: Exception) -> None:
        msg = self._sanitize(str(err))
        lowered = msg.lower()

        if isinstance(err, (asyncio.TimeoutError, TimeoutError)):
            raise LLMTimeoutException(
                f"Gemini request timed out after {self.config.timeout_seconds}s."
            ) from err
        if (
            "api_key_invalid" in lowered
            or "api key not valid" in lowered
            or "unauthenticated" in lowered
        ):
            raise LLMAuthenticationException(
                "Gemini API key authentication failed."
            ) from err
        if (
            "not found" in lowered
            or "is not supported" in lowered
            or "unknown model" in lowered
        ):
            raise LLMInvalidModelException(
                f"Gemini model '{self.model}' was not found or is unsupported: {msg}"
            ) from err
        if (
            "resource_exhausted" in lowered
            or "quota" in lowered
            or "rate limit" in lowered
            or "429" in lowered
        ):
            raise LLMRateLimitException(
                f"Gemini rate limit or quota exceeded: {msg}"
            ) from err
        if (
            "unavailable" in lowered
            or "503" in lowered
            or "connection refused" in lowered
        ):
            raise LLMProviderUnavailableException(
                f"Gemini service is unavailable: {msg}"
            ) from err
        if "connection" in lowered or "network" in lowered:
            raise LLMConnectionException(
                f"Failed to connect to Gemini API: {msg}"
            ) from err

        raise LLMProviderException(f"Gemini provider error: {msg}") from err

    async def generate(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> LLMResponse:
        gen_config = self._build_config(
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )

        try:
            response = await asyncio.wait_for(
                self._client.aio.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=gen_config,
                ),
                timeout=float(self.config.timeout_seconds),
            )
        except Exception as err:
            self._map_error(err)
            raise LLMProviderException(
                f"Unexpected Gemini error: {self._sanitize(str(err))}"
            ) from err

        content = getattr(response, "text", "") or ""
        finish_reason = "stop"
        candidates = getattr(response, "candidates", None)
        if candidates and len(candidates) > 0:
            finish_reason = str(getattr(candidates[0], "finish_reason", "stop")).lower()

        usage: dict[str, Any] = {}
        meta = getattr(response, "usage_metadata", None)
        if meta:
            usage["prompt_tokens"] = getattr(meta, "prompt_token_count", 0)
            usage["completion_tokens"] = getattr(meta, "candidates_token_count", 0)

        return LLMResponse(
            content=content,
            model=self.model,
            provider="gemini",
            finish_reason=finish_reason,
            raw_usage=usage or None,
        )

    async def generate_structured[T: BaseModel](
        self,
        prompt: str,
        response_schema: type[T],
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
    ) -> T:
        gen_config = self._build_config(
            system_instruction=system_instruction,
            temperature=temperature,
            response_mime_type="application/json",
            response_schema=response_schema,
        )

        try:
            response = await asyncio.wait_for(
                self._client.aio.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=gen_config,
                ),
                timeout=float(self.config.timeout_seconds),
            )
        except Exception as err:
            self._map_error(err)
            raise LLMProviderException(
                f"Unexpected Gemini error: {self._sanitize(str(err))}"
            ) from err

        content = getattr(response, "text", "")
        if not content:
            raise LLMResponseException("Gemini returned empty structured content.")
        return parse_structured_output(content, response_schema)

    async def stream(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> AsyncIterator[LLMStreamChunk]:
        gen_config = self._build_config(
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )

        try:
            stream_ctx = await self._client.aio.models.generate_content_stream(
                model=self.model,
                contents=prompt,
                config=gen_config,
            )
            async for chunk in stream_ctx:
                delta = getattr(chunk, "text", "") or ""
                yield LLMStreamChunk(delta=delta)
        except Exception as err:
            self._map_error(err)
            raise LLMProviderException(
                f"Unexpected Gemini streaming error: {self._sanitize(str(err))}"
            ) from err
