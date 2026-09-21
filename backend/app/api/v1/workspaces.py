import hashlib
import logging
import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    AppException,
    ContainerExecutionException,
    ContainerTimeoutException,
    DisallowedCommandException,
    EntityNotFoundException,
    FileSizeLimitExceededException,
    ProtectedFileAccessViolationException,
    SecurityViolationException,
    ToolExecutionException,
)
from app.db.session import get_db
from app.schemas.workspace import (
    TerminalExecuteRequest,
    TerminalExecuteResponse,
    WorkspaceCreate,
    WorkspaceFileReadResponse,
    WorkspaceFileWriteRequest,
    WorkspaceFileWriteResponse,
    WorkspaceRead,
    WorkspaceTreeResponse,
)
from app.services.execution_service import ExecutionService
from app.services.workspace_service import WorkspaceService
from app.tools.file_tools import read_file, write_file
from app.tools.validators import validate_safe_path, validate_workspace_dir

logger = logging.getLogger(__name__)

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
            max_output_bytes=settings.MAX_READ_FILE_BYTES,
        )
        data = tool_res.output or {}
        if data.get("truncated", False):
            raise AppException(
                status_code=413,
                message="File exceeds the editor read limit.",
                details={"path": relative_path, "code": "FILE_TRUNCATED"},
            )

        raw_content = data.get("content", "")
        content_hash = (
            data.get("content_hash") or hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
        )

        return WorkspaceFileReadResponse(
            workspace_id=workspace_id,
            path=data.get("path", relative_path),
            content=raw_content,
            content_hash=content_hash,
            size=len(raw_content.encode("utf-8")),
            total_lines=data.get("total_lines", 0),
            truncated=False,
        )
    except EntityNotFoundException as err:
        raise AppException(
            status_code=404,
            message=f"File '{relative_path}' not found in workspace.",
            details={"path": relative_path, "code": "FILE_NOT_FOUND"},
        ) from err
    except ProtectedFileAccessViolationException as err:
        raise AppException(
            status_code=403,
            message=f"Access denied: path '{relative_path}' is protected.",
            details={"path": relative_path, "code": "PROTECTED_FILE"},
        ) from err
    except SecurityViolationException as err:
        raise AppException(
            status_code=400,
            message=f"Access denied: path '{relative_path}' is outside workspace boundary.",
            details={"path": relative_path, "code": "PATH_TRAVERSAL"},
        ) from err
    except FileSizeLimitExceededException as err:
        raise AppException(
            status_code=413,
            message=f"File exceeds maximum read limit ({settings.MAX_READ_FILE_BYTES} bytes).",
            details={"path": relative_path, "code": "FILE_TOO_LARGE"},
        ) from err
    except ToolExecutionException as err:
        if "binary" in str(err).lower():
            raise AppException(
                status_code=400,
                message=f"Cannot read binary file '{relative_path}' as text.",
                details={"path": relative_path, "code": "BINARY_FILE"},
            ) from err
        logger.error("Tool execution error reading '%s': %s", relative_path, err)
        raise AppException(
            status_code=400,
            message="Failed to read workspace file.",
            details={"path": relative_path, "code": "READ_ERROR"},
        ) from err
    except AppException:
        raise
    except Exception as err:
        logger.exception("Unhandled error reading file '%s': %s", relative_path, err)
        raise AppException(
            status_code=500,
            message="Failed to read workspace file.",
            details={"path": relative_path, "code": "INTERNAL_ERROR"},
        ) from err


def _execute_write_file(
    root_path: str,
    relative_path: str,
    payload: WorkspaceFileWriteRequest,
    workspace_id: uuid.UUID,
) -> WorkspaceFileWriteResponse:
    try:
        base_dir = validate_workspace_dir(root_path)
        safe_file = validate_safe_path(base_dir, relative_path, must_exist=False)

        # Optimistic Concurrency Check
        if safe_file.exists():
            if safe_file.is_dir():
                raise AppException(
                    status_code=400,
                    message="Cannot write to a directory.",
                    details={"path": relative_path, "code": "TARGET_IS_DIRECTORY"},
                )

            if payload.expected_content_hash is None:
                raise AppException(
                    status_code=409,
                    message="File already exists on disk. Expected content hash must be provided.",
                    details={"path": relative_path, "code": "FILE_ALREADY_EXISTS"},
                )

            try:
                current_bytes = safe_file.read_bytes()
                current_hash = hashlib.sha256(current_bytes).hexdigest()
            except Exception as err:
                logger.exception(
                    "Failed reading existing file for concurrency verification: %s",
                    relative_path,
                )
                raise AppException(
                    status_code=500,
                    message="Failed to verify existing file state.",
                    details={"path": relative_path, "code": "READ_CHECK_ERROR"},
                ) from err

            if current_hash != payload.expected_content_hash:
                raise AppException(
                    status_code=409,
                    message="File has been modified since it was read. Reload before saving.",
                    details={
                        "path": relative_path,
                        "code": "FILE_MODIFIED_SINCE_READ",
                    },
                )
        else:
            if payload.expected_content_hash is not None:
                raise AppException(
                    status_code=409,
                    message="Target file does not exist. expected_content_hash must be null for new files.",
                    details={"path": relative_path, "code": "FILE_DOES_NOT_EXIST"},
                )

        tool_res = write_file(
            path=relative_path,
            content=payload.content,
            workspace_root=base_dir,
            raise_on_error=True,
        )
        data = tool_res.output or {}
        new_content_bytes = payload.content.encode("utf-8")
        new_hash = hashlib.sha256(new_content_bytes).hexdigest()

        return WorkspaceFileWriteResponse(
            workspace_id=workspace_id,
            path=data.get("path", relative_path),
            content_hash=new_hash,
            bytes_written=data.get("bytes_written", len(new_content_bytes)),
            is_new_file=data.get("is_new_file", False),
        )
    except ProtectedFileAccessViolationException as err:
        raise AppException(
            status_code=403,
            message=f"Access denied: path '{relative_path}' is protected.",
            details={"path": relative_path, "code": "PROTECTED_FILE"},
        ) from err
    except SecurityViolationException as err:
        raise AppException(
            status_code=400,
            message=f"Access denied: path '{relative_path}' is outside workspace boundary.",
            details={"path": relative_path, "code": "PATH_TRAVERSAL"},
        ) from err
    except FileSizeLimitExceededException as err:
        raise AppException(
            status_code=413,
            message=f"File content exceeds maximum allowed write size ({settings.MAX_WRITE_FILE_BYTES} bytes).",
            details={"path": relative_path, "code": "PAYLOAD_TOO_LARGE"},
        ) from err
    except ToolExecutionException as err:
        logger.error("Tool execution error writing '%s': %s", relative_path, err)
        raise AppException(
            status_code=400,
            message="Failed to write workspace file.",
            details={"path": relative_path, "code": "WRITE_ERROR"},
        ) from err
    except AppException:
        raise
    except Exception as err:
        logger.exception("Unhandled error writing file '%s': %s", relative_path, err)
        raise AppException(
            status_code=500,
            message="Failed to write workspace file.",
            details={"path": relative_path, "code": "INTERNAL_ERROR"},
        ) from err


