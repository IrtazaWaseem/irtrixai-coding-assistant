from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agent.graph import (
    build_agent_graph,
    route_after_approval,
    route_after_patch,
    route_after_test,
)
from app.agent.nodes import (
    coder,
    debugger,
    finalize,
    planner,
    reviewer,
    set_llm_gateway,
)
from app.agent.state import (
    MAX_REPAIR_ITERATIONS,
    create_initial_state,
    validate_state_invariants,
)
from app.core.exceptions import LLMResponseException
from app.schemas.agent_contracts import (
    CoderOutput,
    DebuggerOutput,
    FinalizationResult,
    PlannerOutput,
    ReviewerOutput,
)
from app.services.llm.gateway import LLMGateway


def make_success_execution_service():
    service = MagicMock()
    service.execute_in_sandbox.return_value = {
        "command": "pytest",
        "exit_code": 0,
        "stdout": "1 passed\n",
        "stderr": "",
        "truncated": False,
        "duration_seconds": 0.01,
    }
    return service


@pytest.fixture(autouse=True)
def mock_gateway_fixture():
    """Provides an isolated in-memory mock LLMGateway for all graph unit tests."""
    mock_gw = MagicMock(spec=LLMGateway)

    async def default_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(
                summary="Plan created via mock gateway",
                steps=["Inspect files", "Apply patch"],
                files_expected=["src/main.py"],
            )
        if response_schema is CoderOutput:
            return CoderOutput(
                summary="Code changes proposed via mock gateway",
                requested_changes=["Add endpoint"],
                patch="--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n+test\n",
                files_changed=["src/main.py"],
            )
        if response_schema is DebuggerOutput:
            return DebuggerOutput(
                diagnosis="Test assertion failure detected",
                proposed_fix="Correct the assertion value",
                files_to_change=["src/main.py"],
            )
        if response_schema is ReviewerOutput:
            return ReviewerOutput(
                verdict="approved",
                summary="Implementation reviewed and verified",
                issues=[],
                security_concerns=[],
                required_changes=[],
            )
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=default_structured)
    set_llm_gateway(mock_gw)
    yield mock_gw
    set_llm_gateway(None)


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
    invalid_thread = create_initial_state("1", "/path", "")
    with pytest.raises(ValueError, match="thread_id must be non-empty"):
        validate_state_invariants(invalid_thread)

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
    assert (
        route_after_approval({"approval": True, "pending_patch": "diff content"})
        == "apply_approved_patch"
    )
    assert route_after_approval({"approval": True}) == "test_runner"
    assert (
        route_after_approval(
            {"approval": True, "pending_patch": "diff", "error": "Coder failed: 429"}
        )
        == "finalize"
    )
    assert route_after_approval({"approval": False}) == "finalize"
    assert route_after_approval({"approval": False, "feedback": "Fix imports"}) == "coder"
    assert route_after_approval({"approval": None}) == "finalize"


def test_route_after_patch_logic():
    """Verifies patch application routing logic."""
    assert route_after_patch({"error": "Patch application failed"}) == "finalize"
    assert route_after_patch({"error": None}) == "test_runner"
    assert route_after_patch({}) == "test_runner"


def test_route_after_test_repair_limits():
    """Verifies repair limit enforcement: fail-stops when repair_count >= 3."""
    assert route_after_test({"test_result": {"success": True}}) == "reviewer"

    for count in range(3):
        assert (
            route_after_test({"test_result": {"success": False}, "repair_count": count})
            == "debugger"
        )

    assert (
        route_after_test(
            {
                "test_result": {"success": False},
                "repair_count": MAX_REPAIR_ITERATIONS,
            }
        )
        == "finalize"
    )
    assert route_after_test({"test_result": {"success": False}, "repair_count": 4}) == "finalize"


