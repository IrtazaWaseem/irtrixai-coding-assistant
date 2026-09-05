from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PlannerOutput(BaseModel):
    """Contract for planner agent output."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    summary: str = Field(
        ..., description="High-level reasoning summary and plan objective"
    )
    steps: list[str] = Field(..., description="Ordered step-by-step execution plan")
    plan_id: str | None = Field(default=None, description="Optional plan identifier")
    files_expected: list[str] = Field(
        default_factory=list,
        description="Files anticipated to be read or modified",
    )
    risk_notes: list[str] = Field(
        default_factory=list,
        description="Potential risks, edge cases, or side effects",
    )

    @field_validator("summary", mode="after")
    @classmethod
    def validate_summary(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Planner summary cannot be empty or whitespace.")
        return v.strip()

    @field_validator("steps", mode="after")
    @classmethod
    def validate_steps(cls, v: list[str]) -> list[str]:
        cleaned = [s.strip() for s in v if s and s.strip()]
        if not cleaned:
            raise ValueError("Planner steps must contain at least one non-empty step.")
        return cleaned


class CoderOutput(BaseModel):
    """Contract for coder agent output."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    summary: str = Field(..., description="Summary of implementation changes performed")
    requested_changes: list[str] = Field(
        default_factory=list,
        description="Detailed itemized changes made or requested",
    )
    patch: str | None = Field(
        default=None, description="Proposed unified diff patch or change content"
    )
    files_changed: list[str] = Field(
        default_factory=list,
        description="List of workspace-relative files touched or modified",
    )

    @field_validator("summary", mode="after")
    @classmethod
    def validate_summary(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Coder summary cannot be empty or whitespace.")
        return v.strip()


class DebuggerOutput(BaseModel):
    """Contract for debugger agent output."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    diagnosis: str = Field(
        ..., description="Root-cause diagnosis of failure, test, or runtime defect"
    )
    proposed_fix: str = Field(
        ..., description="Detailed explanation of proposed remediation"
    )
    files_to_change: list[str] = Field(
        default_factory=list,
        description="Target files identified as requiring modification",
    )
    reproduction_command: str | None = Field(
        default=None,
        description="Optional command to reproduce the defect or verify the fix",
    )

    @field_validator("diagnosis", "proposed_fix", mode="after")
    @classmethod
    def validate_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError(
                "Diagnosis and proposed_fix cannot be empty or whitespace."
            )
        return v.strip()


ReviewerVerdict = Literal["approved", "changes_requested", "rejected"]


class ReviewerOutput(BaseModel):
    """Contract for reviewer agent output."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    verdict: ReviewerVerdict = Field(
        ...,
        description="Review outcome: 'approved', 'changes_requested', or 'rejected'",
    )
    summary: str = Field(..., description="Evaluation summary of the implementation")
    issues: list[str] = Field(
        default_factory=list,
        description="Functional, architectural, or performance defects identified",
    )
    security_concerns: list[str] = Field(
        default_factory=list,
        description="Security concerns or policy violations identified",
    )
    required_changes: list[str] = Field(
        default_factory=list,
        description="Mandatory changes required prior to approval",
    )

    @field_validator("summary", mode="after")
    @classmethod
    def validate_summary(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Reviewer summary cannot be empty or whitespace.")
        return v.strip()


FinalizationStatus = Literal["completed", "failed", "aborted"]


class FinalizationResult(BaseModel):
    """Contract for agent workflow completion output."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    status: FinalizationStatus = Field(
        ...,
        description="Final execution status: 'completed', 'failed', or 'aborted'",
    )
    summary: str = Field(..., description="Comprehensive summary of task outcome")
    files_changed: list[str] = Field(
        default_factory=list,
        description="Consolidated list of modified files",
    )
    tests: list[str] = Field(
        default_factory=list,
        description="List of test commands or verification suites executed",
    )
    review: ReviewerOutput | None = Field(
        default=None, description="Final review audit if conducted"
    )

    @field_validator("summary", mode="after")
    @classmethod
    def validate_summary(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Finalization summary cannot be empty or whitespace.")
        return v.strip()
