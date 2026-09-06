from typing import Any, TypedDict

from app.schemas.agent_contracts import (
    CoderOutput,
    DebuggerOutput,
    FinalizationResult,
    PlannerOutput,
    ReviewerOutput,
)

MAX_REPAIR_ITERATIONS = 3


class AgentState(TypedDict, total=False):
    """Explicitly typed workflow state for IrtrixAI LangGraph engine."""

    # 1. Persisted execution context
    task_id: str
    workspace_path: str
    thread_id: str
    messages: list[dict[str, Any]]
    workspace_summary: str | None
    tech_stack: list[str]
    current_step: int
    repair_count: int
    error: str | None
    final_result: FinalizationResult | None

    # 2. Model-generated proposals (Non-authoritative DTOs)
    plan: PlannerOutput | None
    coder_proposal: CoderOutput | None
    debugger_output: DebuggerOutput | None

    # 3. Tool results (Filesystem & execution facts)
    tool_result: dict[str, Any] | None
    pending_patch: str | None
    applied_diff: str | None
    test_command: str | None
    test_result: dict[str, Any] | None

    # 4. Human-in-the-loop governance
    approval: bool | None
    feedback: str | None
    review_summary: ReviewerOutput | None


def create_initial_state(
    task_id: str,
    workspace_path: str,
    thread_id: str,
    *,
    prompt: str | None = None,
) -> AgentState:
    """Creates a deterministic, clean initial agent state."""
    messages: list[dict[str, Any]] = []
    if prompt and prompt.strip():
        messages.append({"role": "user", "content": prompt.strip()})

    return AgentState(
        task_id=str(task_id).strip(),
        workspace_path=str(workspace_path).strip(),
        thread_id=str(thread_id).strip(),
        messages=messages,
        workspace_summary=None,
        tech_stack=[],
        current_step=0,
        repair_count=0,
        error=None,
        final_result=None,
        plan=None,
        coder_proposal=None,
        debugger_output=None,
        tool_result=None,
        pending_patch=None,
        applied_diff=None,
        test_command=None,
        test_result=None,
        approval=None,
        feedback=None,
        review_summary=None,
    )


def validate_state_invariants(state: AgentState) -> None:
    """Asserts runtime invariants: thread continuity, repair limits, and secret isolation."""
    thread_id = state.get("thread_id")
    if not thread_id or not str(thread_id).strip():
        raise ValueError("Graph invariant violated: thread_id must be non-empty.")

    repair_count = state.get("repair_count", 0)
    if repair_count < 0:
        raise ValueError("Graph invariant violated: repair_count cannot be negative.")
    if repair_count > MAX_REPAIR_ITERATIONS:
        raise ValueError(
            f"Graph invariant violated: repair_count ({repair_count}) "
            f"exceeds MAX_REPAIR_ITERATIONS ({MAX_REPAIR_ITERATIONS})."
        )

    # Invariant: No live network clients or API secrets stored directly in graph state
    for key, value in state.items():
        if "api_key" in key.lower() or "secret" in key.lower():
            raise ValueError(
                f"Security violation: Secret key '{key}' cannot be persisted in graph state."
            )
        # Verify no open network/database/client handles
        type_name = type(value).__name__.lower()
        if any(
            bad in type_name
            for bad in ("session", "client", "socket", "engine", "connection")
        ):
            raise TypeError(
                f"State serialization violation: Field '{key}' contains live handle '{type_name}'."
            )
