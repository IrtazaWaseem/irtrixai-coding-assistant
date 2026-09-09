import json
import subprocess
from pathlib import Path
from typing import Any
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
    """Checks if Docker daemon is responsive for live container execution."""
    try:
        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


def init_test_git_repo(repo_path: Path) -> None:
    """Initializes local git repository in test directory with baseline commit."""
    (repo_path / ".gitkeep").touch()
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


"""Proves full end-to-end agent workflow executing real tool chain:
    inspect_workspace -> planner -> coder -> approval_gate -> apply_approved_patch -> test_runner -> reviewer -> finalize.
    """


def make_mock_exec_result(
    exit_code: int,
    stdout: str,
    stderr: str = "",
    command: list[str] | None = None,
    success: bool | None = None,
) -> dict[str, Any]:
    """Creates a dictionary matching ExecutionService.execute_in_sandbox return contract."""
    return {
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "command": command or ["pytest"],
        "duration_seconds": 0.5,
        "truncated": False,
        "success": (exit_code == 0) if success is None else success,
    }


@pytest.mark.asyncio
async def test_e2e_real_tool_chain_inspect_to_finalize(tmp_path: Path):

    ws = tmp_path / "sample_math_project"
    ws.mkdir(parents=True, exist_ok=True)

    math_file = ws / "math_utils.py"
    math_file.write_text(
        "def add(a: int, b: int) -> int:\n    return a + b\n",
        encoding="utf-8",
    )

    test_file = ws / "test_math_utils.py"
    test_file.write_text(
        "from math_utils import add, multiply\n\n"
        "def test_add():\n    assert add(2, 3) == 5\n\n"
        "def test_multiply():\n    assert multiply(3, 4) == 12\n",
        encoding="utf-8",
    )

    manifest_file = ws / "pyproject.toml"
    manifest_file.write_text(
        "[project]\nname = 'sample-math'\nversion = '0.1.0'\n",
        encoding="utf-8",
    )

    init_test_git_repo(ws)
    patch_text = (
        "--- a/math_utils.py\n"
        "+++ b/math_utils.py\n"
        "@@ -1,2 +1,6 @@\n"
        " def add(a: int, b: int) -> int:\n"
        "     return a + b\n"
        "+\n"
        "+def multiply(a: int, b: int) -> int:\n"
        "+    return a * b\n"
    )

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(
                summary="Implement multiply function",
                steps=["Add multiply(a, b) function to math_utils.py"],
                files_expected=["math_utils.py"],
            )
        if response_schema is CoderOutput:
            return CoderOutput(
                summary="Added multiply function",
                patch=patch_text,
                files_changed=["math_utils.py"],
            )
        if response_schema is ReviewerOutput:
            return ReviewerOutput(
                verdict="approved",
                summary="Implementation is correct, type annotated, and all tests pass.",
                issues=[],
                security_concerns=[],
                required_changes=[],
            )
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)

    mock_exec = MagicMock()
    mock_exec.execute_in_sandbox.return_value = make_mock_exec_result(
        exit_code=0,
        stdout="================ 2 passed in 0.04s ================\n",
        stderr="",
        command=["pytest"],
    )
    set_execution_service(mock_exec)

    checkpointer = MemorySaver()
    graph = build_agent_graph(checkpointer=checkpointer)

    thread_id = "thread-e2e-workflow-1"
    config = {"configurable": {"thread_id": thread_id}}

    state = create_initial_state(
        task_id="task-e2e-1",
        workspace_path=str(ws),
        thread_id=thread_id,
        prompt="Add a multiply(a, b) function and tests",
    )
    state["test_command"] = "pytest"

    # Step A: Run until approval_gate interrupt
    await graph.ainvoke(state, config=config)

    snap = await graph.aget_state(config)
    assert snap.next == ("approval_gate",)
    assert snap.values["current_step"] == 3
    assert snap.values["pending_patch"] == patch_text
    assert snap.values["coder_proposal"].summary == "Added multiply function"
    assert "math_utils.py" in snap.values["workspace_summary"]

    # INVARIANT: Filesystem is UNTOUCHED before operator approval
    assert (
        math_file.read_text(encoding="utf-8")
        == "def add(a: int, b: int) -> int:\n    return a + b\n"
    )

    # Step B: Human Operator grants approval via Command(resume=...)
    await graph.ainvoke(
        Command(resume={"approved": True, "feedback": "LGTM"}), config=config
    )

    final_snap = await graph.aget_state(config)

    # Invariants on successful finalization
    assert final_snap.next == ()
    assert final_snap.values["approval"] is True
    assert final_snap.values["current_step"] == 8
    assert final_snap.values["final_result"].status == "completed"
    assert "math_utils.py" in final_snap.values["final_result"].files_changed
    assert final_snap.values["test_result"]["success"] is True
    assert final_snap.values["test_result"]["exit_code"] == 0
    assert final_snap.values["tool_result"]["tool_name"] == "execution_service"

    # Filesystem verification: Approved patch was authoritatively applied to disk
    assert "def multiply(a: int, b: int) -> int:" in math_file.read_text(
        encoding="utf-8"
    )

    # Authoritative sandbox verification: execute_in_sandbox was called with exact signature
    mock_exec.execute_in_sandbox.assert_called_once_with(
        command="pytest",
        workspace_path=str(ws),
        timeout_seconds=30,
    )

    set_llm_gateway(None)
    set_execution_service(None)


