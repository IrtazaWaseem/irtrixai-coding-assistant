"""Central constants shared across application layers."""

import fnmatch
from pathlib import Path

IGNORED_DIRECTORIES: set[str] = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    ".venv",
    "venv",
    "env",
    ".idea",
    ".vscode",
    ".next",
    "target",
    "dist",
    "build",
}

IGNORED_FILES: set[str] = {
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    ".env",
}

PROTECTED_FILES: set[str] = {
    ".env",
}

PROTECTED_PATTERNS: set[str] = {
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "id_rsa",
    "id_ed25519",
}

ALLOWLISTED_EXECUTABLES: set[str] = {
    "python",
    "python3",
    "pytest",
    "ruff",
}

FORBIDDEN_COMMAND_TOKENS: set[str] = {
    "|",
    ";",
    "&",
    "&&",
    "||",
    "`",
    "$",
    "<",
    ">",
    ">>",
    "2>",
}


def is_protected_file(path: str | Path) -> bool:
    """Checks whether a file path or filename matches protected secret policies."""
    filename = Path(path).name
    if filename in PROTECTED_FILES:
        return True
    return any(fnmatch.fnmatch(filename, pattern) for pattern in PROTECTED_PATTERNS)