@router.get(
    "/{workspace_id}/files/{file_path:path}",
    response_model=WorkspaceFileReadResponse,
    summary="Read a workspace file by relative path",
)
async def read_workspace_file_canonical(
    workspace_id: uuid.UUID,
    file_path: str,
    db: SessionDep,
) -> WorkspaceFileReadResponse:
    workspace = await WorkspaceService.get_workspace_by_id(db, workspace_id)
    return _execute_read_file(workspace.root_path, file_path, workspace.id)


@router.put(
    "/{workspace_id}/files/{file_path:path}",
    response_model=WorkspaceFileWriteResponse,
    summary="Write or save a workspace file with optimistic concurrency",
)
async def write_workspace_file_canonical(
    workspace_id: uuid.UUID,
    file_path: str,
    payload: WorkspaceFileWriteRequest,
    db: SessionDep,
) -> WorkspaceFileWriteResponse:
    workspace = await WorkspaceService.get_workspace_by_id(db, workspace_id)
    return _execute_write_file(workspace.root_path, file_path, payload, workspace.id)


@router.post(
    "/{workspace_id}/terminal/execute",
    response_model=TerminalExecuteResponse,
    summary="Execute an allowlisted command securely inside the workspace Docker sandbox",
)
async def execute_terminal_command(
    workspace_id: uuid.UUID,
    payload: TerminalExecuteRequest,
    db: SessionDep,
) -> TerminalExecuteResponse:
    """Executes a validated command inside an ephemeral Docker sandbox scoped to a registered workspace."""
    workspace = await WorkspaceService.get_workspace_by_id(db, workspace_id)
    base_dir = validate_workspace_dir(workspace.root_path)

    service = ExecutionService()
    try:
        result_dict = service.execute_in_sandbox(
            command=payload.command,
            workspace_path=base_dir,
            timeout_seconds=settings.COMMAND_TIMEOUT_SECONDS,
        )
        return TerminalExecuteResponse(
            workspace_id=workspace.id,
            command=result_dict["command"],
            exit_code=result_dict["exit_code"],
            stdout=result_dict["stdout"],
            stderr=result_dict["stderr"],
            truncated=result_dict["truncated"],
            duration_seconds=result_dict.get("duration_seconds"),
        )
    except (DisallowedCommandException, SecurityViolationException) as err:
        logger.warning(
            "Terminal command rejected by policy for workspace %s: %s",
            workspace_id,
            err,
        )
        raise AppException(
            status_code=400,
            message="Command rejected by execution policy.",
            details={"code": "COMMAND_DISALLOWED", "reason": str(err)},
        ) from err
    except ContainerTimeoutException as err:
        logger.warning("Terminal command timed out for workspace %s", workspace_id)
        raise AppException(
            status_code=408,
            message=f"Command execution timed out after {settings.COMMAND_TIMEOUT_SECONDS}s.",
            details={"code": "TIMEOUT"},
        ) from err
    except ContainerExecutionException as err:
        logger.error("Terminal Docker container error for workspace %s: %s", workspace_id, err)
        raise AppException(
            status_code=500,
            message="Terminal execution failed.",
            details={"code": "CONTAINER_ERROR"},
        ) from err
    except AppException:
        raise
    except Exception as err:
        logger.exception(
            "Unexpected error in terminal execution for workspace %s: %s",
            workspace_id,
            err,
        )
        raise AppException(
            status_code=500,
            message="Terminal execution failed.",
            details={"code": "INTERNAL_ERROR"},
        ) from err