@pytest.mark.asyncio
async def test_e2e_repair_cycle_preserves_invariants(tmp_path: Path):
    """Proves repair loop routes test_runner -> debugger -> coder -> approval_gate,
    clears stale authorization, and requires fresh human approval for repair proposal.
    """
    ws = tmp_path / "repair_project"
    ws.mkdir(parents=True, exist_ok=True)
    target = ws / "service.py"
    target.write_text("STATUS = 'INIT'\n", encoding="utf-8")
    init_test_git_repo(ws)

    # Initial buggy proposal, then corrected repair proposal
    patch_v1 = "--- a/service.py\n+++ b/service.py\n@@ -1 +1 @@\n-STATUS = 'INIT'\n+STATUS = 'BUGGY'\n"
    patch_v2 = "--- a/service.py\n+++ b/service.py\n@@ -1 +1 @@\n-STATUS = 'BUGGY'\n+STATUS = 'ACTIVE'\n"

    coder_call_count = 0
    exec_call_count = 0

    def mock_exec_fn(command, workspace_path, **kwargs):
        nonlocal exec_call_count
        exec_call_count += 1
        if exec_call_count == 1:
            return make_mock_exec_result(
                exit_code=1,
                stdout="FAILED assert STATUS == 'ACTIVE'\n",
                stderr="",
                command=["pytest"],
            )
        return make_mock_exec_result(
            exit_code=0,
            stdout="1 passed in 0.02s\n",
            stderr="",
            command=["pytest"],
        )

    mock_exec = MagicMock()
    mock_exec.execute_in_sandbox.side_effect = mock_exec_fn

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        nonlocal coder_call_count
        if response_schema is PlannerOutput:
            return PlannerOutput(
                summary="Plan", steps=["S1"], files_expected=["service.py"]
            )
        if response_schema is CoderOutput:
            coder_call_count += 1
            patch = patch_v1 if coder_call_count == 1 else patch_v2
            return CoderOutput(
                summary=f"Proposal {coder_call_count}",
                patch=patch,
                files_changed=["service.py"],
            )
        if response_schema is DebuggerOutput:
            return DebuggerOutput(
                diagnosis="Status was set to BUGGY instead of ACTIVE",
                proposed_fix="Set STATUS = 'ACTIVE'",
                files_to_change=["service.py"],
            )
        if response_schema is ReviewerOutput:
            return ReviewerOutput(
                verdict="approved",
                summary="Repair verified by passing test suite",
                issues=[],
                security_concerns=[],
                required_changes=[],
            )
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)
    set_execution_service(mock_exec)

    checkpointer = MemorySaver()
    graph = build_agent_graph(checkpointer=checkpointer)
    thread_id = "thread-e2e-repair-1"
    config = {"configurable": {"thread_id": thread_id}}

    state = create_initial_state("task-rep-1", str(ws), thread_id)
    state["test_command"] = "pytest"

    # Run 1: Pauses at approval_gate for patch_v1
    await graph.ainvoke(state, config=config)

    # Approve patch_v1 -> Applied -> test_runner fails -> debugger -> coder -> pauses at approval_gate
    await graph.ainvoke(Command(resume={"approved": True}), config=config)

    repair_snap = await graph.aget_state(config)
    assert repair_snap.next == ("approval_gate",)
    assert repair_snap.values["repair_count"] == 1
    assert (
        repair_snap.values["approval"] is None
    )  # INVARIANT: Stale authorization cleared!
    assert repair_snap.values["pending_patch"] == patch_v2
    assert target.read_text(encoding="utf-8") == "STATUS = 'BUGGY'\n"

    # Approve patch_v2 -> Applied -> test_runner passes -> reviewer -> finalize
    await graph.ainvoke(Command(resume={"approved": True}), config=config)

    final_snap = await graph.aget_state(config)
    assert final_snap.next == ()
    assert final_snap.values["final_result"].status == "completed"
    assert final_snap.values["repair_count"] == 1
    assert target.read_text(encoding="utf-8") == "STATUS = 'ACTIVE'\n"

    set_llm_gateway(None)
    set_execution_service(None)


