from fastapi import APIRouter

from app.api.v1 import llm, tasks, workspaces

api_router = APIRouter()


@api_router.get("/status")
async def get_status() -> dict[str, str]:
    return {"status": "active", "api_version": "v1"}


api_router.include_router(workspaces.router, prefix="/workspaces", tags=["workspaces"])
api_router.include_router(llm.router, prefix="/llm", tags=["llm"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
