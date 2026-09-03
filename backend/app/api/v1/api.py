from fastapi import APIRouter

from app.api.v1.workspaces import router as workspaces_router

api_router = APIRouter()


@api_router.get("/status")
async def get_v1_status() -> dict[str, str]:
    return {"api_version": "v1", "status": "active"}


api_router.include_router(workspaces_router, prefix="/workspaces", tags=["Workspaces"])
