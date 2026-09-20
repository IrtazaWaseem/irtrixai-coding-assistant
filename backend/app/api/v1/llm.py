from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings
from app.services.llm.gateway import LLMGateway

router = APIRouter()
gateway = LLMGateway()


class ProviderOption(BaseModel):
    id: str
    name: str
    available: bool
    reason: str | None = None
    default_model: str
    models: list[str]


class ProvidersResponse(BaseModel):
    providers: list[ProviderOption]
    default_provider: str
    default_model: str


def get_available_providers() -> list[ProviderOption]:
    # 1. Ollama (local execution)
    ollama_base = settings.OLLAMA_BASE_URL.strip() if settings.OLLAMA_BASE_URL else ""
    ollama_avail = bool(ollama_base)
    ollama_default = settings.OLLAMA_MODEL or "qwen-gpu-tuned"
    ollama_models = [ollama_default]
    for m in ["deepseek-r1:8b", "llama3.2:latest"]:
        if m not in ollama_models:
            ollama_models.append(m)

    # 2. Gemini
    gemini_key = settings.GEMINI_API_KEY.strip() if settings.GEMINI_API_KEY else ""
    gemini_avail = bool(gemini_key)
    gemini_default = settings.GEMINI_MODEL or "gemini-2.5-flash"
    gemini_models = [gemini_default]
    for m in ["gemini-2.5-pro", "gemini-2.0-flash"]:
        if m not in gemini_models:
            gemini_models.append(m)

    # 3. Groq
    groq_key = settings.GROQ_API_KEY.strip() if settings.GROQ_API_KEY else ""
    groq_avail = bool(groq_key)
    groq_default = settings.GROQ_MODEL or "llama-3.3-70b-versatile"
    groq_models = [groq_default]
    for m in ["llama-3.1-8b-instant"]:
        if m not in groq_models:
            groq_models.append(m)

    return [
        ProviderOption(
            id="ollama",
            name="Ollama (Local)",
            available=ollama_avail,
            reason=None if ollama_avail else "Ollama base URL not configured",
            default_model=ollama_default,
            models=ollama_models,
        ),
        ProviderOption(
            id="gemini",
            name="Google Gemini",
            available=gemini_avail,
            reason=None if gemini_avail else "Gemini API key not configured",
            default_model=gemini_default,
            models=gemini_models,
        ),
        ProviderOption(
            id="groq",
            name="Groq Cloud",
            available=groq_avail,
            reason=None if groq_avail else "Groq API key not configured",
            default_model=groq_default,
            models=groq_models,
        ),
    ]


@router.get("/providers", response_model=ProvidersResponse)
async def get_providers():
    providers = get_available_providers()
    default_prov = settings.PRIMARY_LLM_PROVIDER.strip().lower()
    default_mod = (
        settings.PRIMARY_LLM_MODEL.strip()
        if settings.PRIMARY_LLM_MODEL
        else settings.get_provider_default_model(default_prov)
    )
    return ProvidersResponse(
        providers=providers,
        default_provider=default_prov,
        default_model=default_mod,
    )


@router.get("/info")
async def get_llm_info():
    info = gateway.get_model_info()
    data = info.model_dump() if hasattr(info, "model_dump") else dict(info)
    data["primary_provider"] = data.get("provider", "gemini")
    data["models"] = [data.get("model", "gemini-2.5-flash")]
    data["fallback_provider"] = getattr(settings, "FALLBACK_LLM_PROVIDER", None)
    data["providers"] = [p.model_dump() for p in get_available_providers()]
    return data