@pytest.mark.asyncio
async def test_in_memory_graph_happy_path_preapproved(mock_gateway_fixture):
    """Executes full graph in-memory with pre-approved state and verified non-stub test results."""
    graph = build_agent_graph()
    initial = create_initial_state(
        task_id="task-001",
        workspace_path="/mock/workspace",
        thread_id="thread-test-run-1",
        prompt="Implement calculator",
    )
    initial["approval"] = True
    initial["test_result"] = {
        "success": True,
        "output": "3 passed",
        "is_stub": False,
    }

    config = {
        "configurable": {
            "thread_id": "thread-test-run-1",
            "execution_service": make_success_execution_service(),
        }
    }
    final_state = await graph.ainvoke(initial, config=config)

    assert final_state["thread_id"] == "thread-test-run-1"
    assert final_state["current_step"] == 8
    assert isinstance(final_state["plan"], PlannerOutput)
    assert isinstance(final_state["review_summary"], ReviewerOutput)
    assert isinstance(final_state["final_result"], FinalizationResult)
    assert final_state["final_result"].status == "completed"


@pytest.mark.asyncio
async def test_in_memory_graph_execution_unavailable_does_not_complete(
    mock_gateway_fixture,
):
    """Verifies unavailable sandbox execution cannot produce a completed task."""
    graph = build_agent_graph()
    initial = create_initial_state(
        task_id="task-no-exec-1",
        workspace_path="/mock/workspace",
        thread_id="thread-no-exec-1",
        prompt="Implement calculator",
    )
    initial["approval"] = True

    config = {"configurable": {"thread_id": "thread-no-exec-1"}}
    final_state = await graph.ainvoke(initial, config=config)

    snapshot = graph.get_state(config)
    assert snapshot.next == ("approval_gate",)
    assert snapshot.values["test_result"]["execution_unavailable"] is True
    assert final_state.get("final_result") is None
    assert final_state["test_result"]["success"] is False


@pytest.mark.asyncio
async def test_hitl_unresolved_approval_interrupts(mock_gateway_fixture):
    """Initial state with approval=None halts at approval_gate."""
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

    await graph.ainvoke(initial, config=config)
    snapshot = graph.get_state(config)

    assert snapshot.next == ("approval_gate",)
    assert len(snapshot.tasks) > 0
    assert len(snapshot.tasks[0].interrupts) > 0
    payload = snapshot.tasks[0].interrupts[0].value
    assert payload["action"] == "human_approval_required"
    assert payload["pending_patch"] is not None

    assert snapshot.values.get("test_result") is None
    assert snapshot.values.get("final_result") is None
    assert snapshot.values.get("approval") is None


@pytest.mark.asyncio
async def test_hitl_resume_with_approval(mock_gateway_fixture):
    """Resuming an interrupted thread with approval=True and verified test results completes workflow."""
    graph = build_agent_graph()
    thread_id = "thread-hitl-resume-approved"
    config = {
        "configurable": {
            "thread_id": thread_id,
            "execution_service": make_success_execution_service(),
        }
    }

    initial = create_initial_state(
        task_id="task-hitl-2",
        workspace_path="/test/workspace",
        thread_id=thread_id,
        prompt="Add metrics endpoint",
    )
    initial["test_result"] = {
        "success": True,
        "output": "3 passed",
        "is_stub": False,
    }

    await graph.ainvoke(initial, config=config)
    assert graph.get_state(config).next == ("approval_gate",)

    resumed = await graph.ainvoke(Command(resume={"approved": True}), config=config)

    assert resumed["approval"] is True
    assert resumed["test_result"] is not None
    assert resumed["review_summary"] is not None
    assert resumed["final_result"] is not None
    assert resumed["final_result"].status == "completed"

    assert graph.get_state(config).next == ()
    assert resumed["thread_id"] == thread_id


@pytest.mark.asyncio
async def test_hitl_resume_with_rejection(mock_gateway_fixture):
    """Resuming with approval=False aborts workflow without running tests."""
    graph = build_agent_graph()
    thread_id = "thread-hitl-resume-rejected"
    config = {"configurable": {"thread_id": thread_id}}

    initial = create_initial_state(
        task_id="task-hitl-3",
        workspace_path="/test/workspace",
        thread_id=thread_id,
        prompt="Add unsafe endpoint",
    )

    await graph.ainvoke(initial, config=config)
    assert graph.get_state(config).next == ("approval_gate",)

    resumed = await graph.ainvoke(Command(resume={"approved": False}), config=config)

    assert resumed["approval"] is False
    assert resumed.get("test_result") is None
    assert resumed["final_result"] is not None
    assert resumed["final_result"].status == "aborted"


