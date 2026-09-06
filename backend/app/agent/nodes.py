import logging
from typing import Any

from langgraph.types import interrupt

from app.agent.state import MAX_REPAIR_ITERATIONS, AgentState
from app.schemas.agent_contracts import (
    CoderOutput,
    DebuggerOutput,
    FinalizationResult,
    PlannerOutput,
    ReviewerOutput,
)

logger = logging.getLogger(__name__)


async def inspect_workspace(state: AgentState) -> dict[str, Any]:
    """Inspects workspace topology, detects tech stack, and records initial summary."""
    workspace_path = state.get("workspace_path", "")
    logger.info("Node [inspect_workspace] analyzing '%s'", workspace_path)

    existing_summary = state.get("workspace_summary")
    existing_stack = state.get("tech_stack", [])

    return {
        "workspace_summary": existing_summary
        or f"[STUB] Workspace root at {workspace_path}",
        "tech_stack": existing_stack or ["python"],
        "current_step": 1,
    }


async def planner(state: AgentState) -> dict[str, Any]:
    """Generates execution plan based on workspace inspection and task prompt."""
    logger.info("Node [planner] building execution roadmap.")
    existing_plan = state.get("plan")
    if existing_plan is not None:
        return {"plan": existing_plan, "current_step": 2}

    default_plan = PlannerOutput(
        summary="[STUB] Analyze workspace and apply requested changes",
        steps=["Inspect target files", "Apply patch", "Run verification tests"],
        files_expected=[],
    )
    return {"plan": default_plan, "current_step": 2}


async def coder(state: AgentState) -> dict[str, Any]:
    """Proposes code modifications and produces unified patch for review."""
    logger.info("Node [coder] generating code patches.")
    existing_proposal = state.get("coder_proposal")
    feedback = state.get("feedback")

    # If already proposed and not in a rejection/feedback revision loop, reuse
    if existing_proposal is not None and state.get("approval") is not False:
        return {
            "coder_proposal": existing_proposal,
            "pending_patch": existing_proposal.patch,
            "current_step": 3,
        }

    summary = (
        f"[STUB] Implementation revised based on feedback: {feedback}"
        if feedback
        else "[STUB] Implementation changes proposed"
    )
    default_proposal = CoderOutput(
        summary=summary,
        requested_changes=["Update implementation"],
        patch="# [STUB] Proposed patch placeholder\n",
        files_changed=[],
    )
    updates: dict[str, Any] = {
        "coder_proposal": default_proposal,
        "pending_patch": default_proposal.patch,
        "current_step": 3,
    }
    # A revised proposal requires fresh human approval
    if state.get("approval") is False:
        updates["approval"] = None

    return updates


async def approval_gate(state: AgentState) -> dict[str, Any]:
    """Enforces human-in-the-loop verification before changes are applied or executed."""
    logger.info("Node [approval_gate] validating human approval status.")

    approval = state.get("approval")
    feedback = state.get("feedback")

    # If approval has not been resolved yet, interrupt graph execution for human decision
    if approval is None:
        interruption_payload = {
            "action": "human_approval_required",
            "pending_patch": state.get("pending_patch"),
            "coder_summary": (
                state["coder_proposal"].summary if state.get("coder_proposal") else None
            ),
        }
        res = interrupt(interruption_payload)

        # When resumed via Command(resume=...), process the human operator response
        if isinstance(res, dict):
            approval = bool(res.get("approved", False))
            feedback = res.get("feedback")
        elif isinstance(res, bool):
            approval = res
        else:
            approval = False

    return {
        "approval": approval,
        "feedback": feedback,
        "current_step": 4,
    }


async def test_runner(state: AgentState) -> dict[str, Any]:
    """Runs verification tests against proposed changes inside the secure sandbox."""
    logger.info("Node [test_runner] executing test verification.")
    existing_result = state.get("test_result")
    if existing_result is not None:
        return {"test_result": existing_result, "current_step": 5}

    default_result = {
        "success": True,
        "exit_code": 0,
        "output": "[STUB] Skeleton test execution placeholder - unverified",
        "is_stub": True,
    }
    return {
        "test_command": state.get("test_command") or "pytest",
        "test_result": default_result,
        "current_step": 5,
    }


async def debugger(state: AgentState) -> dict[str, Any]:
    """Diagnoses test failures, proposes fixes, and increments the repair counter."""
    current_repairs = state.get("repair_count", 0) + 1
    if current_repairs > MAX_REPAIR_ITERATIONS:
        logger.error(
            "Node [debugger] invoked beyond MAX_REPAIR_ITERATIONS (%d > %d).",
            current_repairs,
            MAX_REPAIR_ITERATIONS,
        )
        current_repairs = MAX_REPAIR_ITERATIONS

    logger.warning(
        "Node [debugger] diagnosing failure (repair cycle %d).", current_repairs
    )

    diagnostic = DebuggerOutput(
        diagnosis="[STUB] Test verification failed; diagnosing root cause",
        proposed_fix="[STUB] Adjust implementation to address test assertion",
        files_to_change=[],
    )

    return {
        "debugger_output": diagnostic,
        "repair_count": current_repairs,
        "current_step": 6,
    }


async def reviewer(state: AgentState) -> dict[str, Any]:
    """Performs final code quality and architectural review."""
    logger.info("Node [reviewer] auditing completed implementation.")
    existing_review = state.get("review_summary")
    if existing_review is not None:
        return {"review_summary": existing_review, "current_step": 7}

    review = ReviewerOutput(
        verdict="approved",
        summary="[STUB] Skeleton review placeholder - pending model verification in Part 2",
        issues=[],
        security_concerns=[],
        required_changes=[],
    )
    return {
        "review_summary": review,
        "current_step": 7,
    }


async def finalize(state: AgentState) -> dict[str, Any]:
    """Synthesizes workflow outcome into authoritative FinalizationResult."""
    logger.info("Node [finalize] concluding execution.")

    test_res = state.get("test_result") or {}
    test_passed = test_res.get("success", False)
    approval = state.get("approval")

    if approval is False:
        status = "aborted"
        summary = (
            f"Workflow aborted by human operator: {state.get('feedback', 'Rejected')}"
        )
    elif test_passed:
        is_stub = test_res.get("is_stub", False)
        status = "completed"
        if is_stub:
            summary = "[STUB] Skeleton workflow completed with placeholder execution"
        else:
            summary = "Task completed successfully and all tests verified"
    else:
        status = "failed"
        summary = f"Task failed after {state.get('repair_count', 0)} repair attempts."

    executed_tests: list[str] = []
    if state.get("test_command"):
        executed_tests.append(str(state["test_command"]))

    final = FinalizationResult(
        status=status,
        summary=summary,
        files_changed=(
            state["coder_proposal"].files_changed if state.get("coder_proposal") else []
        ),
        tests=executed_tests,
        review=state.get("review_summary"),
    )

    return {
        "final_result": final,
        "current_step": 8,
    }
