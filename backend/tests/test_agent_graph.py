import pytest

from app.agent.graph import (
    build_agent_graph,
    route_after_approval,
    route_after_test,
)
from app.agent.state import (
    MAX_REPAIR_ITERATIONS,
    create_initial_state,
    validate_state_invariants,
)
from app.schemas.agent_contracts import (
    FinalizationResult,
    PlannerOutput,
    ReviewerOutput,
)


def test_create_initial_state_defaults():
    """Verifies default values and field initializations."""
    state = create_initial_state(
        task_id="task-uuid-101",
        workspace_path="/test/workspace",
        thread_id="thread-xyz-404",
        prompt="Build health check route",
    )

    assert state["task_id"] == "task-uuid-101"
    assert state["workspace_path"] == "/test/workspace"
    assert state["thread_id"] == "thread-xyz-404"
    assert len(state["messages"]) == 1
    assert state["messages"][0]["content"] == "Build health check route"
    assert state["repair_count"] == 0
    assert state["current_step"] == 0
    assert state["approval"] is None
    assert state["plan"] is None


def test_state_invariants_validation():
    """Verifies security invariants prevent empty threads, negative counters, and secrets."""
    valid_state = create_initial_state("1", "/path", "thread-1")
    validate_state_invariants(valid_state)

    # Empty thread rejection
    invalid_thread = create_initial_state("1", "/path", "")
    with pytest.raises(ValueError, match="thread_id must be non-empty"):
        validate_state_invariants(invalid_thread)

    # Negative repair rejection
    negative_repair = create_initial_state("1", "/path", "thread-1")
    negative_repair["repair_count"] = -1
    with pytest.raises(ValueError, match="cannot be negative"):
        validate_state_invariants(negative_repair)

    # Secret isolation check
    leaked_state = create_initial_state("1", "/path", "thread-1")
    leaked_state["api_key"] = "AIzaSecret123"  # type: ignore[typeddict-unknown-key]
    with pytest.raises(ValueError, match="Security violation"):
        validate_state_invariants(leaked_state)


def test_graph_topology_contains_required_nodes():
    """Verifies all 8 required nodes are compiled into the StateGraph."""
    graph = build_agent_graph()
    node_keys = set(graph.nodes.keys())

    required_nodes = {
        "inspect_workspace",
        "planner",
        "coder",
        "approval_gate",
        "test_runner",
        "debugger",
        "reviewer",
        "finalize",
    }

    assert required_nodes.issubset(node_keys)


def test_route_after_approval_logic():
    """Verifies approval gate routing: approved -> test_runner, rejected -> finalize, feedback -> coder."""
    assert route_after_approval({"approval": True}) == "test_runner"
    assert route_after_approval({"approval": False}) == "finalize"
    assert (
        route_after_approval({"approval": False, "feedback": "Fix imports"}) == "coder"
    )


def test_route_after_test_repair_limits():
    """Verifies repair limit enforcement: fail-stops when repair_count >= 3."""
    # Test pass -> reviewer
    assert route_after_test({"test_result": {"success": True}}) == "reviewer"

    # Test failures within bounds (0, 1, 2) -> debugger
    assert (
        route_after_test({"test_result": {"success": False}, "repair_count": 0})
        == "debugger"
    )
    assert (
        route_after_test({"test_result": {"success": False}, "repair_count": 1})
        == "debugger"
    )
    assert (
        route_after_test({"test_result": {"success": False}, "repair_count": 2})
        == "debugger"
    )

    # Test failures hitting threshold -> finalize
    assert (
        route_after_test(
            {
                "test_result": {"success": False},
                "repair_count": MAX_REPAIR_ITERATIONS,
            }
        )
        == "finalize"
    )
    assert (
        route_after_test({"test_result": {"success": False}, "repair_count": 4})
        == "finalize"
    )


@pytest.mark.asyncio
async def test_in_memory_graph_happy_path_execution():
    """Executes full graph in-memory with pre-approved state verifying clean completion."""
    graph = build_agent_graph()
    initial = create_initial_state(
        task_id="task-001",
        workspace_path="/mock/workspace",
        thread_id="thread-test-run-1",
        prompt="Implement calculator",
    )
    initial["approval"] = True

    config = {"configurable": {"thread_id": "thread-test-run-1"}}
    final_state = await graph.ainvoke(initial, config=config)

    assert final_state["thread_id"] == "thread-test-run-1"
    assert final_state["current_step"] == 8
    assert isinstance(final_state["plan"], PlannerOutput)
    assert isinstance(final_state["review_summary"], ReviewerOutput)
    assert isinstance(final_state["final_result"], FinalizationResult)
    assert final_state["final_result"].status == "completed"
