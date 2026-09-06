import logging
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel

from app.core.exceptions import (
    LLMAuthenticationException,
    LLMConfigurationException,
    LLMConnectionException,
    LLMException,
    LLMInvalidModelException,
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
from app.services.llm.base import LLMProvider, sanitize_secret

logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    """Adapter for Google Gemini using modern official google-genai SDK."""

    def __init__(self, config: LLMConfig, client: Any = None) -> None:
        super().__init__(config)
        self.api_key = config.api_key
        if not self.api_key:
            raise LLMAuthenticationException(
                "Gemini API key is required. Set GEMINI_API_KEY in environment or .env."
            )

        self._capabilities = ProviderCapabilities(
            supports_streaming=True,
            supports_structured_output=True,
            supports_tools=True,
            supports_system_messages=True,
        )

        if client is not None:
            self._client = client
        else:
            try:
                from google import genai

                self._client = genai.Client(api_key=self.api_key)
            except ImportError as err:
                raise LLMConfigurationException(
                    "google-genai SDK is not installed. "
                    "Add 'google-genai' to requirements."
                ) from err

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            provider=self.provider_name,
            model=self.model,
            display_name=f"Google Gemini ({self.model})",
            capabilities=self.capabilities,
        )

    def _get_thinking_config(self) -> Any:
        """Configures thinking budgets based on configured thinking_level."""
        try:
            from google.genai import types

            budget_map = {"low": 1024, "medium": 4096, "high": 8192}
            budget = budget_map.get(self.config.thinking_level or "low", 1024)
            return types.ThinkingConfig(thinking_budget=budget)
        except Exception:
            return None

    def _map_error(self, err: Exception) -> LLMException:
        """Normalizes Gemini exceptions into internal hierarchy without secret leakage."""
        if isinstance(
            err,
            (
                LLMTimeoutException,
                LLMAuthenticationException,
                LLMInvalidModelException,
                LLMProviderUnavailableException,
                LLMConnectionException,
                LLMRateLimitException,
                LLMResponseException,
                LLMUnsupportedCapabilityException,
            ),
        ):
            return err

        sec = sanitize_secret(str(err), self.api_key)

        if isinstance(err, TimeoutError):
            return LLMTimeoutException(f"Gemini request timed out: {sec}")

        # 1. Direct status code check on exception attributes if present
        raw_code = getattr(err, "status_code", None) or getattr(err, "code", None)
        if raw_code is not None:
            try:
                code_val = (
                    int(raw_code.value) if hasattr(raw_code, "value") else int(raw_code)
                )
                if code_val in (401, 403):
                    return LLMAuthenticationException(
                        f"Gemini authentication failed ({code_val}): {sec}"
                    )
                if code_val == 404:
                    return LLMInvalidModelException(
                        f"Gemini model '{self.model}' not found ({code_val}): {sec}"
                    )
                if code_val == 429:
                    return LLMRateLimitException(f"Gemini rate limit exceeded: {sec}")
                if code_val in (502, 503, 504):
                    return LLMProviderUnavailableException(
                        f"Gemini service unavailable ({code_val}): {sec}"
                    )
            except (ValueError, TypeError):
                pass

        # 2. Substring fallback for wrapped or unstructured gRPC exceptions
        lowered = str(err).lower()
        if (
            "api_key" in lowered
            or "unauthorized" in lowered
            or "permission denied" in lowered
        ):
            return LLMAuthenticationException(f"Gemini authentication failed: {sec}")
        if (
            "not found" in lowered
            or "model not supported" in lowered
            or "unknown model" in lowered
        ):
            return LLMInvalidModelException(
                f"Gemini model '{self.model}' is invalid: {sec}"
            )
        if "quota" in lowered or "resource_exhausted" in lowered:
            return LLMRateLimitException(f"Gemini quota exceeded: {sec}")
        if "unavailable" in lowered or "overloaded" in lowered or "503" in lowered:
            return LLMProviderUnavailableException(
                f"Gemini service temporarily unavailable: {sec}"
            )
        if "connection" in lowered or "econnrefused" in lowered:
            return LLMConnectionException(f"Failed to connect to Gemini: {sec}")

        return LLMResponseException(f"Gemini returned an unexpected error: {sec}")

    async def generate(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> LLMResponse:
        try:
            from google.genai import types

            config_params: dict[str, Any] = {}
            if system_instruction:
                config_params["system_instruction"] = system_instruction
            if temperature is not None:
                config_params["temperature"] = temperature
            if max_output_tokens is not None:
                config_params["max_output_tokens"] = max_output_tokens

            thinking_cfg = self._get_thinking_config()
            if thinking_cfg:
                config_params["thinking_config"] = thinking_cfg

            config = types.GenerateContentConfig(**config_params)

            response = await self._client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=config,
            )

            text = response.text or ""

            finish_reason = "STOP"
            if (
                hasattr(response, "candidates")
                and response.candidates
                and hasattr(response.candidates[0], "finish_reason")
                and response.candidates[0].finish_reason
            ):
                finish_reason = str(response.candidates[0].finish_reason)

            raw_usage = None
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                raw_usage = {
                    "prompt_tokens": getattr(
                        response.usage_metadata, "prompt_token_count", None
                    ),
                    "completion_tokens": getattr(
                        response.usage_metadata, "candidates_token_count", None
                    ),
                    "total_tokens": getattr(
                        response.usage_metadata, "total_token_count", None
                    ),
                }

            return LLMResponse(
                content=text,
                model=self.model,
                provider=self.provider_name,
                finish_reason=finish_reason,
                raw_usage=raw_usage,
            )
        except Exception as e:
            raise self._map_error(e) from e

    async def generate_structured[T: BaseModel](
        self,
        prompt: str,
        response_schema: type[T],
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
    ) -> T:
        try:
            from google.genai import types

            config_params: dict[str, Any] = {
                "response_mime_type": "application/json",
                "response_schema": response_schema,
            }
            if system_instruction:
                config_params["system_instruction"] = system_instruction
            if temperature is not None:
                config_params["temperature"] = temperature

            thinking_cfg = self._get_thinking_config()
            if thinking_cfg:
                config_params["thinking_config"] = thinking_cfg

            config = types.GenerateContentConfig(**config_params)

            response = await self._client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=config,
            )

            text = response.text or ""
            if not text:
                raise LLMResponseException("Gemini returned empty structured output.")

            return response_schema.model_validate_json(text)
        except Exception as e:
            raise self._map_error(e) from e

    async def stream(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> AsyncIterator[LLMStreamChunk]:
        try:
            from google.genai import types

            config_params: dict[str, Any] = {}
            if system_instruction:
                config_params["system_instruction"] = system_instruction
            if temperature is not None:
                config_params["temperature"] = temperature
            if max_output_tokens is not None:
                config_params["max_output_tokens"] = max_output_tokens

            thinking_cfg = self._get_thinking_config()
            if thinking_cfg:
                config_params["thinking_config"] = thinking_cfg

            config = types.GenerateContentConfig(**config_params)

            stream_iter = await self._client.aio.models.generate_content_stream(
                model=self.model,
                contents=prompt,
                config=config,
            )

            async for chunk in stream_iter:
                delta_text = chunk.text or ""
                yield LLMStreamChunk(delta=delta_text, finish_reason=None)

            yield LLMStreamChunk(delta="", finish_reason="STOP")
        except Exception as e:
            raise self._map_error(e) from e
