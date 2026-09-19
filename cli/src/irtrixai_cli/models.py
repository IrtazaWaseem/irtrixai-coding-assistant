from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SystemStatus:
    status: str
    version: str
    environment: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SystemStatus":
        return cls(
            status=str(data.get("status", "unknown")),
            version=str(data.get("version", "unknown")),
            environment=str(data.get("environment", "unknown")),
        )


@dataclass(slots=True)
class LLMInfo:
    provider: str
    model: str
    display_name: str
    fallback_provider: str | None = None
    capabilities: dict[str, bool] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LLMInfo":
        caps = data.get("capabilities", {})
        clean_caps = {str(k): bool(v) for k, v in caps.items()} if isinstance(caps, dict) else {}
        return cls(
            provider=str(data.get("provider", "unknown")),
            model=str(data.get("model", "unknown")),
            display_name=str(data.get("display_name", data.get("model", "unknown"))),
            fallback_provider=data.get("fallback_provider"),
            capabilities=clean_caps,
        )


@dataclass(slots=True)
class CombinedStatus:
    backend: SystemStatus | None = None
    llm: LLMInfo | None = None
    backend_error: str | None = None
    llm_error: str | None = None


@dataclass(slots=True)
class Workspace:
    id: str
    name: str
    root_path: str
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Workspace":
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            root_path=str(data.get("root_path", "")),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


@dataclass(slots=True)
class FileNode:
    name: str
    path: str
    type: str
    size: int | None = None
    children: list["FileNode"] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FileNode":
        raw_children = data.get("children")
        children = (
            [cls.from_dict(c) for c in raw_children] if isinstance(raw_children, list) else None
        )
        return cls(
            name=str(data.get("name", "")),
            path=str(data.get("path", "")),
            type=str(data.get("type", "file")),
            size=data.get("size"),
            children=children,
        )


@dataclass(slots=True)
class WorkspaceTree:
    workspace_id: str
    root_path: str
    max_depth: int
    total_entries: int
    truncated: bool
    tree: list[FileNode] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkspaceTree":
        raw_tree = data.get("tree", [])
        nodes = (
            [FileNode.from_dict(item) for item in raw_tree] if isinstance(raw_tree, list) else []
        )
        return cls(
            workspace_id=str(data.get("workspace_id", "")),
            root_path=str(data.get("root_path", "")),
            max_depth=int(data.get("max_depth", 3)),
            total_entries=int(data.get("total_entries", 0)),
            truncated=bool(data.get("truncated", False)),
            tree=nodes,
        )


@dataclass(slots=True)
class TaskResponse:
    id: str
    workspace_id: str
    status: str
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskResponse":
        return cls(
            id=str(data.get("id", "")),
            workspace_id=str(data.get("workspace_id", "")),
            status=str(data.get("status", "unknown")),
            error=data.get("error"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


@dataclass(slots=True)
class ExecutionResponse:
    task_id: str
    status: str
    current_step: int | None = None
    pending_patch: str | None = None
    coder_summary: str | None = None
    test_result: dict[str, Any] | None = None
    review_result: dict[str, Any] | None = None
    final_result: dict[str, Any] | None = None
    error: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionResponse":
        return cls(
            task_id=str(data.get("task_id", "")),
            status=str(data.get("status", "unknown")),
            current_step=data.get("current_step"),
            pending_patch=data.get("pending_patch"),
            coder_summary=data.get("coder_summary"),
            test_result=data.get("test_result"),
            review_result=data.get("review_result"),
            final_result=data.get("final_result"),
            error=data.get("error"),
        )


@dataclass(slots=True)
class CLIEvent:
    id: str
    timestamp: str
    type: str
    title: str
    description: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any], fallback_id: str = "") -> "CLIEvent":
        return cls(
            id=str(data.get("id") or fallback_id),
            timestamp=str(data.get("timestamp", "")),
            type=str(data.get("type", "event")),
            title=str(data.get("title", "")),
            description=str(data.get("description", "")),
            metadata=data.get("metadata", {}) if isinstance(data.get("metadata"), dict) else {},
        )
