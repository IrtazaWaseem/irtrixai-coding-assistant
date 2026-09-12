from pathlib import Path
from typing import Any, TypedDict

from app.schemas.agent_contracts import (
    CoderOutput,
    DebuggerOutput,
    FinalizationResult,
    PlannerOutput,
    ReviewerOutput,
)

MAX_REPAIR_ITERATIONS = 3

SENSITIVE_KEY_TERMS = (
    "api_key",
    "secret",
    "token",
    "password",
    "credential",
    "private_key",
)


class AgentState(TypedDict):
    task_id: str
    workspace_path: str
    thread_id: str
    messages: list[dict[str, Any]]
    workspace_summary: str | None
    tech_stack: list[str]
    repository_context: dict[str, Any] | None  # Day 9 Context Layer
    plan: PlannerOutput | dict[str, Any] | None
    coder_proposal: CoderOutput | dict[str, Any] | None
    pending_patch: str | None
    approval: bool | None
    feedback: str | None
    applied_diff: str | None
    test_command: str | None
    test_result: dict[str, Any] | None
    tool_result: dict[str, Any] | None
    debugger_output: DebuggerOutput | dict[str, Any] | None
    repair_count: int
    review_summary: ReviewerOutput | dict[str, Any] | None
    final_result: FinalizationResult | dict[str, Any] | None
    error: str | None
    current_step: int


def create_initial_state(
    task_id: str,
    workspace_path: str,
    thread_id: str,
    prompt: str = "",
) -> AgentState:
    return {
        "task_id": task_id,
        "workspace_path": workspace_path,
        "thread_id": thread_id,
        "messages": [{"role": "user", "content": prompt}] if prompt else [],
        "workspace_summary": None,
        "tech_stack": [],
        "repository_context": None,  # Day 9 Context Layer
        "plan": None,
        "coder_proposal": None,
        "pending_patch": None,
        "approval": None,
        "feedback": None,
        "applied_diff": None,
        "test_command": None,
        "test_result": None,
        "tool_result": None,
        "debugger_output": None,
        "repair_count": 0,
        "review_summary": None,
        "final_result": None,
        "error": None,
        "current_step": 0,
    }


def validate_state_invariants(state: AgentState | dict[str, Any]) -> bool:
    """Validates critical security, graph, and thread state invariants."""
    if not isinstance(state, dict):
        raise ValueError("State must be a dictionary or Mapping.")

    # 1. Thread Invariants
    thread_id = state.get("thread_id")
    if not thread_id or not isinstance(thread_id, str) or not thread_id.strip():
        raise ValueError("thread_id must be non-empty.")

    # 2. Task & Workspace Identity Invariants
    task_id = state.get("task_id")
    if not task_id or not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task_id must be non-empty.")

    workspace_path = state.get("workspace_path")
    if (
        not workspace_path
        or not isinstance(workspace_path, str)
        or not workspace_path.strip()
    ):
        raise ValueError("workspace_path must be non-empty.")

    # Security: Workspace boundary & traversal protection
    norm_ws = str(workspace_path).replace("\\", "/")
    if (
        ".." in Path(workspace_path).parts
        or "/../" in norm_ws
        or norm_ws.startswith("../")
        or norm_ws == ".."
    ):
        raise ValueError(
            "Security invariant violated: workspace_path contains path traversal ('..')."
        )

    # Security: Secret & credential leak protection
    for k, v in state.items():
        k_lower = str(k).lower()
        if any(term in k_lower for term in SENSITIVE_KEY_TERMS):
            raise ValueError(f"Security violation: state contains sensitive key '{k}'.")
        if isinstance(v, str) and any(
            term in v.lower() for term in ("aizasy", "bearer ")
        ):
            raise ValueError(
                f"Security violation: state contains sensitive secret in '{k}'."
            )

    # 3. Repair Count Governance (0 <= repair_count <= MAX_REPAIR_ITERATIONS)
    repair_count = state.get("repair_count", 0)
    if not isinstance(repair_count, int) or isinstance(repair_count, bool):
        raise ValueError("repair_count must be an integer.")
    if repair_count < 0:
        raise ValueError("repair_count cannot be negative.")
    if repair_count > MAX_REPAIR_ITERATIONS:
        raise ValueError(
            f"repair_count ({repair_count}) exceeds MAX_REPAIR_ITERATIONS ({MAX_REPAIR_ITERATIONS})."
        )

    # 4. Security & Patch Authorization Invariant
    applied_diff = state.get("applied_diff")
    approval = state.get("approval")
    if applied_diff and approval is not True:
        raise ValueError(
            "Security invariant violated: applied_diff cannot exist without explicit human approval (approval=True)."
        )

    if approval is not None and not isinstance(approval, bool):
        raise ValueError("approval must be a boolean or None.")

    # 5. Step boundary invariant
    current_step = state.get("current_step", 0)
    if (
        current_step is not None
        and not isinstance(current_step, int)
        or isinstance(current_step, bool)
    ):
        raise ValueError("current_step must be an integer.")
    if current_step is not None and (current_step < 0 or current_step > 8):
        raise ValueError("current_step must be between 0 and 8.")

    return True


__all__ = [
    "MAX_REPAIR_ITERATIONS",
    "AgentState",
    "create_initial_state",
    "validate_state_invariants",
]
