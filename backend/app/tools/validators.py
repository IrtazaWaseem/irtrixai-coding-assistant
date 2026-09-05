import contextvars
from pathlib import Path

from app.core.config import settings
from app.core.constants import is_protected_file
from app.core.exceptions import (
    AppException,
    EntityNotFoundException,
    FileSizeLimitExceededException,
    ProtectedFileAccessViolationException,
    ToolExecutionException,
)
from app.core.security import (
    resolve_safe_path,
    truncate_output,
    validate_command,
)

_current_workspace_root: contextvars.ContextVar[Path | None] = contextvars.ContextVar(
    "current_workspace_root", default=None
)


def set_current_workspace(root: str | Path | None) -> None:
    """Sets the active workspace root for the current execution context."""
    _current_workspace_root.set(Path(root).resolve() if root else None)


def get_current_workspace() -> Path | None:
    """Returns the active workspace root for the current execution context."""
    return _current_workspace_root.get()


def validate_workspace_dir(workspace_root: str | Path | None = None) -> Path:
    """Verifies that the workspace root exists, is a directory, and resolves safely."""
    if workspace_root is None:
        ctx_root = get_current_workspace()
        workspace_root = ctx_root if ctx_root is not None else settings.WORKSPACE_BASE_PATH

    root = Path(workspace_root).resolve()
    if not root.exists():
        raise AppException(
            "Workspace directory does not exist.",
            status_code=404,
            details={"workspace_root": str(workspace_root)},
        )
    if not root.is_dir():
        raise AppException(
            "Workspace path is not a directory.",
            status_code=400,
            details={"workspace_root": str(workspace_root)},
        )
    return root


def validate_safe_path(
    workspace_root: str | Path,
    target_path: str | Path,
    must_exist: bool = False,
) -> Path:
    """Validates that target_path resolves strictly within workspace_root."""
    root = validate_workspace_dir(workspace_root)
    safe_path = resolve_safe_path(root, target_path)

    if must_exist and not safe_path.exists():
        raise EntityNotFoundException("File", str(target_path))

    return safe_path


def validate_not_protected(
    target_path: str | Path,
    resolved_path: Path | None = None,
) -> None:
    """Ensures neither the requested path nor the resolved file is protected."""
    if is_protected_file(target_path):
        raise ProtectedFileAccessViolationException(str(target_path))
    if resolved_path is not None and is_protected_file(resolved_path):
        raise ProtectedFileAccessViolationException(str(target_path))


def validate_file_size(
    file_path: Path,
    max_bytes: int | None = None,
) -> int:
    """Ensures target file is a regular file and does not exceed maximum byte size."""
    if max_bytes is None:
        max_bytes = settings.MAX_READ_FILE_BYTES

    if not file_path.is_file():
        raise AppException(
            f"Path '{file_path.name}' is not a regular file.",
            status_code=400,
            details={"path": file_path.name},
        )
    try:
        size = file_path.stat().st_size
    except OSError as err:
        raise AppException(
            f"Failed to access file metadata for '{file_path.name}': {err}",
            status_code=400,
        ) from err

    if size > max_bytes:
        raise FileSizeLimitExceededException(
            f"File size ({size} bytes) exceeds limit of {max_bytes} bytes.",
            details={"size": size, "max_bytes": max_bytes, "file_path": file_path.name},
        )
    return size


def validate_content_size(
    content: str | bytes,
    max_bytes: int,
    field_name: str = "content",
) -> int:
    """Ensures input payload size does not exceed specified limit."""
    byte_length = len(content.encode("utf-8")) if isinstance(content, str) else len(content)
    if byte_length > max_bytes:
        raise FileSizeLimitExceededException(
            f"Payload for '{field_name}' ({byte_length} bytes) exceeds limit of {max_bytes} bytes.",
            details={"byte_length": byte_length, "max_bytes": max_bytes, "field": field_name},
        )
    return byte_length


def validate_allowed_operation(operation: str, allowed: set[str] | list[str]) -> str:
    """Enforces allowlisted operations."""
    allowed_set = set(allowed)
    if operation not in allowed_set:
        raise ToolExecutionException(
            f"Operation '{operation}' is not allowed. Supported: {sorted(allowed_set)}",
            details={"operation": operation, "allowed": sorted(allowed_set)},
        )
    return operation


__all__ = [
    "get_current_workspace",
    "set_current_workspace",
    "truncate_output",
    "validate_allowed_operation",
    "validate_command",
    "validate_content_size",
    "validate_file_size",
    "validate_not_protected",
    "validate_safe_path",
    "validate_workspace_dir",
]
