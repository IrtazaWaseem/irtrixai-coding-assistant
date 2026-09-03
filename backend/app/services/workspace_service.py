import contextlib
import os
import uuid
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, EntityNotFoundException
from app.core.security import resolve_safe_path
from app.db.models import Workspace
from app.schemas.workspace import FileTreeNode, WorkspaceCreate

IGNORED_DIRECTORIES = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".idea",
    ".vscode",
    ".next",
    "target",
}

IGNORED_FILES = {
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
}


class WorkspaceService:
    @staticmethod
    async def create_workspace(db: AsyncSession, payload: WorkspaceCreate) -> Workspace:
        """Validates path and registers workspace metadata in PostgreSQL.

        Source code is never duplicated into the database.
        """
        raw_path = Path(payload.root_path)

        if not raw_path.exists():
            raise AppException(
                message=f"Directory '{payload.root_path}' does not exist on host.",
                status_code=400,
                details={"root_path": payload.root_path},
            )

        if not raw_path.is_dir():
            raise AppException(
                message=f"Path '{payload.root_path}' is not a directory.",
                status_code=400,
                details={"root_path": payload.root_path},
            )

        resolved_root = str(raw_path.resolve())

        stmt = select(Workspace).where(Workspace.root_path == resolved_root)
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing:
            raise AppException(
                message=f"Workspace with root path '{resolved_root}' is already registered.",
                status_code=409,
                details={"workspace_id": str(existing.id)},
            )

        workspace = Workspace(
            name=payload.name.strip(),
            root_path=resolved_root,
        )
        db.add(workspace)
        await db.commit()
        await db.refresh(workspace)
        return workspace

    @staticmethod
    async def get_all_workspaces(db: AsyncSession) -> Sequence[Workspace]:
        stmt = select(Workspace).order_by(Workspace.created_at.desc())
        result = await db.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def get_workspace_by_id(db: AsyncSession, workspace_id: uuid.UUID) -> Workspace:
        stmt = select(Workspace).where(Workspace.id == workspace_id)
        workspace = (await db.execute(stmt)).scalar_one_or_none()
        if not workspace:
            raise EntityNotFoundException("Workspace", str(workspace_id))
        return workspace

    @staticmethod
    def build_file_tree(
        root_path: str | Path,
        max_depth: int = 3,
        max_entries: int = 1000,
    ) -> tuple[list[FileTreeNode], int, bool]:
        """Scans workspace directory recursively up to max_depth and max_entries."""
        base_dir = Path(root_path).resolve()
        if not base_dir.exists() or not base_dir.is_dir():
            raise AppException(
                message=f"Workspace filesystem directory '{root_path}' is inaccessible.",
                status_code=404,
            )

        entry_count = 0
        truncated = False

        def _scan(current_dir: Path, current_depth: int) -> list[FileTreeNode]:
            nonlocal entry_count, truncated
            if current_depth > max_depth or entry_count >= max_entries:
                if entry_count >= max_entries:
                    truncated = True
                return []

            nodes: list[FileTreeNode] = []

            try:
                entries = sorted(
                    os.scandir(current_dir),
                    key=lambda e: (not e.is_dir(), e.name.lower()),
                )
            except PermissionError:
                return nodes

            for entry in entries:
                if entry_count >= max_entries:
                    truncated = True
                    break

                if entry.name in IGNORED_DIRECTORIES or entry.name in IGNORED_FILES:
                    continue

                safe_child = resolve_safe_path(base_dir, entry.path)
                rel_path = str(safe_child.relative_to(base_dir)).replace("\\", "/")

                if entry.is_dir(follow_symlinks=False):
                    entry_count += 1
                    children = _scan(safe_child, current_depth + 1)
                    nodes.append(
                        FileTreeNode(
                            name=entry.name,
                            path=rel_path,
                            type="directory",
                            children=children,
                        )
                    )
                elif entry.is_file(follow_symlinks=False):
                    entry_count += 1
                    file_size = None
                    with contextlib.suppress(OSError):
                        file_size = entry.stat().st_size

                    nodes.append(
                        FileTreeNode(
                            name=entry.name,
                            path=rel_path,
                            type="file",
                            size=file_size,
                        )
                    )

            return nodes

        tree = _scan(base_dir, current_depth=1)
        return tree, entry_count, truncated