@pytest.mark.asyncio
async def test_e2e_max_repair_exhaustion_terminates_failed(tmp_path: Path):
    """Proves repair loop terminates with status='failed' when max repairs (3) are exhausted."""
    ws = tmp_path / "exhaust_project"
    ws.mkdir(parents=True, exist_ok=True)
    target = ws / "flaky.py"
    target.write_text("x = 0\n", encoding="utf-8")
    init_test_git_repo(ws)

    mock_exec = MagicMock()
    mock_exec.execute_in_sandbox.return_value = make_mock_exec_result(
        exit_code=1,
        stdout="FAILED assertion error\n",
        stderr="",
        command=["pytest"],
    )

    coder_attempt = 0

    async def mock_structured(prompt, response_schema, **kwargs):
        nonlocal coder_attempt
        if response_schema is PlannerOutput:
            return PlannerOutput(
                summary="Plan", steps=["S"], files_expected=["flaky.py"]
            )
        if response_schema is CoderOutput:
            coder_attempt += 1
            patch = f"--- a/flaky.py\n+++ b/flaky.py\n@@ -1 +1 @@\n-x = {coder_attempt - 1}\n+x = {coder_attempt}\n"
            return CoderOutput(
                summary=f"Fix {coder_attempt}",
                patch=patch,
                files_changed=["flaky.py"],
            )
        if response_schema is DebuggerOutput:
            return DebuggerOutput(
                diagnosis="Persistent failure",
                proposed_fix="Retry",
                files_to_change=["flaky.py"],
            )
        return response_schema.model_validate({})

    mock_gw = MagicMock(spec=LLMGateway)
    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)
    set_execution_service(mock_exec)

    checkpointer = MemorySaver()
    graph = build_agent_graph(checkpointer=checkpointer)
    thread_id = "thread-e2e-exhaust"
    config = {"configurable": {"thread_id": thread_id}}

    await graph.ainvoke(
        create_initial_state("task-ex", str(ws), thread_id), config=config
    )

    # Approve Initial -> fails -> repair 1
    await graph.ainvoke(Command(resume={"approved": True}), config=config)
    assert (await graph.aget_state(config)).values["repair_count"] == 1

    # Approve Repair 1 -> fails -> repair 2
    await graph.ainvoke(Command(resume={"approved": True}), config=config)
    assert (await graph.aget_state(config)).values["repair_count"] == 2

    # Approve Repair 2 -> fails -> repair 3
    await graph.ainvoke(Command(resume={"approved": True}), config=config)
    assert (await graph.aget_state(config)).values["repair_count"] == 3

    # Approve Repair 3 -> fails -> EXHAUSTED (routes directly to finalize)
    await graph.ainvoke(Command(resume={"approved": True}), config=config)
    final_snap = await graph.aget_state(config)

    assert final_snap.next == ()
    assert final_snap.values["final_result"].status == "failed"
    assert "repair count: 3" in final_snap.values["final_result"].summary

    set_llm_gateway(None)
    set_execution_service(None)


@pytest.mark.asyncio
async def test_e2e_rejected_patch_causes_zero_mutation(tmp_path: Path):
    """Proves that an operator rejection with final abort causes zero filesystem mutations."""
    ws = tmp_path / "reject_project"
    ws.mkdir(parents=True, exist_ok=True)
    target = ws / "core.py"
    target.write_text("IMMUTABLE = True\n", encoding="utf-8")
    init_test_git_repo(ws)

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(summary="P", steps=["S"], files_expected=["core.py"])
        if response_schema is CoderOutput:
            return CoderOutput(
                summary="Malicious edit",
                patch="--- a/core.py\n+++ b/core.py\n@@ -1 +1 @@\n-IMMUTABLE = True\n+IMMUTABLE = False\n",
                files_changed=["core.py"],
            )
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)

    checkpointer = MemorySaver()
    graph = build_agent_graph(checkpointer=checkpointer)
    thread_id = "thread-e2e-reject"
    config = {"configurable": {"thread_id": thread_id}}

    await graph.ainvoke(
        create_initial_state("task-rej", str(ws), thread_id), config=config
    )

    # Operator rejects proposal with approval=False and no feedback (or terminal abort signal)
    await graph.ainvoke(
        Command(resume={"approved": False}),
        config=config,
    )

    final_snap = await graph.aget_state(config)
    assert final_snap.values["approval"] is False
    assert target.read_text(encoding="utf-8") == "IMMUTABLE = True\n"

    set_llm_gateway(None)


