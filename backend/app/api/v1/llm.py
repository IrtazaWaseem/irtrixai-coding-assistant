from fastapi import APIRouter

from app.core.config import settings
from app.services.llm.gateway import LLMGateway

router = APIRouter()
gateway = LLMGateway()


@router.get("/info")
async def get_llm_info():
    info = gateway.get_model_info()
    data = info.model_dump() if hasattr(info, "model_dump") else dict(info)
    data["primary_provider"] = data.get("provider", "gemini")
    data["models"] = [data.get("model", "gemini-2.5-flash")]
    data["fallback_provider"] = getattr(settings, "FALLBACK_LLM_PROVIDER", None)
    return data
