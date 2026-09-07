import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import docker
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agent.graph import build_agent_graph
from app.agent.nodes import set_execution_service, set_llm_gateway
from app.agent.state import create_initial_state
from app.schemas.agent_contracts import (
    CoderOutput,
    DebuggerOutput,
    PlannerOutput,
    ReviewerOutput,
)
from app.services.llm.gateway import LLMGateway


def is_docker_daemon_accessible() -> bool:
    """Checks if Docker daemon is responsive."""
    try:
        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


def init_test_git_repo(repo_path: Path) -> None:
    """Initializes local git repository in test directory with baseline commit."""
    subprocess.run(["git", "init"], cwd=str(repo_path), capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.name", "TestRunner"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@irtrixai.internal"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "add", "."], cwd=str(repo_path), capture_output=True, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )


def make_mock_exec_result(
    success: bool,
    exit_code: int,
    stdout: str,
    stderr: str = "",
    command: list[str] | None = None,
) -> dict:
    """Return the exact dictionary shape produced by ExecutionService.execute_in_sandbox()."""
    return {
        "command": " ".join(command or ["pytest"]),
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "truncated": False,
        "duration_seconds": 0.5,
    }


@pytest.mark.asyncio
async def test_test_runner_real_passing_command_produces_success(tmp_path: Path):
    """Proves test_runner produces success=True, is_stub=False and exit_code=0."""
    from app.agent.nodes import test_runner

    mock_exec = MagicMock()
    mock_exec.execute_in_sandbox.return_value = make_mock_exec_result(
        success=True,
        exit_code=0,
        stdout="================ 1 passed in 0.05s ================\n",
        stderr="",
        command=["pytest"],
    )

    state = create_initial_state("task-tr-1", str(tmp_path), "th-tr-1")
    state["test_command"] = "pytest"

    res = await test_runner(
        state, config={"configurable": {"execution_service": mock_exec}}
    )

    tr = res["test_result"]
    assert tr["success"] is True
    assert tr["is_stub"] is False
    assert tr["exit_code"] == 0
    assert "1 passed" in tr["stdout"]
    assert tr["command"] == "pytest"
    mock_exec.execute_in_sandbox.assert_called_once()


@pytest.mark.asyncio
async def test_test_runner_failing_command_produces_failure(tmp_path: Path):
    """Proves test_runner produces success=False on test assertion failure."""
    from app.agent.nodes import test_runner

    mock_exec = MagicMock()
    mock_exec.execute_in_sandbox.return_value = make_mock_exec_result(
        success=False,
        exit_code=1,
        stdout="FAILED test_calc.py::test_add - assert 2 == 3\n",
        stderr="",
        command=["pytest"],
    )

    state = create_initial_state("task-tr-2", str(tmp_path), "th-tr-2")
    state["test_command"] = "pytest"

    res = await test_runner(
        state, config={"configurable": {"execution_service": mock_exec}}
    )

    tr = res["test_result"]
    assert tr["success"] is False
    assert tr["is_stub"] is False
    assert tr["exit_code"] == 1
    assert "FAILED" in tr["output"]
    mock_exec.execute_in_sandbox.assert_called_once()


@pytest.mark.asyncio
async def test_fake_stub_execution_cannot_cause_completion(tmp_path: Path):
    """Proves that a stub execution result cannot advance a task to completed status."""
    from app.agent.nodes import finalize

    state = create_initial_state("task-tr-3", str(tmp_path), "th-tr-3")
    state["approval"] = True
    state["test_result"] = {
        "success": True,
        "exit_code": 0,
        "output": "stub output",
        "is_stub": True,
    }
    state["review_summary"] = ReviewerOutput(
        verdict="approved",
        summary="Looks good",
        issues=[],
        security_concerns=[],
        required_changes=[],
    )

    res = await finalize(state)
    assert res["final_result"].status == "failed"
    assert "stub" in res["final_result"].summary.lower()


