import logging

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.agent.checkpoint import checkpointer_manager
from app.agent.nodes import (
    apply_approved_patch,
    approval_gate,
    coder,
    debugger,
    finalize,
    inspect_workspace,
    planner,
    repository_context,  # Day 9 Node
    reviewer,
    test_runner,
)
from app.agent.state import MAX_REPAIR_ITERATIONS, AgentState

logger = logging.getLogger(__name__)


def route_after_approval(state: AgentState) -> str:
    approval = state.get("approval")
    feedback = state.get("feedback")

    if approval is True:
        if state.get("pending_patch"):
            return "apply_approved_patch"
        return "test_runner"
    elif approval is False:
        if feedback and str(feedback).strip():
            return "coder"
        return "finalize"
    return "finalize"


def route_after_test(state: AgentState) -> str:
    test_res = state.get("test_result")
    test_passed = isinstance(test_res, dict) and test_res.get("success") is True

    if test_passed:
        return "reviewer"

    repair_count = state.get("repair_count", 0)
    if repair_count >= MAX_REPAIR_ITERATIONS:
        logger.warning(
            "Max repair iterations reached (%d). Exiting loop to finalize.",
            repair_count,
        )
        return "finalize"

    return "debugger"


def build_agent_graph(checkpointer: BaseCheckpointSaver | None = None):
    """Constructs the canonical 10-node agent graph with Day 9 repository intelligence."""
    builder = StateGraph(AgentState)

    # Canonical 10 Nodes
    builder.add_node("inspect_workspace", inspect_workspace)
    builder.add_node("repository_context", repository_context)  # Day 9 Node
    builder.add_node("planner", planner)
    builder.add_node("coder", coder)
    builder.add_node("approval_gate", approval_gate)
    builder.add_node("apply_approved_patch", apply_approved_patch)
    builder.add_node("test_runner", test_runner)
    builder.add_node("debugger", debugger)
    builder.add_node("reviewer", reviewer)
    builder.add_node("finalize", finalize)

    # Workflow Spine
    builder.add_edge(START, "inspect_workspace")
    builder.add_edge("inspect_workspace", "repository_context")  # Day 9 Spine
    builder.add_edge("repository_context", "planner")  # Day 9 Spine
    builder.add_edge("planner", "coder")
    builder.add_edge("coder", "approval_gate")

    # Conditional Edge: Approval Gate
    builder.add_conditional_edges(
        "approval_gate",
        route_after_approval,
        {
            "apply_approved_patch": "apply_approved_patch",
            "test_runner": "test_runner",
            "coder": "coder",
            "finalize": "finalize",
        },
    )

    builder.add_edge("apply_approved_patch", "test_runner")

    # Conditional Edge: Test Runner
    builder.add_conditional_edges(
        "test_runner",
        route_after_test,
        {
            "reviewer": "reviewer",
            "debugger": "debugger",
            "finalize": "finalize",
        },
    )

    # Repair Loop
    builder.add_edge("debugger", "coder")

    # Happy Path Finalization
    builder.add_edge("reviewer", "finalize")
    builder.add_edge("finalize", END)

    effective_checkpointer = (
        checkpointer
        if checkpointer is not None
        else MemorySaver()  # Fallback for offline unit tests
    )

    return builder.compile(checkpointer=effective_checkpointer)


def get_production_graph():
    """Constructs the production agent graph backed strictly by PostgreSQL."""
    saver = checkpointer_manager.get_checkpointer()
    return build_agent_graph(checkpointer=saver)
