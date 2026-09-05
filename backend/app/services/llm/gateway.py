import logging
from collections.abc import AsyncIterator

from pydantic import BaseModel

from app.core.exceptions import (
    LLMConnectionException,
    LLMProviderUnavailableException,
    LLMRateLimitException,
    LLMResponseException,
    LLMTimeoutException,
    LLMUnsupportedCapabilityException,
)
from app.schemas.llm import LLMResponse, LLMStreamChunk, ModelInfo
from app.services.llm.base import LLMProvider
from app.services.llm.factory import LLMFactory

logger = logging.getLogger(__name__)


class LLMGateway:
    """Authoritative provider-neutral gateway for LLM capabilities."""

    def __init__(
        self,
        primary_provider: LLMProvider | None = None,
        fallback_provider: LLMProvider | None = None,
    ) -> None:
        self._primary_provider = primary_provider
        self._fallback_provider = fallback_provider
        self._resolved = primary_provider is not None
        self.last_used_provider: str | None = None
        self.last_used_model: str | None = None

    def _ensure_providers(self) -> None:
        if not self._resolved:
            self._primary_provider = LLMFactory.create_provider()
            self._fallback_provider = LLMFactory.create_fallback_provider()
            self._resolved = True

    @property
    def primary(self) -> LLMProvider:
        self._ensure_providers()
        assert self._primary_provider is not None
        return self._primary_provider

    @property
    def fallback(self) -> LLMProvider | None:
        self._ensure_providers()
        return self._fallback_provider

    def get_model_info(self) -> ModelInfo:
        return self.primary.get_model_info()

    def check_capability(self, capability: str) -> bool:
        caps = self.primary.capabilities
        return getattr(caps, capability, False)

    async def generate(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> LLMResponse:
        if not prompt or not prompt.strip():
            raise LLMResponseException("Prompt cannot be empty.")

        try:
            res = await self.primary.generate(
                prompt=prompt,
                system_instruction=system_instruction,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )
            self.last_used_provider = self.primary.provider_name
            self.last_used_model = self.primary.model
            logger.info(
                "LLM generation fulfilled by %s (%s)", self.last_used_provider, self.last_used_model
            )
            return res
        except (
            LLMTimeoutException,
            LLMProviderUnavailableException,
            LLMConnectionException,
            LLMRateLimitException,
        ) as exc:
            if self.fallback is not None:
                logger.warning(
                    "Primary provider '%s' failed (%s); triggering fallback provider '%s'",
                    self.primary.provider_name,
                    type(exc).__name__,
                    self.fallback.provider_name,
                )
                res = await self.fallback.generate(
                    prompt=prompt,
                    system_instruction=system_instruction,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                )
                self.last_used_provider = self.fallback.provider_name
                self.last_used_model = self.fallback.model
                logger.info(
                    "LLM generation fulfilled by fallback %s (%s)",
                    self.last_used_provider,
                    self.last_used_model,
                )
                return res
            raise

    async def generate_structured[T: BaseModel](
        self,
        prompt: str,
        response_schema: type[T],
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
    ) -> T:
        if not self.primary.capabilities.supports_structured_output:
            raise LLMUnsupportedCapabilityException(
                f"Provider '{self.primary.provider_name}' with model '{self.primary.model}' "
                "does not support structured output."
            )

        try:
            res = await self.primary.generate_structured(
                prompt=prompt,
                response_schema=response_schema,
                system_instruction=system_instruction,
                temperature=temperature,
            )
            self.last_used_provider = self.primary.provider_name
            self.last_used_model = self.primary.model
            logger.info(
                "Structured generation fulfilled by %s (%s)",
                self.last_used_provider,
                self.last_used_model,
            )
            return res
        except (
            LLMTimeoutException,
            LLMProviderUnavailableException,
            LLMConnectionException,
            LLMRateLimitException,
        ) as exc:
            if self.fallback is not None and self.fallback.capabilities.supports_structured_output:
                logger.warning(
                    "Primary provider '%s' failed (%s); triggering fallback structured provider '%s'",
                    self.primary.provider_name,
                    type(exc).__name__,
                    self.fallback.provider_name,
                )
                res = await self.fallback.generate_structured(
                    prompt=prompt,
                    response_schema=response_schema,
                    system_instruction=system_instruction,
                    temperature=temperature,
                )
                self.last_used_provider = self.fallback.provider_name
                self.last_used_model = self.fallback.model
                return res
            raise

    async def stream(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> AsyncIterator[LLMStreamChunk]:
        """Dispatches streaming request with capability validation and restart-signaled fallback."""
        if not self.primary.capabilities.supports_streaming:
            raise LLMUnsupportedCapabilityException(
                f"Provider '{self.primary.provider_name}' with model '{self.primary.model}' "
                "does not support streaming."
            )

        yielded_any = False
        try:
            self.last_used_provider = self.primary.provider_name
            self.last_used_model = self.primary.model
            async for chunk in self.primary.stream(
                prompt=prompt,
                system_instruction=system_instruction,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            ):
                yielded_any = True
                yield chunk
        except (
            LLMTimeoutException,
            LLMProviderUnavailableException,
            LLMConnectionException,
            LLMRateLimitException,
        ) as exc:
            if self.fallback is not None and self.fallback.capabilities.supports_streaming:
                logger.warning(
                    "Primary provider '%s' stream failed (%s); triggering fallback stream '%s' (yielded_any=%s)",
                    self.primary.provider_name,
                    type(exc).__name__,
                    self.fallback.provider_name,
                    yielded_any,
                )
                self.last_used_provider = self.fallback.provider_name
                self.last_used_model = self.fallback.model

                if yielded_any:
                    yield LLMStreamChunk(delta="", provider_switched=True)

                async for chunk in self.fallback.stream(
                    prompt=prompt,
                    system_instruction=system_instruction,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                ):
                    yield chunk
            else:
                raise
