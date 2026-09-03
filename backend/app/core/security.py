from pathlib import Path

from app.core.exceptions import SecurityViolationException


def resolve_safe_path(base_dir: str | Path, target_path: str | Path = ".") -> Path:
    """Resolves target_path strictly within base_dir.

    Prevents directory traversal (../), absolute path hijacking,
    and symlink escapes.
    """
    base = Path(base_dir).resolve()
    target = Path(target_path)

    # In Python, Path('/a') / '/b' resolves to Path('/b').
    # Use ternary operator to handle absolute and relative inputs cleanly.
    resolved_target = target.resolve() if target.is_absolute() else (base / target).resolve()

    try:
        if not resolved_target.is_relative_to(base):
            raise SecurityViolationException(
                f"Access denied: path '{target_path}' escapes workspace root '{base}'"
            )
    except (ValueError, RuntimeError) as err:
        raise SecurityViolationException(
            f"Access denied: invalid path traversal detected for '{target_path}'"
        ) from err

    return resolved_target
