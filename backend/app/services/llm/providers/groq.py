import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from pydantic import BaseModel

from app.core.exceptions import (
    LLMAuthenticationException,
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


class GroqProvider(LLMProvider):
    """Adapter for cloud Groq execution via official REST endpoint."""

    def __init__(
        self,
        config: LLMConfig,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(config)
        api_key = config.get_api_key()
        if not api_key:
            raise LLMAuthenticationException("Groq API key is required but missing.")
        if not self.model:
            raise LLMInvalidModelException("Groq model ID cannot be empty.")
        self.base_url = (config.base_url or "https://api.groq.com/openai/v1").rstrip(
            "/"
        )
        self._injected_client = client

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_streaming=True,
            supports_structured_output=True,
            supports_tools=True,
            supports_system_messages=True,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.get_api_key()}",
            "Content-Type": "application/json",
        }

    def _build_payload(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        stream: bool = False,
        response_format: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if system_instruction and system_instruction.strip():
            messages.append({"role": "system", "content": system_instruction.strip()})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_output_tokens is not None:
            payload["max_tokens"] = max_output_tokens
        if response_format is not None:
            payload["response_format"] = response_format

        return payload

    def _handle_http_error(self, err: Exception) -> None:
        if isinstance(err, httpx.TimeoutException):
            raise LLMTimeoutException(
                f"Groq request timed out after {self.config.timeout_seconds}s."
            ) from err
        if isinstance(err, (httpx.ConnectError, httpx.NetworkError)):
            raise LLMConnectionException(
                f"Failed to connect to Groq endpoint '{self.base_url}'."
            ) from err
        if isinstance(err, httpx.HTTPStatusError):
            status = err.response.status_code
            safe_text = self._sanitize(err.response.text)
            if status == 401:
                raise LLMAuthenticationException(
                    "Groq API key authentication failed."
                ) from err
            if status in {400, 404}:
                raise LLMInvalidModelException(
                    f"Groq model '{self.model}' is invalid or unsupported: {safe_text}"
                ) from err
            if status == 429:
                raise LLMRateLimitException(
                    f"Groq rate limit or quota exceeded: {safe_text}"
                ) from err
            if status in {500, 502, 503, 504}:
                raise LLMProviderUnavailableException(
                    f"Groq service unavailable ({status}): {safe_text}"
                ) from err
            raise LLMProviderException(
                f"Groq HTTP error ({status}): {safe_text}"
            ) from err

    async def generate(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> LLMResponse:
        payload = self._build_payload(
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            stream=False,
        )
        url = f"{self.base_url}/chat/completions"

        try:
            if self._injected_client is not None:
                resp = await self._injected_client.post(
                    url, json=payload, headers=self._headers()
                )
                resp.raise_for_status()
                data = resp.json()
            else:
                async with httpx.AsyncClient(
                    timeout=self.config.timeout_seconds
                ) as client:
                    resp = await client.post(url, json=payload, headers=self._headers())
                    resp.raise_for_status()
                    data = resp.json()
        except Exception as err:
            self._handle_http_error(err)
            raise LLMProviderException(
                f"Unexpected Groq error: {self._sanitize(str(err))}"
            ) from err

        choices = data.get("choices", [])
        if not choices:
            raise LLMResponseException("Groq returned no choices.")

        choice = choices[0]
        content = choice.get("message", {}).get("content", "")
        finish_reason = choice.get("finish_reason", "stop")

        usage = data.get("usage")
        return LLMResponse(
            content=content,
            model=self.model,
            provider="groq",
            finish_reason=finish_reason,
            raw_usage=usage,
        )

    async def generate_structured[T: BaseModel](
        self,
        prompt: str,
        response_schema: type[T],
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
    ) -> T:
        schema_json = json.dumps(response_schema.model_json_schema())
        instruction = (
            f"{system_instruction or ''}\n"
            f"You MUST respond with a JSON object strictly conforming to this schema: {schema_json}"
        ).strip()

        payload = self._build_payload(
            prompt=prompt,
            system_instruction=instruction,
            temperature=temperature,
            stream=False,
            response_format={"type": "json_object"},
        )
        url = f"{self.base_url}/chat/completions"

        try:
            if self._injected_client is not None:
                resp = await self._injected_client.post(
                    url, json=payload, headers=self._headers()
                )
                resp.raise_for_status()
                data = resp.json()
            else:
                async with httpx.AsyncClient(
                    timeout=self.config.timeout_seconds
                ) as client:
                    resp = await client.post(url, json=payload, headers=self._headers())
                    resp.raise_for_status()
                    data = resp.json()
        except Exception as err:
            self._handle_http_error(err)
            raise LLMProviderException(
                f"Unexpected Groq error: {self._sanitize(str(err))}"
            ) from err

        choices = data.get("choices", [])
        if not choices:
            raise LLMResponseException(
                "Groq returned no choices for structured output."
            )

        content = choices[0].get("message", {}).get("content", "")
        return parse_structured_output(content, response_schema)

    async def stream(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> AsyncIterator[LLMStreamChunk]:
        payload = self._build_payload(
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            stream=True,
        )
        url = f"{self.base_url}/chat/completions"

        try:
            client_ctx = (
                self._injected_client
                if self._injected_client is not None
                else httpx.AsyncClient(timeout=self.config.timeout_seconds)
            )
            async with client_ctx.stream(
                "POST", url, json=payload, headers=self._headers()
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    line_data = line[6:].strip()
                    if line_data == "[DONE]":
                        break
                    try:
                        chunk_json = json.loads(line_data)
                    except json.JSONDecodeError:
                        continue

                    choices = chunk_json.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {}).get("content", "")
                    reason = choices[0].get("finish_reason")
                    yield LLMStreamChunk(delta=delta, finish_reason=reason)
        except Exception as err:
            self._handle_http_error(err)
            raise LLMProviderException(
                f"Unexpected Groq stream error: {self._sanitize(str(err))}"
            ) from err
