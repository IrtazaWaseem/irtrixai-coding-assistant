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


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    llm_calls: int = 0
    by_provider: dict[str, Any] = Field(default_factory=dict)


class TaskAnalyticsResponse(BaseModel):
    tasks_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    llm_calls: int
    by_provider: dict[str, Any] = Field(default_factory=dict)


class TaskResponse(BaseModel):
    id: str
    workspace_id: str | None = None
    workspace_path: str
    prompt: str
    thread_id: str
    status: str
    provider: str | None = None
    model: str | None = None
    error: str | None = None
    token_usage: TokenUsage | None = None
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

        ws_id = None
        if getattr(task, "workspace_id", None):
            ws_id = str(task.workspace_id)
        elif getattr(task, "workspace", None) and hasattr(task.workspace, "id"):
            ws_id = str(task.workspace.id)

        t_id = getattr(task, "thread_id", "")
        if not t_id and getattr(task, "runs", None) and len(task.runs) > 0:
            t_id = task.runs[0].thread_id
        if not t_id:
            t_id = f"thread-{task.id}"

        st = task.status.value if hasattr(task.status, "value") else str(task.status)

        usage = None
        if getattr(task, "total_tokens", 0) > 0 or getattr(task, "llm_calls", 0) > 0:
            usage = TokenUsage(
                prompt_tokens=getattr(task, "prompt_tokens", 0),
                completion_tokens=getattr(task, "completion_tokens", 0),
                total_tokens=getattr(task, "total_tokens", 0),
                llm_calls=getattr(task, "llm_calls", 0),
                by_provider=getattr(task, "provider_usage", {}) or {},
            )

        return cls(
            id=str(task.id),
            workspace_id=ws_id,
            workspace_path=ws_path,
            prompt=task.prompt,
            thread_id=t_id,
            status=st,
            provider=getattr(task, "provider", None),
            model=getattr(task, "model", None),
            error=error,
            token_usage=usage,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )


class ExecutionResponse(BaseModel):
    task_id: str
    status: str
    current_step: int | None = None
    next_step: str | None = None
    token_usage: TokenUsage | None = None
    interrupt_payload: dict[str, Any] | None = None
    final_result: dict[str, Any] | None = None
    error: str | None = None


class ApprovalRequest(BaseModel):
    approved: bool
    feedback: str | None = Field(default=None, max_length=2000)
