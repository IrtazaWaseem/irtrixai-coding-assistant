import json
import re
from enum import Enum
from typing import Any, TypeVar

from pydantic import BaseModel, Field, field_validator

T = TypeVar("T", bound=BaseModel)


class ReviewerVerdict(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


class FinalizationStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class PlannerOutput(BaseModel):
    summary: str = Field(
        ..., min_length=1, description="High-level architectural summary"
    )
    steps: list[str] = Field(
        ..., min_length=1, description="Concrete implementation sequence"
    )
    plan_id: str | None = Field(default=None, description="Optional plan identifier")
    files_expected: list[str] = Field(
        default_factory=list, description="Target workspace paths"
    )
    risk_notes: list[str] = Field(
        default_factory=list, description="Risk considerations"
    )
    risks_and_mitigations: list[str] = Field(
        default_factory=list, description="Edge cases and mitigations"
    )

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("summary cannot be empty or blank")
        return v

    @field_validator("steps")
    @classmethod
    def validate_steps(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("steps cannot be empty")
        for s in v:
            if not isinstance(s, str) or not s.strip():
                raise ValueError("steps cannot contain empty or blank items")
        return v


class CoderOutput(BaseModel):
    summary: str = Field(
        ..., min_length=1, description="Summary of proposed code mutations"
    )
    patch: str = Field(default="", description="Standard unified diff or patch block")
    files_changed: list[str] = Field(
        default_factory=list, description="List of workspace-relative paths"
    )

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("summary cannot be empty or blank")
        return v


class DebuggerOutput(BaseModel):
    diagnosis: str = Field(..., description="Root cause of test failure")
    proposed_fix: str = Field(..., description="Actionable fix direction for the Coder")
    files_to_change: list[str] = Field(
        default_factory=list, description="Files requiring repair"
    )
    reproduction_command: str | None = Field(
        default=None, description="Command to reproduce test failure"
    )


class ReviewerOutput(BaseModel):
    verdict: ReviewerVerdict = Field(..., description="Review outcome")
    summary: str = Field(..., description="Audit verdict justification")
    issues: list[str] = Field(default_factory=list, description="Defects found")
    security_concerns: list[str] = Field(
        default_factory=list, description="Security findings"
    )
    required_changes: list[str] = Field(
        default_factory=list, description="Mandatory remedies"
    )


class FinalizationResult(BaseModel):
    status: FinalizationStatus = Field(..., description="Workflow final state")
    summary: str = Field(..., description="Executive final outcome report")
    files_changed: list[str] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    review: ReviewerOutput | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def parse_structured_output(text: Any, schema: type[T]) -> T:
    """Parses JSON string, markdown codeblock, or dict into the requested Pydantic schema."""
    if isinstance(text, dict):
        return schema.model_validate(text)

    if not text or not str(text).strip():
        raise ValueError("Empty output cannot be parsed into structured schema.")

    cleaned = str(text).strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
    if match:
        cleaned = match.group(1).strip()

    try:
        data = json.loads(cleaned)
    except Exception as e:
        raise ValueError(f"Failed to parse JSON from model output: {e}") from e

    try:
        return schema.model_validate(data)
    except Exception as e:
        raise ValueError(f"Validation error for {schema.__name__}: {e}") from e


# Day 9 Context Layer Schemas
class RelevantFileContext(BaseModel):
    path: str = Field(..., description="Workspace-relative path of the relevant file")
    relevance_score: float = Field(
        default=0.0, description="Deterministic relevance score"
    )
    reason: str = Field(
        default="", description="Reason this file was determined relevant"
    )
    excerpt: str = Field(default="", description="Bounded text excerpt from the file")
    start_line: int = Field(default=1, description="1-based start line of the excerpt")
    end_line: int = Field(default=1, description="1-based end line of the excerpt")
    truncated: bool = Field(default=False, description="Whether excerpt was truncated")


class RepositoryContext(BaseModel):
    summary: str = Field(
        default="", description="Summary of repository context and relevance"
    )
    tech_stack: list[str] = Field(
        default_factory=list, description="Detected technology stack"
    )
    relevant_files: list[RelevantFileContext] = Field(
        default_factory=list, description="Ranked relevant files with excerpts"
    )
    total_files_considered: int = Field(
        default=0, description="Total workspace files evaluated"
    )
    files_included: int = Field(
        default=0, description="Count of relevant files included"
    )
    truncated: bool = Field(
        default=False,
        description="Whether total context limits caused truncation",
    )
    total_context_bytes: int = Field(
        default=0, description="Total byte size of all excerpts included"
    )


__all__ = [
    "FinalizationStatus",
    "ReviewerVerdict",
    "PlannerOutput",
    "CoderOutput",
    "DebuggerOutput",
    "ReviewerOutput",
    "FinalizationResult",
    "parse_structured_output",
    "RelevantFileContext",
    "RepositoryContext",
]
