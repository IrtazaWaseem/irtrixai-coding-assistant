from pathlib import Path

from app.core.exceptions import SecurityViolationException


def resolve_safe_path(base_directory: str | Path, target_path: str | Path) -> Path:
    """Resolves target_path strictly within base_directory.

    Prevents directory traversal (../), absolute escapes, and symlink escapes.
    Raises SecurityViolationException if the resolved path is outside base_directory.
    The exception message deliberately excludes the host's absolute base_directory
    to prevent filesystem topology disclosure.
    """
    base = Path(base_directory).resolve()
    target = Path(target_path)

    if target.is_absolute():
        resolved = target.resolve()
    else:
        resolved = (base / target).resolve()

    try:
        resolved.relative_to(base)
    except ValueError:
        raise SecurityViolationException(
            f"Access denied: path '{target_path}' escapes workspace boundary.",
            details={"path": str(target_path)},
        )

    return resolved