@pytest.mark.asyncio
async def test_hitl_resume_with_rejection_and_feedback(mock_gateway_fixture):
    """Resuming with rejection and feedback routes back to coder."""
    graph = build_agent_graph()
    thread_id = "thread-hitl-feedback-loop"
    config = {"configurable": {"thread_id": thread_id}}

    initial = create_initial_state(
        task_id="task-hitl-4",
        workspace_path="/test/workspace",
        thread_id=thread_id,
        prompt="Add rate limiter",
    )

    await graph.ainvoke(initial, config=config)
    assert graph.get_state(config).next == ("approval_gate",)

    await graph.ainvoke(
        Command(
            resume={
                "approved": False,
                "feedback": "Use redis token bucket algorithm",
            }
        ),
        config=config,
    )

    snapshot = graph.get_state(config)
    assert snapshot.next == ("approval_gate",)
    assert snapshot.values.get("feedback") == "Use redis token bucket algorithm"
    assert snapshot.values.get("test_result") is None


def test_hitl_no_implicit_approval_invariant():
    """Unresolved approval can never route to test_runner."""
    assert route_after_approval({"approval": None}) != "test_runner"
    assert route_after_approval({}) != "test_runner"


# --- Part 2 Targeted Node Tests ---


@pytest.mark.asyncio
async def test_planner_node_structured_output():
    """Verifies planner calls gateway structured output and updates state."""
    mock_gw = MagicMock(spec=LLMGateway)
    expected_plan = PlannerOutput(
        summary="Add healthcheck endpoint",
        steps=["Create route in app/api/v1", "Register in router"],
        files_expected=["app/api/v1/health.py"],
    )
    mock_gw.generate_structured = AsyncMock(return_value=expected_plan)

    state = create_initial_state("1", "/test", "t1", prompt="Add health endpoint")
    res = await planner(state, config={"configurable": {"llm_gateway": mock_gw}})

    assert res["plan"] == expected_plan
    assert res["current_step"] == 2
    mock_gw.generate_structured.assert_awaited_once()


@pytest.mark.asyncio
async def test_planner_node_error_handling():
    """Verifies planner handles gateway failure without fabricating plan."""
    mock_gw = MagicMock(spec=LLMGateway)
    mock_gw.generate_structured = AsyncMock(side_effect=LLMResponseException("JSON decode error"))

    state = create_initial_state("1", "/test", "t1", prompt="Add endpoint")
    res = await planner(state, config={"configurable": {"llm_gateway": mock_gw}})

    assert res.get("plan") is None
    assert "Planner failed" in res["error"]


@pytest.mark.asyncio
async def test_coder_node_structured_output():
    """Verifies coder calls gateway and produces CoderOutput with pending_patch."""
    mock_gw = MagicMock(spec=LLMGateway)
    expected_proposal = CoderOutput(
        summary="Added healthcheck router",
        requested_changes=["Add GET /health"],
        patch="@@ -0,0 +1,5 @@\n+def health():\n+    return {'status': 'ok'}",
        files_changed=["app/api/v1/health.py"],
    )
    mock_gw.generate_structured = AsyncMock(return_value=expected_proposal)

    state = create_initial_state("1", "/test", "t1", prompt="Add health")
    state["plan"] = PlannerOutput(summary="Plan", steps=["Step 1"])

    res = await coder(state, config={"configurable": {"llm_gateway": mock_gw}})

    assert res["coder_proposal"] == expected_proposal
    assert res["pending_patch"] == expected_proposal.patch
    assert res["current_step"] == 3
    mock_gw.generate_structured.assert_awaited_once()


@pytest.mark.asyncio
async def test_coder_proposal_not_authoritative_execution():
    """Verifies coder proposal does not populate applied_diff or claim execution."""
    mock_gw = MagicMock(spec=LLMGateway)
    proposal = CoderOutput(
        summary="Proposal",
        patch="patch content",
        files_changed=["file.py"],
    )
    mock_gw.generate_structured = AsyncMock(return_value=proposal)

    state = create_initial_state("1", "/test", "t1", prompt="Task")
    res = await coder(state, config={"configurable": {"llm_gateway": mock_gw}})

    assert "applied_diff" not in res
    assert res.get("tool_result") is None


