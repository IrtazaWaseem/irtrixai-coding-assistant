import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from pydantic import BaseModel

from app.core.config import settings
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
        self._timeout = max(float(self.config.timeout_seconds or 60.0), 180.0)

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
            raise LLMTimeoutException(f"Ollama request timed out after {self._timeout}s.") from err
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
            format_json=False,
        )
        url = f"{self.base_url}/api/chat"

        try:
            if self._injected_client is not None:
                resp = await self._injected_client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
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

        p_tokens = data.get("prompt_eval_count", 0) or 0
        c_tokens = data.get("eval_count", 0) or 0
        self.last_usage = {
            "prompt_tokens": p_tokens,
            "completion_tokens": c_tokens,
            "total_tokens": p_tokens + c_tokens,
        }

        return LLMResponse(
            content=content,
            model=self.model,
            provider="ollama",
            finish_reason=data.get("done_reason", "stop"),
            raw_usage=self.last_usage,
        )

    async def generate_structured[T: BaseModel](
        self,
        prompt: str,
        response_schema: type[T],
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> T:
        schema_dict = response_schema.model_json_schema()
        schema_json = json.dumps(schema_dict)
        instruction = (
            f"{system_instruction or ''}\n"
            f"You MUST output populated values for the fields defined in this schema: {schema_json}. "
            "Do NOT output the schema definitions or properties metadata; output the concrete populated data."
        ).strip()

        effective_max_tokens = (
            max_output_tokens
            if max_output_tokens is not None
            else getattr(settings, "OLLAMA_MAX_OUTPUT_TOKENS", 4096)
        )

        payload = self._build_payload(
            prompt=prompt,
            system_instruction=instruction,
            temperature=temperature,
            max_output_tokens=effective_max_tokens,
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
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(url, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
        except Exception as err:
            self._handle_http_error(err)
            raise LLMProviderException(f"Unexpected Ollama error: {err}") from err

        p_tokens = data.get("prompt_eval_count", 0) or 0
        c_tokens = data.get("eval_count", 0) or 0
        self.last_usage = {
            "prompt_tokens": p_tokens,
            "completion_tokens": c_tokens,
            "total_tokens": p_tokens + c_tokens,
        }

        done_reason = data.get("done_reason")
        if done_reason in ("length", "max_tokens"):
            raise LLMResponseException(
                "Ollama response was truncated by the token limit (done_reason=length); "
                "the output is incomplete and cannot be trusted as valid structured output."
            )

        content = data.get("message", {}).get("content", "")

        # Defensive unwrap: if a model outputs {"properties": {...}}, extract the values
        try:
            parsed_raw = json.loads(content)
            if (
                isinstance(parsed_raw, dict)
                and "properties" in parsed_raw
                and not any(k in parsed_raw for k in response_schema.model_fields)
            ):
                extracted = {}
                for k, v in parsed_raw["properties"].items():
                    if isinstance(v, dict):
                        extracted[k] = v.get("default") or v.get("value") or v.get("example") or ""
                    else:
                        extracted[k] = v
                content = json.dumps(extracted)
        except Exception:
            pass

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
            format_json=False,
        )
        url = f"{self.base_url}/api/chat"

        try:
            client_ctx = (
                self._injected_client
                if self._injected_client is not None
                else httpx.AsyncClient(timeout=self._timeout)
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
            raise LLMProviderException(f"Unexpected Ollama streaming error: {err}") from err
