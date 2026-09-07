import logging

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.checkpoint import checkpointer_manager
from app.agent.nodes import (
    apply_approved_patch,
    approval_gate,
    coder,
    debugger,
    finalize,
    inspect_workspace,
    planner,
    reviewer,
    test_runner,
)
from app.agent.state import MAX_REPAIR_ITERATIONS, AgentState

logger = logging.getLogger(__name__)


def route_after_approval(state: AgentState) -> str:
    """Routes after human approval gate.

    - Approved with pending patch -> apply_approved_patch
    - Approved without pending patch -> test_runner
    - Rejected with feedback -> coder
    - Rejected without feedback -> finalize (aborted)
    """
    approval = state.get("approval")
    feedback = state.get("feedback")

    if approval is True:
        if state.get("pending_patch"):
            return "apply_approved_patch"
        return "test_runner"
    if approval is False and feedback:
        return "coder"
    return "finalize"


def route_after_test(state: AgentState) -> str:
    """Routes based on test runner outcome and repair count limits.

    - Success -> reviewer
    - Failure and repair_count < 3 -> debugger
    - Failure and repair_count >= 3 -> finalize (exhausted)
    """
    test_res = state.get("test_result")
    repair_count = state.get("repair_count", 0)

    test_passed = isinstance(test_res, dict) and test_res.get("success") is True

    if test_passed:
        return "reviewer"

    if repair_count < MAX_REPAIR_ITERATIONS:
        return "debugger"

    return "finalize"


def build_agent_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Builds and compiles the full IrtrixAI StateGraph."""
    builder = StateGraph(AgentState)

    # 1. Register all 9 domain nodes
    builder.add_node("inspect_workspace", inspect_workspace)
    builder.add_node("planner", planner)
    builder.add_node("coder", coder)
    builder.add_node("approval_gate", approval_gate)
    builder.add_node("apply_approved_patch", apply_approved_patch)
    builder.add_node("test_runner", test_runner)
    builder.add_node("debugger", debugger)
    builder.add_node("reviewer", reviewer)
    builder.add_node("finalize", finalize)

    # 2. Linear initialization edges
    builder.add_edge(START, "inspect_workspace")
    builder.add_edge("inspect_workspace", "planner")
    builder.add_edge("planner", "coder")
    builder.add_edge("coder", "approval_gate")

    # 3. Conditional routing after approval gate
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

    # 4. Patch application transitions to test runner
    builder.add_edge("apply_approved_patch", "test_runner")

    # 5. Conditional routing after test execution
    builder.add_conditional_edges(
        "test_runner",
        route_after_test,
        {
            "reviewer": "reviewer",
            "debugger": "debugger",
            "finalize": "finalize",
        },
    )

    # 6. Repair and review feedback edges
    builder.add_edge("debugger", "coder")
    builder.add_edge("reviewer", "finalize")
    builder.add_edge("finalize", END)

    saver = checkpointer if checkpointer is not None else MemorySaver()
    return builder.compile(checkpointer=saver)


def get_production_graph() -> CompiledStateGraph:
    """Returns production StateGraph backed by the initialized PostgreSQL checkpointer."""
    saver = checkpointer_manager.get_checkpointer()
    return build_agent_graph(checkpointer=saver)