@pytest.mark.asyncio
async def test_debugger_node_requires_failed_test():
    """Verifies debugger rejects execution if test_result is missing or succeeded."""
    mock_gw = MagicMock(spec=LLMGateway)
    state = create_initial_state("1", "/test", "t1")

    # 1. No test result
    res1 = await debugger(state, config={"configurable": {"llm_gateway": mock_gw}})
    assert "Debugger invoked without a failed test result" in res1["error"]

    # 2. Passing test result
    state["test_result"] = {"success": True, "output": "All passed"}
    res2 = await debugger(state, config={"configurable": {"llm_gateway": mock_gw}})
    assert "Debugger invoked without a failed test result" in res2["error"]
    mock_gw.generate_structured.assert_not_called()


@pytest.mark.asyncio
async def test_debugger_node_structured_output_and_repair_count():
    """Verifies debugger diagnoses failure and increments repair count up to 3."""
    mock_gw = MagicMock(spec=LLMGateway)
    expected_diag = DebuggerOutput(
        diagnosis="Null pointer in auth handler",
        proposed_fix="Add none check before accessing token",
        files_to_change=["app/auth.py"],
    )
    mock_gw.generate_structured = AsyncMock(return_value=expected_diag)

    state = create_initial_state("1", "/test", "t1")
    state["test_result"] = {
        "success": False,
        "output": "AssertionError: None is not True",
    }
    state["repair_count"] = 1

    res = await debugger(state, config={"configurable": {"llm_gateway": mock_gw}})

    assert res["debugger_output"] == expected_diag
    assert res["repair_count"] == 2
    assert res["current_step"] == 6


@pytest.mark.asyncio
async def test_reviewer_node_structured_output():
    """Verifies reviewer produces validated ReviewerOutput."""
    mock_gw = MagicMock(spec=LLMGateway)
    expected_review = ReviewerOutput(
        verdict="approved",
        summary="Code meets all quality and architecture guidelines",
        issues=[],
        security_concerns=[],
        required_changes=[],
    )
    mock_gw.generate_structured = AsyncMock(return_value=expected_review)

    state = create_initial_state("1", "/test", "t1")
    state["test_result"] = {"success": True, "output": "10 passed"}
    state["coder_proposal"] = CoderOutput(summary="Done", files_changed=["test.py"])

    res = await reviewer(state, config={"configurable": {"llm_gateway": mock_gw}})

    assert res["review_summary"] == expected_review
    assert res["current_step"] == 7


@pytest.mark.asyncio
async def test_reviewer_cannot_override_failed_test():
    """Verifies reviewer cannot issue 'approved' verdict if test_result indicates failure."""
    mock_gw = MagicMock(spec=LLMGateway)
    hallucinated_approval = ReviewerOutput(
        verdict="approved",
        summary="Looks great to me!",
    )
    mock_gw.generate_structured = AsyncMock(return_value=hallucinated_approval)

    state = create_initial_state("1", "/test", "t1")
    state["test_result"] = {"success": False, "output": "Tests crashed"}

    res = await reviewer(state, config={"configurable": {"llm_gateway": mock_gw}})

    assert res["review_summary"].verdict == "rejected"
    assert "automated override" in res["review_summary"].summary.lower()


@pytest.mark.asyncio
async def test_reviewer_cannot_override_unverified_truthy_string_test():
    """Verifies reviewer coerces approved to rejected when test success is a truthy string."""
    mock_gw = MagicMock(spec=LLMGateway)
    mock_gw.generate_structured = AsyncMock(
        return_value=ReviewerOutput(
            verdict="approved",
            summary="Approved regardless of tests",
            issues=[],
            security_concerns=[],
            required_changes=[],
        )
    )
    state = create_initial_state("1", "/test", "t1")
    state["test_result"] = {"success": "false", "output": "Tests crashed"}

    res = await reviewer(state, config={"configurable": {"llm_gateway": mock_gw}})
    assert res["review_summary"].verdict == "rejected"
    assert "automated override" in res["review_summary"].summary.lower()


