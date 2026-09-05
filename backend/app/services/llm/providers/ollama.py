import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from pydantic import BaseModel

from app.core.exceptions import (
    LLMConnectionException,
    LLMInvalidModelException,
    LLMProviderException,
    LLMProviderUnavailableException,
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


class OllamaProvider(LLMProvider):
    """Adapter for local Ollama execution."""

    def __init__(
        self,
        config: LLMConfig,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(config)
        if not self.model:
            raise LLMInvalidModelException("Ollama model ID cannot be empty.")
        self.base_url = (config.base_url or "http://localhost:11434").rstrip("/")
        self._injected_client = client

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_streaming=True,
            supports_structured_output=True,
            supports_tools=True,
            supports_system_messages=True,
        )

    def _build_payload(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        stream: bool = False,
        format_json: bool = False,
    ) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if system_instruction and system_instruction.strip():
            messages.append({"role": "system", "content": system_instruction.strip()})
        messages.append({"role": "user", "content": prompt})

        options: dict[str, Any] = {}
        if temperature is not None:
            options["temperature"] = temperature
        if max_output_tokens is not None:
            options["num_predict"] = max_output_tokens

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
        }
        if options:
            payload["options"] = options
        if format_json:
            payload["format"] = "json"

        return payload

    def _handle_http_error(self, err: Exception) -> None:
        if isinstance(err, httpx.TimeoutException):
            raise LLMTimeoutException(
                f"Ollama request timed out after {self.config.timeout_seconds}s."
            ) from err
        if isinstance(err, (httpx.ConnectError, httpx.NetworkError)):
            raise LLMConnectionException(
                f"Failed to connect to Ollama at '{self.base_url}'. Verify the daemon is running."
            ) from err
        if isinstance(err, httpx.HTTPStatusError):
            status = err.response.status_code
            text = err.response.text
            if status == 404:
                raise LLMInvalidModelException(
                    f"Ollama model '{self.model}' not found. Run 'ollama pull {self.model}'."
                ) from err
            if status in {500, 502, 503, 504}:
                raise LLMProviderUnavailableException(
                    f"Ollama service error ({status}): {text}"
                ) from err
            raise LLMProviderException(f"Ollama HTTP error ({status}): {text}") from err

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
        url = f"{self.base_url}/api/chat"

        try:
            if self._injected_client is not None:
                resp = await self._injected_client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
            else:
                async with httpx.AsyncClient(
                    timeout=self.config.timeout_seconds
                ) as client:
                    resp = await client.post(url, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
        except Exception as err:
            self._handle_http_error(err)
            raise LLMProviderException(f"Unexpected Ollama error: {err}") from err

        message = data.get("message", {})
        content = message.get("content", "")
        if not content and not data.get("done", False):
            raise LLMResponseException("Ollama returned empty response.")

        usage: dict[str, Any] = {}
        if "prompt_eval_count" in data:
            usage["prompt_tokens"] = data["prompt_eval_count"]
        if "eval_count" in data:
            usage["completion_tokens"] = data["eval_count"]

        return LLMResponse(
            content=content,
            model=self.model,
            provider="ollama",
            finish_reason=data.get("done_reason", "stop"),
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
        schema_json = json.dumps(response_schema.model_json_schema())
        instruction = (
            f"{system_instruction or ''}\n"
            f"You MUST reply with a valid JSON object strictly matching this schema: {schema_json}"
        ).strip()

        payload = self._build_payload(
            prompt=prompt,
            system_instruction=instruction,
            temperature=temperature,
            stream=False,
            format_json=True,
        )
        url = f"{self.base_url}/api/chat"

        try:
            if self._injected_client is not None:
                resp = await self._injected_client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
            else:
                async with httpx.AsyncClient(
                    timeout=self.config.timeout_seconds
                ) as client:
                    resp = await client.post(url, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
        except Exception as err:
            self._handle_http_error(err)
            raise LLMProviderException(f"Unexpected Ollama error: {err}") from err

        content = data.get("message", {}).get("content", "")
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
        url = f"{self.base_url}/api/chat"

        try:
            client_ctx = (
                self._injected_client
                if self._injected_client is not None
                else httpx.AsyncClient(timeout=self.config.timeout_seconds)
            )
            async with client_ctx.stream("POST", url, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk_data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    delta = chunk_data.get("message", {}).get("content", "")
                    done = chunk_data.get("done", False)
                    reason = chunk_data.get("done_reason") if done else None
                    yield LLMStreamChunk(delta=delta, finish_reason=reason)
        except Exception as err:
            self._handle_http_error(err)
            raise LLMProviderException(
                f"Unexpected Ollama streaming error: {err}"
            ) from err
