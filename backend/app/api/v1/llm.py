from fastapi import APIRouter

from app.schemas.llm import ModelInfo
from app.services.llm.gateway import LLMGateway

router = APIRouter()


@router.get("/info", response_model=ModelInfo)
async def get_llm_info() -> ModelInfo:
    """Returns provider and model metadata for frontend display without secrets."""
    gateway = LLMGateway()
    return gateway.get_model_info()