@pytest.mark.asyncio
async def test_finalize_reflects_actual_evidence_only():
    """Verifies finalize fails when code changes were proposed without applied diff, without fabricating files."""
    state = create_initial_state("1", "/test", "t1")
    state["approval"] = True
    state["test_result"] = {"success": True, "is_stub": False}
    state["test_command"] = "pytest tests/unit"
    state["review_summary"] = ReviewerOutput(
        verdict="approved",
        summary="All checks verified",
        issues=[],
        security_concerns=[],
        required_changes=[],
    )
    state["coder_proposal"] = CoderOutput(
        summary="Proposed changes",
        patch="--- a/unapplied.py\n+++ b/unapplied.py\n@@ -1 +1 @@\n+x\n",
        files_changed=["unapplied.py"],
    )

    res = await finalize(state)
    final: FinalizationResult = res["final_result"]

    assert final.status == "failed"
    assert final.tests == ["pytest tests/unit"]
    assert final.files_changed == []


@pytest.mark.asyncio
async def test_graph_patch_application_failure_routes_to_finalize_without_running_tests(
    tmp_path: Path,
):
    """Regression test: apply_approved_patch failure routes directly to finalize, bypassing test_runner."""
    ws = tmp_path / "ws_patch_fail"
    ws.mkdir(parents=True, exist_ok=True)

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(summary="Plan", steps=["S1"], files_expected=["nonexistent.py"])
        if response_schema is CoderOutput:
            return CoderOutput(
                summary="Bad patch",
                patch="--- a/nonexistent.py\n+++ b/nonexistent.py\n@@ -1,1 +1,1 @@\n-invalid\n+context\n",
                files_changed=["nonexistent.py"],
            )
        if response_schema is ReviewerOutput:
            return ReviewerOutput(verdict="approved", summary="Should not run")
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)

    mock_exec = make_success_execution_service()
    memory_saver = MemorySaver()
    graph = build_agent_graph(checkpointer=memory_saver)

    thread_id = "thread-regression-patch-fail"
    config = {
        "configurable": {
            "thread_id": thread_id,
            "llm_gateway": mock_gw,
            "execution_service": mock_exec,
        }
    }

    initial = create_initial_state(
        task_id="task-patch-fail-1",
        workspace_path=str(ws),
        thread_id=thread_id,
        prompt="Fix bug",
    )

    await graph.ainvoke(initial, config=config)
    resumed = await graph.ainvoke(Command(resume={"approved": True}), config=config)

    assert resumed["final_result"] is not None
    assert resumed["final_result"].status == "failed"
    assert resumed.get("test_result") is None
    assert resumed.get("review_summary") is None
    mock_exec.execute_in_sandbox.assert_not_called()


@pytest.mark.asyncio
async def test_graph_noop_proposal_completes_successfully():
    """Verifies legitimate no-op proposals with patch='' and files_changed=[] complete normally."""
    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(summary="Plan", steps=["Verify only"], files_expected=[])
        if response_schema is CoderOutput:
            return CoderOutput(summary="No change needed", patch="", files_changed=[])
        if response_schema is ReviewerOutput:
            return ReviewerOutput(verdict="approved", summary="No changes required, tests verified")
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)

    mock_exec = make_success_execution_service()
    memory_saver = MemorySaver()
    graph = build_agent_graph(checkpointer=memory_saver)

    thread_id = "thread-noop-complete"
    config = {
        "configurable": {
            "thread_id": thread_id,
            "llm_gateway": mock_gw,
            "execution_service": mock_exec,
        }
    }

    initial = create_initial_state(
        task_id="task-noop-1",
        workspace_path="/test/workspace",
        thread_id=thread_id,
        prompt="Verify functionality",
    )
    initial["test_command"] = "pytest"

    await graph.ainvoke(initial, config=config)
    resumed = await graph.ainvoke(Command(resume={"approved": True}), config=config)

    assert resumed["final_result"] is not None
    assert resumed["final_result"].status == "completed"
    assert resumed["final_result"].files_changed == []
    mock_exec.execute_in_sandbox.assert_called_once()


