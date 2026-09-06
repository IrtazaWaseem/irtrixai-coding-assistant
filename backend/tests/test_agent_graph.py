import pytest
from langgraph.types import Command

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


def test_state_invariants_repair_count_boundaries():
    """Verifies repair count boundaries: -1 -> reject, 0-3 -> valid, 4 -> reject."""
    state = create_initial_state("1", "/path", "thread-1")

    # -1 -> reject
    state["repair_count"] = -1
    with pytest.raises(ValueError, match="cannot be negative"):
        validate_state_invariants(state)

    # 0, 1, 2, 3 -> valid
    for count in range(4):
        state["repair_count"] = count
        validate_state_invariants(state)

    # 4 -> reject
    state["repair_count"] = 4
    with pytest.raises(ValueError, match="exceeds MAX_REPAIR_ITERATIONS"):
        validate_state_invariants(state)


def test_state_invariants_security_and_thread():
    """Verifies security invariants prevent empty threads and secret leaks."""
    # Empty thread rejection
    invalid_thread = create_initial_state("1", "/path", "")
    with pytest.raises(ValueError, match="thread_id must be non-empty"):
        validate_state_invariants(invalid_thread)

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
    """Verifies approval gate routing logic."""
    assert route_after_approval({"approval": True}) == "test_runner"
    assert route_after_approval({"approval": False}) == "finalize"
    assert (
        route_after_approval({"approval": False, "feedback": "Fix imports"}) == "coder"
    )
    # Unresolved approval must never route to test_runner
    assert route_after_approval({"approval": None}) == "finalize"


def test_route_after_test_repair_limits():
    """Verifies repair limit enforcement: fail-stops when repair_count >= 3."""
    assert route_after_test({"test_result": {"success": True}}) == "reviewer"

    # Failures within bounds (0, 1, 2) -> debugger
    for count in range(3):
        assert (
            route_after_test({"test_result": {"success": False}, "repair_count": count})
            == "debugger"
        )

    # Failures hitting threshold (3) -> finalize
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
async def test_in_memory_graph_happy_path_preapproved():
    """Executes full graph in-memory with pre-approved state verifying completion."""
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


@pytest.mark.asyncio
async def test_hitl_unresolved_approval_interrupts():
    """Finding 2A & 2D: Initial state with approval=None halts at approval_gate."""
    graph = build_agent_graph()
    thread_id = "thread-hitl-interrupt-check"
    config = {"configurable": {"thread_id": thread_id}}

    initial = create_initial_state(
        task_id="task-hitl-1",
        workspace_path="/test/workspace",
        thread_id=thread_id,
        prompt="Add authentication route",
    )
    assert initial["approval"] is None

    # Invoke graph - execution must suspend at approval_gate
    await graph.ainvoke(initial, config=config)

    snapshot = graph.get_state(config)

    # 1. Graph paused at approval_gate
    assert snapshot.next == ("approval_gate",)

    # 2. Interruption payload is exposed via LangGraph
    assert len(snapshot.tasks) > 0
    assert len(snapshot.tasks[0].interrupts) > 0
    payload = snapshot.tasks[0].interrupts[0].value
    assert payload["action"] == "human_approval_required"
    assert payload["pending_patch"] is not None

    # 3. Test runner and downstream nodes have NOT executed
    assert snapshot.values.get("test_result") is None
    assert snapshot.values.get("final_result") is None

    # 4. Approval was NOT silently coerced to True
    assert snapshot.values.get("approval") is None


@pytest.mark.asyncio
async def test_hitl_resume_with_approval():
    """Finding 2B & 2E: Resuming an interrupted thread with approval=True completes workflow."""
    graph = build_agent_graph()
    thread_id = "thread-hitl-resume-approved"
    config = {"configurable": {"thread_id": thread_id}}

    initial = create_initial_state(
        task_id="task-hitl-2",
        workspace_path="/test/workspace",
        thread_id=thread_id,
        prompt="Add metrics endpoint",
    )

    # 1. Run until suspended
    await graph.ainvoke(initial, config=config)
    assert graph.get_state(config).next == ("approval_gate",)

    # 2. Resume the SAME thread with explicit approval
    resumed = await graph.ainvoke(Command(resume={"approved": True}), config=config)

    # 3. Assert downstream execution proceeded through test_runner to completion
    assert resumed["approval"] is True
    assert resumed["test_result"] is not None
    assert resumed["review_summary"] is not None
    assert resumed["final_result"] is not None
    assert resumed["final_result"].status == "completed"

    # 4. Checkpoint ended cleanly and thread preserved
    assert graph.get_state(config).next == ()
    assert resumed["thread_id"] == thread_id


@pytest.mark.asyncio
async def test_hitl_resume_with_rejection():
    """Finding 2C & 2E: Resuming with approval=False aborts workflow without running tests."""
    graph = build_agent_graph()
    thread_id = "thread-hitl-resume-rejected"
    config = {"configurable": {"thread_id": thread_id}}

    initial = create_initial_state(
        task_id="task-hitl-3",
        workspace_path="/test/workspace",
        thread_id=thread_id,
        prompt="Add unsafe endpoint",
    )

    # 1. Run until suspended
    await graph.ainvoke(initial, config=config)
    assert graph.get_state(config).next == ("approval_gate",)

    # 2. Resume with explicit rejection
    resumed = await graph.ainvoke(Command(resume={"approved": False}), config=config)

    # 3. Downstream test runner was NOT reached
    assert resumed["approval"] is False
    assert resumed.get("test_result") is None

    # 4. Final state reflects aborted status
    assert resumed["final_result"] is not None
    assert resumed["final_result"].status == "aborted"
    assert "aborted by human operator" in resumed["final_result"].summary.lower()


@pytest.mark.asyncio
async def test_hitl_resume_with_rejection_and_feedback():
    """Finding 2C: Resuming with rejection and feedback routes back to coder."""
    graph = build_agent_graph()
    thread_id = "thread-hitl-feedback-loop"
    config = {"configurable": {"thread_id": thread_id}}

    initial = create_initial_state(
        task_id="task-hitl-4",
        workspace_path="/test/workspace",
        thread_id=thread_id,
        prompt="Add rate limiter",
    )

    # 1. Run until suspended
    await graph.ainvoke(initial, config=config)
    assert graph.get_state(config).next == ("approval_gate",)

    # 2. Resume with rejection and specific feedback
    await graph.ainvoke(
        Command(
            resume={
                "approved": False,
                "feedback": "Use redis token bucket algorithm",
            }
        ),
        config=config,
    )

    # 3. The graph routes back to coder and arrives at approval_gate again
    snapshot = graph.get_state(config)
    assert snapshot.next == ("approval_gate",)
    assert snapshot.values.get("feedback") == "Use redis token bucket algorithm"
    assert snapshot.values.get("test_result") is None


def test_hitl_no_implicit_approval_invariant():
    """Finding 2D: Unresolved approval can never route to test_runner."""
    # Routing test
    assert route_after_approval({"approval": None}) != "test_runner"
    assert route_after_approval({}) != "test_runner"