@pytest.mark.asyncio
async def test_repair_loop_routes_debugger_to_coder_to_hitl(tmp_path: Path):
    """Proves test failure routes to debugger -> coder -> approval_gate with approval=None."""
    target = tmp_path / "app.py"
    target.write_text("def run(): return 1\n", encoding="utf-8")
    init_test_git_repo(tmp_path)

    mock_exec = MagicMock()
    mock_exec.execute_in_sandbox.return_value = make_mock_exec_result(
        success=False,
        exit_code=1,
        stdout="FAILED test_app.py - assert 1 == 2\n",
        command=["pytest"],
    )

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(
                summary="Plan fix", steps=["Update return"], files_expected=["app.py"]
            )
        if response_schema is CoderOutput:
            return CoderOutput(
                summary="Fix return value",
                patch=(
                    "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n"
                    "-def run(): return 1\n+def run(): return 2\n"
                ),
                files_changed=["app.py"],
            )
        if response_schema is DebuggerOutput:
            return DebuggerOutput(
                diagnosis="Assertion mismatch",
                proposed_fix="Change return to 2",
                files_to_change=["app.py"],
            )
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)
    set_execution_service(mock_exec)

    try:
        thread_id = "th-repair-flow"
        config = {"configurable": {"thread_id": thread_id}}
        graph = build_agent_graph()

        state = create_initial_state("task-rep-1", str(tmp_path), thread_id)
        await graph.ainvoke(state, config=config)

        snap = await graph.aget_state(config)
        assert snap.next == ("approval_gate",)
        assert snap.values["repair_count"] == 0

        await graph.ainvoke(Command(resume={"approved": True}), config=config)

        snap2 = await graph.aget_state(config)
        assert snap2.next == ("approval_gate",)
        assert snap2.values["repair_count"] == 1
        assert snap2.values["approval"] is None
        assert snap2.values["debugger_output"] is not None
        assert target.read_text(encoding="utf-8") == "def run(): return 2\n"
    finally:
        set_llm_gateway(None)
        set_execution_service(None)


@pytest.mark.asyncio
async def test_repair_count_governance_and_max_exhaustion(tmp_path: Path):
    """Proves that repair loop terminates after exactly 3 failed repair attempts."""
    target = tmp_path / "flaky.py"
    target.write_text("x = 0\n", encoding="utf-8")
    init_test_git_repo(tmp_path)

    mock_exec = MagicMock()
    mock_exec.execute_in_sandbox.return_value = make_mock_exec_result(
        success=False,
        exit_code=1,
        stdout="FAILED assertion error\n",
        command=["pytest"],
    )

    mock_gw = MagicMock(spec=LLMGateway)
    coder_calls = 0

    async def mock_structured(prompt, response_schema, **kwargs):
        nonlocal coder_calls
        if response_schema is PlannerOutput:
            return PlannerOutput(
                summary="Plan", steps=["Step"], files_expected=["flaky.py"]
            )
        if response_schema is CoderOutput:
            coder_calls += 1
            return CoderOutput(
                summary=f"Try fix {coder_calls}",
                patch=(
                    f"--- a/flaky.py\n+++ b/flaky.py\n@@ -1 +1 @@\n"
                    f"-x = {coder_calls - 1}\n+x = {coder_calls}\n"
                ),
                files_changed=["flaky.py"],
            )
        if response_schema is DebuggerOutput:
            return DebuggerOutput(
                diagnosis="Persistent bug",
                proposed_fix="Retry with another targeted change",
                files_to_change=["flaky.py"],
            )
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)
    set_execution_service(mock_exec)

    try:
        thread_id = "th-exhaust-repair"
        config = {"configurable": {"thread_id": thread_id}}
        graph = build_agent_graph()

        await graph.ainvoke(
            create_initial_state("task-ex", str(tmp_path), thread_id), config=config
        )

        for expected_repair in (1, 2, 3):
            await graph.ainvoke(Command(resume={"approved": True}), config=config)
            snap = await graph.aget_state(config)
            assert snap.next == ("approval_gate",)
            assert snap.values["repair_count"] == expected_repair

        await graph.ainvoke(Command(resume={"approved": True}), config=config)
        final_snap = await graph.aget_state(config)

        assert final_snap.next == ()
        assert final_snap.values["final_result"] is not None
        assert final_snap.values["final_result"].status == "failed"
        assert coder_calls == 4  # initial proposal + exactly 3 repair proposals
    finally:
        set_llm_gateway(None)
        set_execution_service(None)


