import shlex
from pathlib import Path

from app.core.config import settings
from app.core.constants import ALLOWLISTED_EXECUTABLES, FORBIDDEN_COMMAND_TOKENS
from app.core.exceptions import DisallowedCommandException, SecurityViolationException


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


def truncate_output(
    content: str,
    max_bytes: int | None = None,
) -> tuple[str, bool]:
    """Truncates string content cleanly if UTF-8 representation exceeds max_bytes."""
    if max_bytes is None:
        max_bytes = settings.MAX_TOOL_OUTPUT_BYTES

    encoded = content.encode("utf-8")
    if len(encoded) <= max_bytes:
        return content, False

    truncated_str = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return truncated_str, True


def _has_unquoted_shell_operators(command_str: str) -> tuple[bool, str]:
    """Scans command string for shell chaining/redirection operators outside quotes."""
    in_single = False
    in_double = False
    escape = False

    for char in command_str:
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if not in_single and not in_double and char in FORBIDDEN_COMMAND_TOKENS:
            return True, char

    return False, ""


def validate_command(command: str | list[str]) -> list[str]:
    """Validates and parses a command string or token list into deterministic argv tokens.

    Enforces:
    1. Command is non-empty.
    2. No unquoted shell chaining or redirection operators (; & | < > ` $).
    3. argv[0] must be a bare name without path separators (/ or \\).
    4. argv[0] must exactly match an entry in ALLOWLISTED_EXECUTABLES.
    5. Tokens do not contain forbidden shell control operators.
    """
    if isinstance(command, str):
        if not command or not command.strip():
            raise DisallowedCommandException("Command string cannot be empty.")

        has_op, op_char = _has_unquoted_shell_operators(command)
        if has_op:
            raise DisallowedCommandException(
                f"Shell control operator '{op_char}' is forbidden outside quoted arguments."
            )

        try:
            tokens = shlex.split(command.strip(), posix=True)
        except ValueError as err:
            raise DisallowedCommandException(f"Failed to parse command syntax: {err}") from err
    elif isinstance(command, (list, tuple)):
        if not command:
            raise DisallowedCommandException("Command list cannot be empty.")
        tokens = [str(token) for token in command]
        if not any(token.strip() for token in tokens):
            raise DisallowedCommandException("Command list cannot be empty.")
    else:
        raise DisallowedCommandException("Command must be a string or a list of arguments.")

    if not tokens:
        raise DisallowedCommandException("Command contained no executable tokens.")

    executable = tokens[0]

    if "/" in executable or "\\" in executable:
        raise DisallowedCommandException(
            f"Executable path '{executable}' is forbidden. Only bare allowlisted names are accepted."
        )

    if executable not in ALLOWLISTED_EXECUTABLES:
        raise DisallowedCommandException(
            f"Executable '{executable}' is not allowlisted. Supported: {sorted(ALLOWLISTED_EXECUTABLES)}"
        )

    for token in tokens:
        if token in FORBIDDEN_COMMAND_TOKENS:
            raise DisallowedCommandException(f"Shell control token '{token}' is forbidden.")

    return tokens
