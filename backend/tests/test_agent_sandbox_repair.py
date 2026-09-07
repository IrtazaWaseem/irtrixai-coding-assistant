import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import docker
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agent.graph import build_agent_graph
from app.agent.nodes import (
    set_execution_service,
    set_llm_gateway,
)
from app.agent.state import create_initial_state
from app.schemas.agent_contracts import (
    CoderOutput,
    DebuggerOutput,
    PlannerOutput,
    ReviewerOutput,
)
from app.services.execution_service import ExecutionService
from app.services.llm.gateway import LLMGateway
from app.tools.base import ToolResult


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
):
    """Helper creating a ToolResult matching ExecutionService.execute return contract."""
    res = ToolResult(
        tool_name="execution_service",
        success=success,
        output=stdout if success else (stdout or stderr),
        error=stderr if not success else None,
        metadata={
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "command": command or ["pytest"],
            "duration": 0.5,
        },
    )
    setattr(res, "exit_code", exit_code)
    setattr(res, "stdout", stdout)
    setattr(res, "stderr", stderr)
    return res


@pytest.mark.asyncio
async def test_test_runner_real_passing_command_produces_success(tmp_path: Path):
    """Proves test_runner produces success=True, is_stub=False, exit_code=0 with real ExecutionService."""
    from app.agent.nodes import test_runner

    mock_exec = MagicMock()
    mock_exec.execute.return_value = make_mock_exec_result(
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


@pytest.mark.asyncio
async def test_test_runner_failing_command_produces_failure(tmp_path: Path):
    """Proves test_runner produces success=False, is_stub=False on test assertion failure."""
    from app.agent.nodes import test_runner

    mock_exec = MagicMock()
    mock_exec.execute.return_value = make_mock_exec_result(
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
    (tmp_path / "app.py").write_text("def run(): return 1\n", encoding="utf-8")
    init_test_git_repo(tmp_path)

    mock_exec = MagicMock()
    mock_exec.execute.return_value = make_mock_exec_result(
        success=False,
        exit_code=1,
        stdout="FAILED test_app.py - assert 1 == 2\n",
        stderr="",
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
                patch="--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-def run(): return 1\n+def run(): return 2\n",
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

    set_llm_gateway(None)
    set_execution_service(None)


@pytest.mark.asyncio
async def test_repair_count_governance_and_max_exhaustion(tmp_path: Path):
    """Proves that repair loop terminates as failed after exactly 3 failed attempts."""
    # Write file BEFORE git repo initialization so patch hunk context matches
    target = tmp_path / "flaky.py"
    target.write_text("x = 0\n", encoding="utf-8")
    init_test_git_repo(tmp_path)

    mock_exec = MagicMock()
    mock_exec.execute.return_value = make_mock_exec_result(
        success=False,
        exit_code=1,
        stdout="FAILED assertion error\n",
        stderr="",
        command=["pytest"],
    )

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(
                summary="Plan", steps=["Step"], files_expected=["flaky.py"]
            )
        if response_schema is CoderOutput:
            return CoderOutput(
                summary="Try fix",
                patch="--- a/flaky.py\n+++ b/flaky.py\n@@ -1 +1 @@\n-x = 0\n+x = 1\n",
                files_changed=["flaky.py"],
            )
        if response_schema is DebuggerOutput:
            return DebuggerOutput(
                diagnosis="Persistent bug",
                proposed_fix="Retry",
                files_to_change=["flaky.py"],
            )
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)
    set_execution_service(mock_exec)

    thread_id = "th-exhaust-repair"
    config = {"configurable": {"thread_id": thread_id}}
    graph = build_agent_graph()

    await graph.ainvoke(
        create_initial_state("task-ex", str(tmp_path), thread_id), config=config
    )
    assert (await graph.aget_state(config)).next == ("approval_gate",)

    # Approve Initial attempt -> fails -> repair 1
    await graph.ainvoke(Command(resume={"approved": True}), config=config)
    snap1 = await graph.aget_state(config)
    assert snap1.next == ("approval_gate",)
    assert snap1.values["repair_count"] == 1

    # Approve Repair 1 -> fails -> repair 2
    await graph.ainvoke(Command(resume={"approved": True}), config=config)
    snap2 = await graph.aget_state(config)
    assert snap2.next == ("approval_gate",)
    assert snap2.values["repair_count"] == 2

    # Approve Repair 2 -> fails -> repair 3
    await graph.ainvoke(Command(resume={"approved": True}), config=config)
    snap3 = await graph.aget_state(config)
    assert snap3.next == ("approval_gate",)
    assert snap3.values["repair_count"] == 3

    # Approve Repair 3 -> fails -> EXHAUSTED (routes to finalize)
    await graph.ainvoke(Command(resume={"approved": True}), config=config)
    final_snap = await graph.aget_state(config)

    assert final_snap.next == ()
    assert final_snap.values["final_result"] is not None
    assert final_snap.values["final_result"].status == "failed"

    set_llm_gateway(None)
    set_execution_service(None)


@pytest.mark.asyncio
async def test_repair_patch_requires_hitl_before_mutation(tmp_path: Path):
    """Proves that a repair patch cannot mutate the workspace before operator approval."""
    target = tmp_path / "guard.py"
    initial_content = "VAL = 100\n"
    target.write_text(initial_content, encoding="utf-8")
    init_test_git_repo(tmp_path)

    mock_exec = MagicMock()
    mock_exec.execute.return_value = make_mock_exec_result(
        success=False,
        exit_code=1,
        stdout="FAILED assert VAL == 200\n",
        stderr="",
        command=["pytest"],
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
                summary="Repair patch",
                patch=repair_patch,
                files_changed=["guard.py"],
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

    thread_id = "th-hitl-guard"
    config = {"configurable": {"thread_id": thread_id}}
    graph = build_agent_graph()

    await graph.ainvoke(
        create_initial_state("task-hg", str(tmp_path), thread_id), config=config
    )
    await graph.ainvoke(Command(resume={"approved": True}), config=config)

    # File on disk MUST STILL be initial_content because repair patch is pending approval
    assert target.read_text(encoding="utf-8") == initial_content
    snap = await graph.aget_state(config)
    assert snap.next == ("approval_gate",)
    assert snap.values["pending_patch"] == repair_patch

    set_llm_gateway(None)
    set_execution_service(None)


@pytest.mark.asyncio
async def test_repair_patch_rejection_causes_zero_mutation(tmp_path: Path):
    """Proves that rejecting a repair patch mutates zero files and aborts cleanly."""
    target = tmp_path / "reject_me.py"
    initial_code = "SAFE = True\n"
    target.write_text(initial_code, encoding="utf-8")
    init_test_git_repo(tmp_path)

    mock_exec = MagicMock()
    mock_exec.execute.return_value = make_mock_exec_result(
        success=False,
        exit_code=1,
        stdout="FAILED\n",
        stderr="",
        command=["pytest"],
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
                patch="--- a/reject_me.py\n+++ b/reject_me.py\n@@ -1 +1 @@\n-SAFE = True\n+SAFE = False\n",
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

    thread_id = "th-reject-repair"
    config = {"configurable": {"thread_id": thread_id}}
    graph = build_agent_graph()

    await graph.ainvoke(
        create_initial_state("task-rr", str(tmp_path), thread_id), config=config
    )
    await graph.ainvoke(Command(resume={"approved": True}), config=config)
    await graph.ainvoke(Command(resume={"approved": False}), config=config)

    final_snap = await graph.aget_state(config)
    assert final_snap.next == ()
    assert final_snap.values["final_result"].status == "aborted"
    assert target.read_text(encoding="utf-8") == initial_code

    set_llm_gateway(None)
    set_execution_service(None)


@pytest.mark.asyncio
async def test_repair_cycle_with_checkpoint_resume(tmp_path: Path):
    """Proves repair cycle state and approval survive across graph instances with shared checkpointer."""
    target = tmp_path / "persisted.py"
    target.write_text("x = 1\n", encoding="utf-8")
    init_test_git_repo(tmp_path)

    exec_call_count = 0

    def mock_exec_fn(command, workspace_path, **kwargs):
        nonlocal exec_call_count
        exec_call_count += 1
        if exec_call_count == 1:
            return make_mock_exec_result(
                success=False,
                exit_code=1,
                stdout="FAILED\n",
                stderr="",
                command=["pytest"],
            )
        return make_mock_exec_result(
            success=True,
            exit_code=0,
            stdout="1 passed\n",
            stderr="",
            command=["pytest"],
        )

    mock_exec = MagicMock()
    mock_exec.execute.side_effect = mock_exec_fn

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(
                summary="Plan", steps=["S"], files_expected=["persisted.py"]
            )
        if response_schema is CoderOutput:
            return CoderOutput(
                summary="Patch",
                patch="--- a/persisted.py\n+++ b/persisted.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n",
                files_changed=["persisted.py"],
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

    thread_id = "th-persisted-repair"
    config = {"configurable": {"thread_id": thread_id}}
    shared_saver = MemorySaver()

    graph_a = build_agent_graph(checkpointer=shared_saver)
    await graph_a.ainvoke(
        create_initial_state("task-pr", str(tmp_path), thread_id), config=config
    )
    await graph_a.ainvoke(Command(resume={"approved": True}), config=config)
    assert (await graph_a.aget_state(config)).next == ("approval_gate",)
    assert (await graph_a.aget_state(config)).values["repair_count"] == 1
    del graph_a

    graph_b = build_agent_graph(checkpointer=shared_saver)
    await graph_b.ainvoke(Command(resume={"approved": True}), config=config)

    final_snap = await graph_b.aget_state(config)
    assert final_snap.next == ()
    assert final_snap.values["final_result"].status == "completed"
    assert target.read_text(encoding="utf-8") == "x = 2\n"

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

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(
                summary="Plan", steps=["Fix solve()"], files_expected=["solution.py"]
            )
        if response_schema is CoderOutput:
            return CoderOutput(
                summary="Fix solution",
                patch="--- a/solution.py\n+++ b/solution.py\n@@ -1 +1 @@\n-def solve(): return 1\n+def solve(): return 2\n",
                files_changed=["solution.py"],
            )
        if response_schema is DebuggerOutput:
            return DebuggerOutput(
                diagnosis="Assert 1 == 2",
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

    set_llm_gateway(None)
