import logging
from collections.abc import AsyncIterator

from pydantic import BaseModel

from app.core.exceptions import (
    LLMAuthenticationException,
    LLMConfigurationException,
    LLMConnectionException,
    LLMInvalidModelException,
    LLMProviderUnavailableException,
    LLMRateLimitException,
    LLMResponseException,
    LLMTimeoutException,
    LLMUnsupportedCapabilityException,
)
from app.schemas.llm import LLMConfig, LLMResponse, LLMStreamChunk, ModelInfo
from app.services.llm.base import LLMProvider
from app.services.llm.factory import LLMFactory

logger = logging.getLogger(__name__)


def _has_capability(provider: LLMProvider | None, capability: str) -> bool:
    if provider is None:
        return False
    caps = getattr(provider, "capabilities", None)
    if caps is None:
        return False
    if isinstance(caps, dict):
        return bool(caps.get(capability, False))
    return bool(getattr(caps, capability, False))


FALLBACK_ELIGIBLE_EXCEPTIONS = (
    LLMTimeoutException,
    LLMProviderUnavailableException,
    LLMConnectionException,
    LLMRateLimitException,
    LLMInvalidModelException,
)


class LLMGateway:
    """Authoritative provider-neutral gateway for LLM capabilities with token telemetry."""

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
        self.last_usage: dict[str, int] | None = None

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
        return _has_capability(self.primary, capability)

    async def generate(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        allow_fallback: bool = True,
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
            self.last_usage = self.primary.last_usage
            return res
        except FALLBACK_ELIGIBLE_EXCEPTIONS as exc:
            if allow_fallback and self.fallback is not None:
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
                self.last_usage = self.fallback.last_usage
                return res
            raise

    async def generate_structured[T: BaseModel](
        self,
        prompt: str,
        response_schema: type[T],
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
        allow_fallback: bool = True,
    ) -> T:
        if not _has_capability(self.primary, "supports_structured_output"):
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
            self.last_usage = self.primary.last_usage
            return res
        except FALLBACK_ELIGIBLE_EXCEPTIONS as exc:
            if (
                allow_fallback
                and self.fallback is not None
                and _has_capability(self.fallback, "supports_structured_output")
            ):
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
                self.last_usage = self.fallback.last_usage
                return res
            raise

    async def stream(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        allow_fallback: bool = True,
    ) -> AsyncIterator[LLMStreamChunk]:
        if not _has_capability(self.primary, "supports_streaming"):
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
        except FALLBACK_ELIGIBLE_EXCEPTIONS as exc:
            if (
                allow_fallback
                and self.fallback is not None
                and _has_capability(self.fallback, "supports_streaming")
            ):
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


def create_task_llm_gateway(provider: str, model: str) -> LLMGateway:
    from app.core.config import settings

    prov = provider.strip().lower()
    if prov not in ("gemini", "groq", "ollama"):
        raise LLMConfigurationException(
            f"Unsupported LLM provider '{prov}'. Allowed providers: 'gemini', 'groq', 'ollama'."
        )

    clean_model = model.strip()
    if not clean_model:
        clean_model = settings.get_provider_default_model(prov)

    api_key, base_url = settings.get_provider_credentials(prov)
    if prov in ("gemini", "groq") and not (api_key and api_key.strip()):
        raise LLMAuthenticationException(
            f"Provider '{prov}' is unavailable: {prov.capitalize()} API key is not configured."
        )

    config = LLMConfig(
        provider=prov,
        model=clean_model,
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=settings.LLM_REQUEST_TIMEOUT_SECONDS,
        max_retries=settings.LLM_MAX_RETRIES,
        thinking_level=settings.LLM_THINKING_LEVEL,
    )
    primary = LLMFactory.create_provider(config)

    fallback = None
    if settings.FALLBACK_LLM_PROVIDER:
        fallback_prov = settings.FALLBACK_LLM_PROVIDER.strip().lower()
        if fallback_prov != prov:
            try:
                fallback = LLMFactory.create_fallback_provider()
            except Exception:
                fallback = None

    return LLMGateway(primary_provider=primary, fallback_provider=fallback)