@pytest.mark.asyncio
async def test_graph_coder_failure_does_not_phantom_pass_after_approval():
    """Regression test: when Coder fails, approving must NOT run test_runner or complete task."""
    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured_with_coder_failure(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(summary="Plan", steps=["Step 1"], files_expected=["a.py"])
        if response_schema is CoderOutput:
            raise LLMResponseException("429 Too Many Requests: Rate limit exceeded")
        if response_schema is ReviewerOutput:
            return ReviewerOutput(verdict="approved", summary="Approved")
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured_with_coder_failure)
    set_llm_gateway(mock_gw)

    mock_exec = make_success_execution_service()
    memory_saver = MemorySaver()
    graph = build_agent_graph(checkpointer=memory_saver)

    thread_id = "thread-regression-phantom-pass"
    config = {
        "configurable": {
            "thread_id": thread_id,
            "llm_gateway": mock_gw,
            "execution_service": mock_exec,
        }
    }

    initial = create_initial_state(
        task_id="task-phantom-1",
        workspace_path="/test/workspace",
        thread_id=thread_id,
        prompt="Build feature",
    )

    await graph.ainvoke(initial, config=config)
    snap = graph.get_state(config)
    assert snap.next == ("approval_gate",)
    assert "429" in str(snap.values.get("error"))

    resumed = await graph.ainvoke(Command(resume={"approved": True}), config=config)

    assert resumed["final_result"] is not None
    assert resumed["final_result"].status == "failed"
    assert resumed["final_result"].files_changed == []
    mock_exec.execute_in_sandbox.assert_not_called()


def test_model_output_has_no_execution_authority():
    """Verifies malicious commands or paths in model output cannot bypass boundaries."""
    malicious_proposal = CoderOutput(
        summary="Apply root exploit",
        requested_changes=["rm -rf /"],
        patch="--- a/../../etc/passwd\n+++ b/../../etc/passwd\n",
        files_changed=["../../etc/passwd"],
    )
    assert len(malicious_proposal.files_changed) == 1
    assert not hasattr(malicious_proposal, "apply")
    assert not hasattr(malicious_proposal, "execute")


# --- Reviewer Governance & Evidence Safety Tests ---


@pytest.mark.asyncio
async def test_finalize_success_true_is_stub_false_approved_completed():
    """Verifies success=True, is_stub=False, approved reviewer, human approval -> completed."""
    state = create_initial_state("1", "/test", "t1")
    state["approval"] = True
    state["applied_diff"] = "diff"
    state["test_result"] = {"success": True, "output": "3 passed", "is_stub": False}
    state["review_summary"] = ReviewerOutput(
        verdict="approved",
        summary="Verified",
        issues=[],
        security_concerns=[],
        required_changes=[],
    )
    res = await finalize(state)
    assert res["final_result"].status == "completed"


@pytest.mark.asyncio
async def test_finalize_success_true_is_stub_true_approved_failed():
    """Verifies success=True, is_stub=True, approved reviewer, human approval -> failed."""
    state = create_initial_state("1", "/test", "t1")
    state["approval"] = True
    state["test_result"] = {"success": True, "output": "Stub passed", "is_stub": True}
    state["review_summary"] = ReviewerOutput(
        verdict="approved",
        summary="Verified",
        issues=[],
        security_concerns=[],
        required_changes=[],
    )
    res = await finalize(state)
    assert res["final_result"].status == "failed"
    assert res["final_result"].status != "completed"
    assert (
        "placeholder" in res["final_result"].summary.lower()
        or "stub" in res["final_result"].summary.lower()
    )


@pytest.mark.asyncio
async def test_finalize_success_true_missing_is_stub_approved_completed():
    """Verifies success=True with missing is_stub preserves existing intended behavior (completed)."""
    state = create_initial_state("1", "/test", "t1")
    state["approval"] = True
    state["applied_diff"] = "diff"
    state["test_result"] = {"success": True, "output": "3 passed in sandbox"}
    state["review_summary"] = ReviewerOutput(
        verdict="approved",
        summary="Verified",
        issues=[],
        security_concerns=[],
        required_changes=[],
    )
    res = await finalize(state)
    assert res["final_result"].status == "completed"


@pytest.mark.asyncio
async def test_finalize_tests_pass_reviewer_rejected_not_completed():
    """Verifies tests pass + reviewer rejected produces failed status, not completed."""
    state = create_initial_state("1", "/test", "t1")
    state["approval"] = True
    state["test_result"] = {"success": True, "output": "3 passed", "is_stub": False}
    state["review_summary"] = ReviewerOutput(
        verdict="rejected",
        summary="Security flaw detected",
        issues=["SQL injection"],
        security_concerns=["Raw query concatenation"],
        required_changes=["Use parameterized queries"],
    )
    res = await finalize(state)
    assert res["final_result"].status == "failed"
    assert res["final_result"].status != "completed"
    assert "reviewer rejected" in res["final_result"].summary.lower()


