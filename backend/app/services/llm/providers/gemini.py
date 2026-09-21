"""Google Gemini LLM provider implementation.

Integrates with the Google GenAI SDK to support text generation, structured JSON
output, and token streaming. Handles optional SDK availability so mocked testing
can execute without requiring google-genai to be installed in the runtime environment.
"""

import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, ValidationError

from app.core.exceptions import (
    LLMAuthenticationException,
    LLMConnectionException,
    LLMInvalidModelException,
    LLMProviderException,
    LLMProviderUnavailableException,
    LLMRateLimitException,
    LLMResponseException,
)
from app.schemas.llm import LLMConfig, LLMResponse, ModelInfo
from app.services.llm.base import LLMProvider

logger = logging.getLogger(__name__)


def _get_genai_types() -> Any:
    """Returns google.genai.types if installed, or a mock-compatible fallback object."""
    try:
        from google.genai import types

        return types
    except ImportError:

        class _FallbackGenerateContentConfig:
            def __init__(self, **kwargs: Any) -> None:
                for key, value in kwargs.items():
                    setattr(self, key, value)

        class _FallbackTypes:
            GenerateContentConfig = _FallbackGenerateContentConfig

            def __getattr__(self, name: str) -> Any:
                return _FallbackGenerateContentConfig

        return _FallbackTypes


