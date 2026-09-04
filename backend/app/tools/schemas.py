from pydantic import BaseModel, Field


# --- Filesystem Schemas ---
class FileEntry(BaseModel):
    name: str
    path: str
    type: str  # "file" | "directory"
    size: int | None = None


class ListFilesOutput(BaseModel):
    entries: list[FileEntry]
    total_entries: int
    truncated: bool


class ReadFileOutput(BaseModel):
    path: str
    content: str
    start_line: int
    end_line: int
    total_lines: int
    truncated: bool
    has_more: bool


class SearchMatch(BaseModel):
    file_path: str
    line_number: int
    line_content: str


class SearchCodeOutput(BaseModel):
    query: str
    matches: list[SearchMatch]
    total_matches: int
    truncated: bool


class WriteFileOutput(BaseModel):
    path: str
    bytes_written: int
    is_new_file: bool


class ApplyPatchOutput(BaseModel):
    path: str
    hunks_applied: int
    bytes_written: int
    applied: bool


# --- Git Schemas ---
class GitStagedItem(BaseModel):
    path: str
    status: str


class GitStatusOutput(BaseModel):
    branch: str
    is_clean: bool
    modified: list[str] = Field(default_factory=list)
    untracked: list[str] = Field(default_factory=list)
    deleted: list[str] = Field(default_factory=list)
    staged: list[GitStagedItem] = Field(default_factory=list)
