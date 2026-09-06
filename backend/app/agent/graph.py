from typing import Any, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.agent.nodes import (
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


def route_after_approval(
    state: AgentState,
) -> Literal["test_runner", "coder", "finalize"]:
    """Routes based on human approval verdict."""
    approval = state.get("approval")
    if approval is False:
        if state.get("feedback"):
            return "coder"
        return "finalize"
    if approval is True:
        return "test_runner"
    return "finalize"


def route_after_test(
    state: AgentState,
) -> Literal["reviewer", "debugger", "finalize"]:
    """Routes based on test outcomes and strictly enforces max 3 repair iterations."""
    test_res = state.get("test_result") or {}
    success = test_res.get("success", False)

    if success:
        return "reviewer"

    repair_count = state.get("repair_count", 0)
    if repair_count < MAX_REPAIR_ITERATIONS:
        return "debugger"

    return "finalize"


def build_agent_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> Any:
    """Builds and compiles the IrtrixAI LangGraph workflow."""
    workflow = StateGraph(AgentState)

    # 1. Register all 8 nodes
    workflow.add_node("inspect_workspace", inspect_workspace)
    workflow.add_node("planner", planner)
    workflow.add_node("coder", coder)
    workflow.add_node("approval_gate", approval_gate)
    workflow.add_node("test_runner", test_runner)
    workflow.add_node("debugger", debugger)
    workflow.add_node("reviewer", reviewer)
    workflow.add_node("finalize", finalize)

    # 2. Pipeline edges
    workflow.add_edge(START, "inspect_workspace")
    workflow.add_edge("inspect_workspace", "planner")
    workflow.add_edge("planner", "coder")
    workflow.add_edge("coder", "approval_gate")

    # 3. Conditional routing
    workflow.add_conditional_edges(
        "approval_gate",
        route_after_approval,
        {
            "test_runner": "test_runner",
            "coder": "coder",
            "finalize": "finalize",
        },
    )

    workflow.add_conditional_edges(
        "test_runner",
        route_after_test,
        {
            "reviewer": "reviewer",
            "debugger": "debugger",
            "finalize": "finalize",
        },
    )

    # 4. Repair loop & termination edges
    workflow.add_edge("debugger", "coder")
    workflow.add_edge("reviewer", "finalize")
    workflow.add_edge("finalize", END)

    saver = checkpointer if checkpointer is not None else MemorySaver()
    return workflow.compile(checkpointer=saver)