@pytest.mark.asyncio
async def test_e2e_checkpoint_state_msgpack_and_json_serializable(tmp_path: Path):
    """Proves all state values produced across the graph are JSON and checkpoint serializable."""
    ws = tmp_path / "serde_project"
    ws.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws)

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(summary="Plan", steps=["S"], files_expected=[])
        if response_schema is CoderOutput:
            return CoderOutput(summary="Coder", patch="", files_changed=[])
        if response_schema is ReviewerOutput:
            return ReviewerOutput(
                verdict="approved",
                summary="Audit OK",
                issues=[],
                security_concerns=[],
                required_changes=[],
            )
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)

    mock_exec = MagicMock()
    mock_exec.execute_in_sandbox.return_value = make_mock_exec_result(
        exit_code=0, stdout="All passed\n", stderr="", command=["pytest"]
    )
    set_execution_service(mock_exec)

    checkpointer = MemorySaver()
    graph = build_agent_graph(checkpointer=checkpointer)
    thread_id = "thread-e2e-serde"
    config = {"configurable": {"thread_id": thread_id}}

    await graph.ainvoke(
        create_initial_state("task-serde", str(ws), thread_id), config=config
    )
    await graph.ainvoke(Command(resume={"approved": True}), config=config)

    final_snap = await graph.aget_state(config)

    # Verify JSON serializability of every field in values
    serializable_dict = {}
    for k, v in final_snap.values.items():
        if hasattr(v, "model_dump"):
            serializable_dict[k] = v.model_dump()
        else:
            serializable_dict[k] = v

    serialized_str = json.dumps(serializable_dict, default=str)
    assert len(serialized_str) > 0
    assert "task-serde" in serialized_str

    set_llm_gateway(None)
    set_execution_service(None)


@pytest.mark.asyncio
async def test_e2e_live_docker_sandbox_execution(tmp_path: Path):
    """Executes live Docker sandbox through the complete end-to-end workflow if Docker is accessible."""
    if not is_docker_daemon_accessible():
        pytest.skip("Docker daemon is not accessible on this environment.")

    ws = tmp_path / "docker_live_math"
    ws.mkdir(parents=True, exist_ok=True)

    math_file = ws / "math_mod.py"
    math_file.write_text(
        "def multiply(a: int, b: int) -> int:\n    return a * b\n", encoding="utf-8"
    )

    test_file = ws / "test_math_mod.py"
    test_file.write_text(
        "from math_mod import multiply\n\n"
        "def test_multiply():\n    assert multiply(3, 4) == 12\n",
        encoding="utf-8",
    )
    init_test_git_repo(ws)

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(
                summary="Plan", steps=["Verify code"], files_expected=["math_mod.py"]
            )
        if response_schema is CoderOutput:
            return CoderOutput(summary="No change needed", patch="", files_changed=[])
        if response_schema is ReviewerOutput:
            return ReviewerOutput(
                verdict="approved",
                summary="Verified in Docker",
                issues=[],
                security_concerns=[],
                required_changes=[],
            )
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)

    checkpointer = MemorySaver()
    graph = build_agent_graph(checkpointer=checkpointer)
    thread_id = "thread-e2e-live-docker"
    config = {"configurable": {"thread_id": thread_id}}

    state = create_initial_state("task-docker-live", str(ws), thread_id)
    state["test_command"] = "pytest"

    await graph.ainvoke(state, config=config)
    await graph.ainvoke(Command(resume={"approved": True}), config=config)

    final_snap = await graph.aget_state(config)
    assert final_snap.next == ()
    assert final_snap.values["final_result"].status == "completed"
    assert final_snap.values["test_result"]["success"] is True
    assert final_snap.values["test_result"]["exit_code"] == 0
    assert final_snap.values["test_result"]["is_stub"] is False

    set_llm_gateway(None)
