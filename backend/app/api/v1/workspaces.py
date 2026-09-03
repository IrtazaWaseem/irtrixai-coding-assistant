import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceRead,
    WorkspaceTreeResponse,
)
from app.services.workspace_service import WorkspaceService

router = APIRouter()

# Type alias for database dependency injection
SessionDep = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "",
    response_model=WorkspaceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new workspace",
)
async def create_workspace(
    payload: WorkspaceCreate,
    db: SessionDep,
) -> WorkspaceRead:
    workspace = await WorkspaceService.create_workspace(db, payload)
    return WorkspaceRead.model_validate(workspace)


@router.get(
    "",
    response_model=list[WorkspaceRead],
    summary="List registered workspaces",
)
async def list_workspaces(
    db: SessionDep,
) -> Sequence[WorkspaceRead]:
    workspaces = await WorkspaceService.get_all_workspaces(db)
    return [WorkspaceRead.model_validate(w) for w in workspaces]


@router.get(
    "/{workspace_id}",
    response_model=WorkspaceRead,
    summary="Get workspace details",
)
async def get_workspace(
    workspace_id: uuid.UUID,
    db: SessionDep,
) -> WorkspaceRead:
    workspace = await WorkspaceService.get_workspace_by_id(db, workspace_id)
    return WorkspaceRead.model_validate(workspace)


@router.get(
    "/{workspace_id}/tree",
    response_model=WorkspaceTreeResponse,
    summary="Get workspace file tree",
)
async def get_workspace_tree(
    workspace_id: uuid.UUID,
    db: SessionDep,
    max_depth: Annotated[
        int, Query(ge=1, le=10, description="Max traversal depth")
    ] = 3,
) -> WorkspaceTreeResponse:
    workspace = await WorkspaceService.get_workspace_by_id(db, workspace_id)
    tree, total, truncated = WorkspaceService.build_file_tree(
        root_path=workspace.root_path,
        max_depth=max_depth,
        max_entries=1000,
    )
    return WorkspaceTreeResponse(
        workspace_id=workspace.id,
        root_path=workspace.root_path,
        tree=tree,
        total_entries=total,
        truncated=truncated,
    )
