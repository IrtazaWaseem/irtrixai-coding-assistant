from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FileTreeNode(BaseModel):
    name: str
    path: str
    type: str  # "file" | "directory"
    size: int | None = None
    children: list[FileTreeNode] | None = None


FileNodeSchema = FileTreeNode


class WorkspaceBase(BaseModel):
    name: str = Field(
        ..., min_length=1, max_length=128, description="Human-readable workspace label"
    )
    root_path: str = Field(
        ..., min_length=1, max_length=1024, description="Host filesystem root directory"
    )


class WorkspaceCreate(WorkspaceBase):
    pass


class WorkspaceRead(WorkspaceBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WorkspaceTreeResponse(BaseModel):
    workspace_id: uuid.UUID
    root_path: str
    tree: list[FileTreeNode] = Field(default_factory=list)
    total_entries: int = 0
    truncated: bool = False


class WorkspaceFileReadResponse(BaseModel):
    workspace_id: uuid.UUID
    path: str
    content: str
    content_hash: str
    size: int
    total_lines: int
    truncated: bool = False


class WorkspaceFileWriteRequest(BaseModel):
    content: str = Field(default="", description="Text content to write atomically")
    expected_content_hash: str | None = Field(
        default=None,
        description="Expected SHA-256 hash of existing file content. Must be None if creating a new file.",
    )


class WorkspaceFileWriteResponse(BaseModel):
    workspace_id: uuid.UUID
    path: str
    content_hash: str
    bytes_written: int
    is_new_file: bool


class TerminalExecuteRequest(BaseModel):
    command: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        description="Command to execute securely inside the Docker sandbox",
    )


class TerminalExecuteResponse(BaseModel):
    workspace_id: uuid.UUID
    command: str
    exit_code: int
    stdout: str
    stderr: str
    truncated: bool
    duration_seconds: float | None = None