@pytest.mark.asyncio
async def test_repair_patch_requires_hitl_before_mutation(tmp_path: Path):
    """Proves that a repair patch cannot mutate workspace before operator approval."""
    target = tmp_path / "guard.py"
    initial_content = "VAL = 100\n"
    target.write_text(initial_content, encoding="utf-8")
    init_test_git_repo(tmp_path)

    mock_exec = MagicMock()
    mock_exec.execute_in_sandbox.return_value = make_mock_exec_result(
        success=False, exit_code=1, stdout="FAILED assert VAL == 200\n"
    )

    repair_patch = (
        "--- a/guard.py\n+++ b/guard.py\n@@ -1 +1 @@\n-VAL = 100\n+VAL = 200\n"
    )
    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(
                summary="Plan", steps=["Step"], files_expected=["guard.py"]
            )
        if response_schema is CoderOutput:
            return CoderOutput(
                summary="Repair patch", patch=repair_patch, files_changed=["guard.py"]
            )
        if response_schema is DebuggerOutput:
            return DebuggerOutput(
                diagnosis="Incorrect VAL",
                proposed_fix="Set to 200",
                files_to_change=["guard.py"],
            )
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)
    set_execution_service(mock_exec)

    try:
        thread_id = "th-hitl-guard"
        config = {"configurable": {"thread_id": thread_id}}
        graph = build_agent_graph()

        await graph.ainvoke(
            create_initial_state("task-hg", str(tmp_path), thread_id), config=config
        )
        await graph.ainvoke(Command(resume={"approved": True}), config=config)

        assert target.read_text(encoding="utf-8") == "VAL = 200\n"
        snap = await graph.aget_state(config)
        assert snap.next == ("approval_gate",)
        assert snap.values["pending_patch"] == repair_patch

    finally:
        set_llm_gateway(None)
        set_execution_service(None)


@pytest.mark.asyncio
async def test_repair_patch_rejection_causes_zero_mutation(tmp_path: Path):
    """Proves rejecting a repair patch mutates zero files and aborts cleanly."""
    target = tmp_path / "reject_me.py"
    initial_code = "SAFE = True\n"
    target.write_text(initial_code, encoding="utf-8")
    init_test_git_repo(tmp_path)

    mock_exec = MagicMock()
    mock_exec.execute_in_sandbox.return_value = make_mock_exec_result(
        success=False, exit_code=1, stdout="FAILED\n"
    )

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(
                summary="P", steps=["S"], files_expected=["reject_me.py"]
            )
        if response_schema is CoderOutput:
            return CoderOutput(
                summary="C",
                patch=(
                    "--- a/reject_me.py\n+++ b/reject_me.py\n@@ -1 +1 @@\n"
                    "-SAFE = True\n+SAFE = False\n"
                ),
                files_changed=["reject_me.py"],
            )
        if response_schema is DebuggerOutput:
            return DebuggerOutput(
                diagnosis="D", proposed_fix="F", files_to_change=["reject_me.py"]
            )
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)
    set_execution_service(mock_exec)

    try:
        thread_id = "th-reject-repair"
        config = {"configurable": {"thread_id": thread_id}}
        graph = build_agent_graph()

        await graph.ainvoke(
            create_initial_state("task-rr", str(tmp_path), thread_id), config=config
        )
        await graph.ainvoke(Command(resume={"approved": True}), config=config)
        # First attempt fails and produces the repair proposal.
        assert (await graph.aget_state(config)).next == ("approval_gate",)

        await graph.ainvoke(Command(resume={"approved": False}), config=config)

        final_snap = await graph.aget_state(config)
        assert final_snap.next == ()
        assert final_snap.values["final_result"].status == "aborted"
        assert target.read_text(encoding="utf-8") == "SAFE = False\n"
    finally:
        set_llm_gateway(None)
        set_execution_service(None)


@pytest.mark.asyncio
async def test_repair_cycle_with_checkpoint_resume(tmp_path: Path):
    """Proves repair cycle state survives across graph instances with shared checkpointer."""
    target = tmp_path / "persisted.py"
    target.write_text("x = 1\n", encoding="utf-8")
    init_test_git_repo(tmp_path)

    exec_call_count = 0

    def mock_exec_fn(command, workspace_path, **kwargs):
        nonlocal exec_call_count
        exec_call_count += 1
        if exec_call_count == 1:
            return make_mock_exec_result(
                success=False, exit_code=1, stdout="FAILED\n", command=["pytest"]
            )
        return make_mock_exec_result(
            success=True, exit_code=0, stdout="1 passed\n", command=["pytest"]
        )

    mock_exec = MagicMock()
    mock_exec.execute_in_sandbox.side_effect = mock_exec_fn

    mock_gw = MagicMock(spec=LLMGateway)
    coder_calls = 0

    async def mock_structured(prompt, response_schema, **kwargs):
        nonlocal coder_calls
        if response_schema is PlannerOutput:
            return PlannerOutput(
                summary="Plan", steps=["S"], files_expected=["persisted.py"]
            )
        if response_schema is CoderOutput:
            coder_calls += 1
            if coder_calls == 1:
                patch = (
                    "--- a/persisted.py\n+++ b/persisted.py\n@@ -1 +1 @@\n"
                    "-x = 1\n+x = 2\n"
                )
            else:
                patch = (
                    "--- a/persisted.py\n+++ b/persisted.py\n@@ -1 +1 @@\n"
                    "-x = 2\n+x = 3\n"
                )
            return CoderOutput(
                summary="Patch", patch=patch, files_changed=["persisted.py"]
            )
        if response_schema is DebuggerOutput:
            return DebuggerOutput(
                diagnosis="Diagnosis",
                proposed_fix="Fix",
                files_to_change=["persisted.py"],
            )
        if response_schema is ReviewerOutput:
            return ReviewerOutput(
                verdict="approved",
                summary="Verified",
                issues=[],
                security_concerns=[],
                required_changes=[],
            )
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)
    set_execution_service(mock_exec)

    try:
        thread_id = "th-persisted-repair"
        config = {"configurable": {"thread_id": thread_id}}
        shared_saver = MemorySaver()

        graph_a = build_agent_graph(checkpointer=shared_saver)
        await graph_a.ainvoke(
            create_initial_state("task-pr", str(tmp_path), thread_id), config=config
        )
        await graph_a.ainvoke(Command(resume={"approved": True}), config=config)

        snap_a = await graph_a.aget_state(config)
        assert snap_a.next == ("approval_gate",)
        assert snap_a.values["repair_count"] == 1
        assert snap_a.values["test_result"]["success"] is False
        assert target.read_text(encoding="utf-8") == "x = 2\n"
        del graph_a

        graph_b = build_agent_graph(checkpointer=shared_saver)
        await graph_b.ainvoke(Command(resume={"approved": True}), config=config)

        final_snap = await graph_b.aget_state(config)
        assert final_snap.next == ()
        assert final_snap.values["final_result"].status == "completed"
        assert final_snap.values["test_result"]["success"] is True
        assert target.read_text(encoding="utf-8") == "x = 3\n"
    finally:
        set_llm_gateway(None)
        set_execution_service(None)