@pytest.mark.asyncio
async def test_finalize_tests_pass_reviewer_changes_requested_not_completed():
    """Verifies tests pass + reviewer changes_requested produces failed status, not completed."""
    state = create_initial_state("1", "/test", "t1")
    state["approval"] = True
    state["test_result"] = {"success": True, "output": "3 passed", "is_stub": False}
    state["review_summary"] = ReviewerOutput(
        verdict="changes_requested",
        summary="Refactoring required",
        issues=["High cyclomatic complexity"],
        security_concerns=[],
        required_changes=["Break function into smaller helpers"],
    )
    res = await finalize(state)
    assert res["final_result"].status == "failed"
    assert res["final_result"].status != "completed"
    assert "changes" in res["final_result"].summary.lower()


@pytest.mark.asyncio
async def test_finalize_truthy_string_false_not_treated_as_passed():
    """Verifies string 'false' in test_result is not treated as boolean True."""
    state = create_initial_state("1", "/test", "t1")
    state["approval"] = True
    state["test_result"] = {"success": "false", "output": "Tests failed"}
    state["review_summary"] = ReviewerOutput(
        verdict="approved",
        summary="Verified",
        issues=[],
        security_concerns=[],
        required_changes=[],
    )
    res = await finalize(state)
    assert res["final_result"].status == "failed"
    assert res["final_result"].status != "completed"


@pytest.mark.asyncio
async def test_finalize_truthy_string_true_not_treated_as_passed():
    """Verifies string 'true' in test_result is not treated as boolean True."""
    state = create_initial_state("1", "/test", "t1")
    state["approval"] = True
    state["test_result"] = {"success": "true", "output": "Tests passed"}
    state["review_summary"] = ReviewerOutput(
        verdict="approved",
        summary="Verified",
        issues=[],
        security_concerns=[],
        required_changes=[],
    )
    res = await finalize(state)
    assert res["final_result"].status == "failed"
    assert res["final_result"].status != "completed"


@pytest.mark.asyncio
async def test_finalize_truthy_integer_not_treated_as_passed():
    """Verifies integer 1 in test_result is not treated as boolean True."""
    state = create_initial_state("1", "/test", "t1")
    state["approval"] = True
    state["test_result"] = {"success": 1, "output": "Exit code 1"}
    state["review_summary"] = ReviewerOutput(
        verdict="approved",
        summary="Verified",
        issues=[],
        security_concerns=[],
        required_changes=[],
    )
    res = await finalize(state)
    assert res["final_result"].status == "failed"
    assert res["final_result"].status != "completed"


@pytest.mark.asyncio
async def test_finalize_missing_test_result_not_completed():
    """Verifies missing test result causes finalization failure, not completed."""
    state = create_initial_state("1", "/test", "t1")
    state["approval"] = True
    state["test_result"] = None
    state["review_summary"] = ReviewerOutput(
        verdict="approved",
        summary="Verified",
        issues=[],
        security_concerns=[],
        required_changes=[],
    )
    res = await finalize(state)
    assert res["final_result"].status == "failed"
    assert res["final_result"].status != "completed"
    assert "authoritative test verification" in res["final_result"].summary.lower()


@pytest.mark.asyncio
async def test_node_error_handling_sanitizes_secrets():
    """Verifies node error handling redacts API keys and bearer tokens from state error."""
    mock_gw = MagicMock(spec=LLMGateway)
    fake_token = "gsk_super_secret_groq_key_987654321"
    mock_gw.generate_structured = AsyncMock(
        side_effect=Exception(f"Failed connecting with Bearer {fake_token}")
    )

    state = create_initial_state("1", "/test", "t1", prompt="Add endpoint")
    res = await planner(state, config={"configurable": {"llm_gateway": mock_gw}})

    assert "error" in res
    err_text = res["error"]
    assert fake_token not in err_text
    assert "Bearer [REDACTED]" in err_text
