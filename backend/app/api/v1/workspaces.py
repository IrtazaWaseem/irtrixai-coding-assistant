import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    AppException,
    EntityNotFoundException,
    FileSizeLimitExceededException,
    ProtectedFileAccessViolationException,
    SecurityViolationException,
    ToolExecutionException,
)
from app.db.session import get_db
from app.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceFileReadResponse,
    WorkspaceFileWriteRequest,
    WorkspaceFileWriteResponse,
    WorkspaceRead,
    WorkspaceTreeResponse,
)
from app.services.workspace_service import WorkspaceService
from app.tools.file_tools import read_file, write_file
from app.tools.validators import validate_workspace_dir

router = APIRouter()

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
    max_depth: Annotated[int, Query(ge=1, le=10, description="Max traversal depth")] = 3,
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


def _execute_read_file(
    root_path: str, relative_path: str, workspace_id: uuid.UUID
) -> WorkspaceFileReadResponse:
    try:
        base_dir = validate_workspace_dir(root_path)
        tool_res = read_file(
            path=relative_path,
            workspace_root=base_dir,
            raise_on_error=True,
        )
        data = tool_res.output or {}
        raw_content = data.get("content", "")
        return WorkspaceFileReadResponse(
            workspace_id=workspace_id,
            path=data.get("path", relative_path),
            content=raw_content,
            size=len(raw_content.encode("utf-8")),
            total_lines=data.get("total_lines", 0),
            truncated=data.get("truncated", False),
        )
    except EntityNotFoundException as err:
        raise AppException(
            status_code=404,
            message=f"File '{relative_path}' not found in workspace.",
            details={"path": relative_path},
        ) from err
    except (SecurityViolationException, ProtectedFileAccessViolationException) as err:
        status_code = 403 if isinstance(err, ProtectedFileAccessViolationException) else 400
        raise AppException(
            status_code=status_code,
            message=str(err),
            details={"path": relative_path},
        ) from err
    except FileSizeLimitExceededException as err:
        raise AppException(
            status_code=413,
            message=f"File exceeds maximum read limit ({settings.MAX_READ_FILE_BYTES} bytes).",
            details={"path": relative_path},
        ) from err
    except ToolExecutionException as err:
        raise AppException(
            status_code=400,
            message=str(err),
            details={"path": relative_path},
        ) from err
    except Exception as err:
        raise AppException(
            status_code=500,
            message=f"Failed to read file: {err}",
            details={"path": relative_path},
        ) from err


def _execute_write_file(
    root_path: str, relative_path: str, content: str, workspace_id: uuid.UUID
) -> WorkspaceFileWriteResponse:
    try:
        base_dir = validate_workspace_dir(root_path)
        tool_res = write_file(
            path=relative_path,
            content=content,
            workspace_root=base_dir,
            raise_on_error=True,
        )
        data = tool_res.output or {}
        return WorkspaceFileWriteResponse(
            workspace_id=workspace_id,
            path=data.get("path", relative_path),
            bytes_written=data.get("bytes_written", 0),
            is_new_file=data.get("is_new_file", False),
        )
    except (SecurityViolationException, ProtectedFileAccessViolationException) as err:
        status_code = 403 if isinstance(err, ProtectedFileAccessViolationException) else 400
        raise AppException(
            status_code=status_code,
            message=str(err),
            details={"path": relative_path},
        ) from err
    except FileSizeLimitExceededException as err:
        raise AppException(
            status_code=413,
            message=f"File content exceeds maximum allowed write size ({settings.MAX_READ_FILE_BYTES} bytes).",
            details={"path": relative_path},
        ) from err
    except ToolExecutionException as err:
        raise AppException(
            status_code=400,
            message=str(err),
            details={"path": relative_path},
        ) from err
    except Exception as err:
        raise AppException(
            status_code=500,
            message=f"Failed to write file: {err}",
            details={"path": relative_path},
        ) from err


# File read: path parameter
@router.get(
    "/{workspace_id}/files/{file_path:path}",
    response_model=WorkspaceFileReadResponse,
    summary="Read a workspace file by path",
)
async def read_workspace_file_path(
    workspace_id: uuid.UUID,
    file_path: str,
    db: SessionDep,
) -> WorkspaceFileReadResponse:
    workspace = await WorkspaceService.get_workspace_by_id(db, workspace_id)
    return _execute_read_file(workspace.root_path, file_path, workspace.id)


# File read: query parameter
@router.get(
    "/{workspace_id}/file",
    response_model=WorkspaceFileReadResponse,
    summary="Read a workspace file via query param",
)
async def read_workspace_file_query(
    workspace_id: uuid.UUID,
    path: Annotated[str, Query(min_length=1, description="Workspace-relative file path")],
    db: SessionDep,
) -> WorkspaceFileReadResponse:
    workspace = await WorkspaceService.get_workspace_by_id(db, workspace_id)
    return _execute_read_file(workspace.root_path, path, workspace.id)


# File write: path parameter
@router.put(
    "/{workspace_id}/files/{file_path:path}",
    response_model=WorkspaceFileWriteResponse,
    summary="Write or save a workspace file by path",
)
async def write_workspace_file_path(
    workspace_id: uuid.UUID,
    file_path: str,
    payload: WorkspaceFileWriteRequest,
    db: SessionDep,
) -> WorkspaceFileWriteResponse:
    workspace = await WorkspaceService.get_workspace_by_id(db, workspace_id)
    return _execute_write_file(workspace.root_path, file_path, payload.content, workspace.id)


# File write: query parameter
@router.put(
    "/{workspace_id}/file",
    response_model=WorkspaceFileWriteResponse,
    summary="Write or save a workspace file via query param",
)
async def write_workspace_file_query(
    workspace_id: uuid.UUID,
    path: Annotated[str, Query(min_length=1, description="Workspace-relative file path")],
    payload: WorkspaceFileWriteRequest,
    db: SessionDep,
) -> WorkspaceFileWriteResponse:
    workspace = await WorkspaceService.get_workspace_by_id(db, workspace_id)
    return _execute_write_file(workspace.root_path, path, payload.content, workspace.id)
