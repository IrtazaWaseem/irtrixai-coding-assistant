import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TaskCreate(BaseModel):
    workspace_id: uuid.UUID | str | None = Field(
        default=None, description="UUID of registered workspace"
    )
    workspace_path: str | None = Field(
        default=None,
        min_length=1,
        max_length=1024,
        description="Filesystem path to task workspace (legacy fallback)",
    )
    provider: str | None = Field(
        default=None, description="LLM provider: 'gemini', 'groq', or 'ollama'"
    )
    model: str | None = Field(
        default=None, description="Model identifier for the selected provider"
    )
    prompt: str = Field(..., min_length=1, max_length=10000, description="Task instructions/prompt")

    @model_validator(mode="after")
    def check_workspace_identifier(self) -> "TaskCreate":
        if not self.workspace_id and not self.workspace_path:
            raise ValueError("Either 'workspace_id' or 'workspace_path' must be provided.")
        return self


class TaskResponse(BaseModel):
    id: str
    workspace_path: str
    prompt: str
    thread_id: str
    status: str
    provider: str | None = None
    model: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_task(cls, task: Any) -> "TaskResponse":
        error = None
        if hasattr(task, "runs") and task.runs and len(task.runs) > 0:
            error = task.runs[-1].error_message
        elif hasattr(task, "error"):
            error = task.error

        ws_path = getattr(task, "workspace_path", "")
        if not ws_path and getattr(task, "workspace", None):
            ws_path = getattr(task.workspace, "root_path", "")

        t_id = getattr(task, "thread_id", "")
        if not t_id and getattr(task, "runs", None) and len(task.runs) > 0:
            t_id = task.runs[0].thread_id
        if not t_id:
            t_id = f"thread-{task.id}"

        st = task.status.value if hasattr(task.status, "value") else str(task.status)

        return cls(
            id=str(task.id),
            workspace_path=ws_path,
            prompt=task.prompt,
            thread_id=t_id,
            status=st,
            provider=getattr(task, "provider", None),
            model=getattr(task, "model", None),
            error=error,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )


class ApprovalRequest(BaseModel):
    approved: bool
    feedback: str | None = Field(default=None, max_length=2000)


class ExecutionResponse(BaseModel):
    task_id: str
    status: str
    current_step: int | None = None
    next_step: str | None = None
    interrupt_payload: dict[str, Any] | None = None
    final_result: dict[str, Any] | None = None
    error: str | None = None
