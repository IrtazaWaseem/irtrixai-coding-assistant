import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FileTreeNode(BaseModel):
    name: str
    path: str
    type: str  # "file" | "directory"
    size: int | None = None
    children: list["FileTreeNode"] | None = None


# Backward-compatible alias
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
    size: int
    total_lines: int
    truncated: bool = False


class WorkspaceFileWriteRequest(BaseModel):
    content: str = Field(default="", description="Text content to write atomically")


class WorkspaceFileWriteResponse(BaseModel):
    workspace_id: uuid.UUID
    path: str
    bytes_written: int
    is_new_file: bool
