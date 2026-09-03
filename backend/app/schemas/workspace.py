import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceBase(BaseModel):
    name: str = Field(
        ..., min_length=1, max_length=255, description="Human-readable workspace label"
    )
    root_path: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        description="Absolute filesystem directory path",
    )


class WorkspaceCreate(WorkspaceBase):
    pass


class WorkspaceRead(WorkspaceBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FileTreeNode(BaseModel):
    name: str
    path: str  # Normalized relative path from workspace root (using forward slashes)
    type: Literal["file", "directory"]
    size: int | None = None
    children: list["FileTreeNode"] | None = None


class WorkspaceTreeResponse(BaseModel):
    workspace_id: uuid.UUID
    root_path: str
    tree: list[FileTreeNode]
    total_entries: int
    truncated: bool
