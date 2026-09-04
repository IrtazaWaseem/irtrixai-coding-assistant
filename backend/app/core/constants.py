"""Central constants shared across application layers."""

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