@pytest.mark.asyncio
async def test_live_docker_end_to_end_repair_loop(tmp_path: Path):
    """Executes live Docker sandbox through the repair loop if Docker daemon is responsive."""
    if not is_docker_daemon_accessible():
        pytest.skip("Docker daemon is not accessible.")

    (tmp_path / "solution.py").write_text("def solve(): return 1\n", encoding="utf-8")
    (tmp_path / "test_solution.py").write_text(
        "from solution import solve\ndef test_solve(): assert solve() == 2\n",
        encoding="utf-8",
    )
    init_test_git_repo(tmp_path)

    mock_gw = MagicMock(spec=LLMGateway)
    coder_calls = 0

    async def mock_structured(prompt, response_schema, **kwargs):
        nonlocal coder_calls
        if response_schema is PlannerOutput:
            return PlannerOutput(
                summary="Plan", steps=["Fix solve()"], files_expected=["solution.py"]
            )
        if response_schema is CoderOutput:
            coder_calls += 1
            if coder_calls == 1:
                patch = (
                    "--- a/solution.py\n+++ b/solution.py\n@@ -1 +1 @@\n"
                    "-def solve(): return 1\n+def solve(): return 3\n"
                )
            else:
                patch = (
                    "--- a/solution.py\n+++ b/solution.py\n@@ -1 +1 @@\n"
                    "-def solve(): return 3\n+def solve(): return 2\n"
                )
            return CoderOutput(
                summary="Fix solution", patch=patch, files_changed=["solution.py"]
            )
        if response_schema is DebuggerOutput:
            return DebuggerOutput(
                diagnosis="Assert mismatch",
                proposed_fix="Return 2",
                files_to_change=["solution.py"],
            )
        if response_schema is ReviewerOutput:
            return ReviewerOutput(
                verdict="approved",
                summary="Solution verified in Docker",
                issues=[],
                security_concerns=[],
                required_changes=[],
            )
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)

    try:
        thread_id = "th-live-docker-repair"
        config = {"configurable": {"thread_id": thread_id}}
        graph = build_agent_graph()

        state = create_initial_state("task-live", str(tmp_path), thread_id)
        state["test_command"] = "pytest"
        await graph.ainvoke(state, config=config)
        await graph.ainvoke(Command(resume={"approved": True}), config=config)

        snap = await graph.aget_state(config)
        assert snap.next == ("approval_gate",)
        assert snap.values["repair_count"] == 1
        assert snap.values["test_result"]["is_stub"] is False
        assert snap.values["test_result"]["exit_code"] == 1

        await graph.ainvoke(Command(resume={"approved": True}), config=config)

        final_snap = await graph.aget_state(config)
        assert final_snap.next == ()
        assert final_snap.values["final_result"].status == "completed"
        assert final_snap.values["test_result"]["exit_code"] == 0
        assert final_snap.values["test_result"]["success"] is True
        assert (tmp_path / "solution.py").read_text(
            encoding="utf-8"
        ) == "def solve(): return 2\n"
    finally:
        set_llm_gateway(None)
