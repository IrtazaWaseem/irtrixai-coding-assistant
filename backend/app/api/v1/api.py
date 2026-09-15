from fastapi import APIRouter

from app.api.v1 import llm, tasks, workspaces
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(workspaces.router, prefix="/workspaces", tags=["workspaces"])
api_router.include_router(llm.router, prefix="/llm", tags=["llm"])

router = api_router


@api_router.get("/status")
async def get_status():
    return {
        "status": "active",
        "version": "0.1.0",
        "environment": settings.ENVIRONMENT,
    }