class GeminiProvider(LLMProvider):
    """LLM provider implementation for Google Gemini models via google-genai SDK."""

    def __init__(
        self,
        config: LLMConfig,
        client: Any | None = None,
    ) -> None:
        super().__init__(config=config)
        self._client = client
        if self._client is None and not (self.config.api_key and self.config.api_key.strip()):
            raise LLMAuthenticationException("Gemini API key is required")

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        try:
            from google import genai

            return genai.Client(api_key=self.config.api_key)
        except ImportError as err:
            raise LLMProviderException(
                "The 'google-genai' package is required to use GeminiProvider without a mock client. "
                "Install it via: pip install google-genai"
            ) from err

    def _map_error(self, err: Exception) -> Exception:
        err_msg = str(err)
        if self.config.api_key and self.config.api_key in err_msg:
            err_msg = err_msg.replace(self.config.api_key, "[REDACTED]")
        lower_msg = err_msg.lower()
        err_code = (
            getattr(err, "status_code", None)
            or getattr(err, "code", None)
            or getattr(err, "http_status", None)
        )
        if hasattr(err, "response") and hasattr(err.response, "status_code"):
            err_code = err.response.status_code

        if (
            err_code in (502, 503, 504)
            or "unavailable" in lower_msg
            or "service unavailable" in lower_msg
        ):
            return LLMProviderUnavailableException(f"Gemini service unavailable: {err_msg}")

        if err_code == 404 or "not found" in lower_msg or "not_found" in lower_msg:
            return LLMInvalidModelException(f"Gemini model not found: {err_msg}")

        if (
            err_code == 429
            or "quota" in lower_msg
            or "resourceexhausted" in lower_msg
            or "resource_exhausted" in lower_msg
            or "rate" in lower_msg
            or "too many requests" in lower_msg
        ):
            return LLMRateLimitException(f"Gemini rate limit or quota exceeded: {err_msg}")

        if (
            err_code in (401, 403)
            or "api_key" in lower_msg
            or "unauthenticated" in lower_msg
            or "invalid api key" in lower_msg
            or "permission_denied" in lower_msg
            or "permission denied" in lower_msg
        ):
            return LLMAuthenticationException(f"Gemini authentication failed: {err_msg}")

        if (
            "connection" in lower_msg
            or "connect" in lower_msg
            or "network" in lower_msg
            or "timeout" in lower_msg
            or "unreachable" in lower_msg
        ):
            return LLMConnectionException(f"Gemini connection error: {err_msg}")

        return LLMProviderException(f"Gemini provider error: {err_msg}")

    def _extract_json_from_text(self, text: str) -> str:
        cleaned = text.strip()
        cleaned = re.sub(r"<think>[\s\S]*?</think>", "", cleaned).strip()
        fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
        if fence_match:
            cleaned = fence_match.group(1).strip()
        return cleaned

    async def generate(self, prompt: str, **kwargs: Any) -> LLMResponse:
        client = self._get_client()
        types = _get_genai_types()
        config_params: dict[str, Any] = {}
        if "temperature" in kwargs:
            config_params["temperature"] = kwargs["temperature"]
        if "max_tokens" in kwargs:
            config_params["max_output_tokens"] = kwargs["max_tokens"]
        config = types.GenerateContentConfig(**config_params)

        try:
            response = await client.aio.models.generate_content(
                model=self.config.model,
                contents=prompt,
                config=config,
            )
            raw_text = response.text or ""

            raw_usage = None
            if hasattr(response, "usage_metadata") and response.usage_metadata is not None:
                usage = response.usage_metadata
                prompt_tokens = getattr(usage, "prompt_token_count", 0) or 0
                completion_tokens = getattr(usage, "candidates_token_count", 0) or 0
                total_tokens = getattr(
                    usage, "total_token_count", prompt_tokens + completion_tokens
                ) or (prompt_tokens + completion_tokens)
                raw_usage = {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                }
            self.last_usage = raw_usage

            return LLMResponse(
                content=raw_text,
                model=self.config.model,
                provider="gemini",
                raw_response=response,
                raw_usage=raw_usage,
            )
        except Exception as err:
            raise self._map_error(err) from err

    async def generate_structured[T: BaseModel](
        self, prompt: str, response_schema: type[T], **kwargs: Any
    ) -> T:
        client = self._get_client()
        types = _get_genai_types()
        config_params: dict[str, Any] = {
            "response_mime_type": "application/json",
            "response_schema": response_schema,
        }
        if "temperature" in kwargs:
            config_params["temperature"] = kwargs["temperature"]
        if "max_tokens" in kwargs:
            config_params["max_output_tokens"] = kwargs["max_tokens"]
        config = types.GenerateContentConfig(**config_params)

        try:
            response = await client.aio.models.generate_content(
                model=self.config.model,
                contents=prompt,
                config=config,
            )

            # Extract token telemetry for structured generation (Phase 13A-8)
            if hasattr(response, "usage_metadata") and response.usage_metadata is not None:
                usage = response.usage_metadata
                prompt_tokens = getattr(usage, "prompt_token_count", 0) or 0
                completion_tokens = getattr(usage, "candidates_token_count", 0) or 0
                total_tokens = getattr(
                    usage, "total_token_count", prompt_tokens + completion_tokens
                ) or (prompt_tokens + completion_tokens)
                self.last_usage = {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                }
            else:
                self.last_usage = None

            raw_text = response.text or ""
            if not raw_text.strip():
                raise LLMResponseException("Gemini returned empty structured content")

            cleaned_text = self._extract_json_from_text(raw_text)
            try:
                data = json.loads(cleaned_text)
            except json.JSONDecodeError as err:
                raise LLMResponseException(
                    f"Failed to parse Gemini structured JSON: {err}",
                    details={"raw_content": raw_text[:500]},
                ) from err

            if not isinstance(data, dict):
                raise LLMResponseException(
                    f"Expected JSON object for schema '{response_schema.__name__}', "
                    f"received '{type(data).__name__}'."
                )

            try:
                return response_schema.model_validate(data)
            except ValidationError as err:
                raise LLMResponseException(
                    f"Gemini output violates schema '{response_schema.__name__}': {err}",
                    details={"validation_errors": err.errors(include_url=False)},
                ) from err
        except Exception as err:
            if isinstance(err, LLMResponseException):
                raise
            raise self._map_error(err) from err

    async def stream(self, prompt: str, **kwargs: Any) -> AsyncIterator[str]:
        client = self._get_client()
        types = _get_genai_types()
        config_params: dict[str, Any] = {}
        if "temperature" in kwargs:
            config_params["temperature"] = kwargs["temperature"]
        if "max_tokens" in kwargs:
            config_params["max_output_tokens"] = kwargs["max_tokens"]
        config = types.GenerateContentConfig(**config_params)

        try:
            response = await client.aio.models.generate_content_stream(
                model=self.config.model,
                contents=prompt,
                config=config,
            )
            async for chunk in response:
                if chunk.text:
                    yield chunk.text
        except Exception as err:
            raise self._map_error(err) from err

    @property
    def capabilities(self) -> dict[str, Any]:
        return {
            "supports_streaming": True,
            "supports_structured_output": True,
            "supports_tools": True,
            "supports_system_messages": True,
        }

    @property
    def display_name(self) -> str:
        return f"Google Gemini ({self.config.model})"

    def get_model_info(self) -> ModelInfo:
        info = super().get_model_info()
        try:
            info.display_name = f"Google Gemini ({self.config.model})"
            return info
        except Exception:
            return info.model_copy(update={"display_name": f"Google Gemini ({self.config.model})"})
