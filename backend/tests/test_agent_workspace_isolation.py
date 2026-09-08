import asyncio
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agent.graph import build_agent_graph
from app.agent.nodes import (
    apply_approved_patch,
    coder,
    inspect_workspace,
    set_execution_service,
    set_llm_gateway,
)
from app.agent.state import create_initial_state
from app.core.config import settings
from app.schemas.agent_contracts import (
    CoderOutput,
    DebuggerOutput,
    PlannerOutput,
)
from app.services.llm.gateway import LLMGateway


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
    exit_code: int,
    stdout: str,
    stderr: str = "",
    command: list[str] | None = None,
    success: bool | None = None,
) -> dict[str, Any]:
    """Helper creating a dictionary matching ExecutionService.execute_in_sandbox return contract."""
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
async def test_concurrent_workspaces_cannot_cross_write(tmp_path: Path):
    """Proves concurrent patch applications targeting different workspaces cannot cross-write."""
    ws_a = tmp_path / "ws_a"
    ws_b = tmp_path / "ws_b"
    ws_a.mkdir(parents=True, exist_ok=True)
    ws_b.mkdir(parents=True, exist_ok=True)

    file_a = ws_a / "calc.py"
    file_b = ws_b / "calc.py"

    file_a.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    file_b.write_text("def add(a, b):\n    return a * b\n", encoding="utf-8")

    init_test_git_repo(ws_a)
    init_test_git_repo(ws_b)

    patch_a = (
        "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n"
        " def add(a, b):\n-    return a - b\n+    return a + b\n"
    )
    patch_b = (
        "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n"
        " def add(a, b):\n-    return a * b\n+    return a / b\n"
    )

    state_a = create_initial_state("task-a", str(ws_a), "th-a")
    state_a["pending_patch"] = patch_a
    state_a["approval"] = True

    state_b = create_initial_state("task-b", str(ws_b), "th-b")
    state_b["pending_patch"] = patch_b
    state_b["approval"] = True

    original_setting = settings.WORKSPACE_BASE_PATH

    res_a, res_b = await asyncio.gather(
        apply_approved_patch(state_a),
        apply_approved_patch(state_b),
    )

    assert res_a["error"] is None
    assert res_b["error"] is None
    assert file_a.read_text(encoding="utf-8") == "def add(a, b):\n    return a + b\n"
    assert file_b.read_text(encoding="utf-8") == "def add(a, b):\n    return a / b\n"
    assert settings.WORKSPACE_BASE_PATH == original_setting


@pytest.mark.asyncio
async def test_interleaved_global_setting_tampering_immunity(tmp_path: Path):
    """Proves mutating settings.WORKSPACE_BASE_PATH externally cannot divert a task's patch."""
    ws_a = tmp_path / "ws_target"
    ws_b = tmp_path / "ws_tampered"
    ws_a.mkdir(parents=True, exist_ok=True)
    ws_b.mkdir(parents=True, exist_ok=True)

    file_a = ws_a / "service.py"
    file_b = ws_b / "service.py"

    initial_a = "VERSION = '1.0'\n"
    initial_b = "VERSION = 'PRISTINE'\n"

    file_a.write_text(initial_a, encoding="utf-8")
    file_b.write_text(initial_b, encoding="utf-8")

    init_test_git_repo(ws_a)
    init_test_git_repo(ws_b)

    patch_a = (
        "--- a/service.py\n+++ b/service.py\n@@ -1 +1 @@\n"
        "-VERSION = '1.0'\n+VERSION = '2.0'\n"
    )

    state_a = create_initial_state("task-tamper", str(ws_a), "th-tamper")
    state_a["pending_patch"] = patch_a
    state_a["approval"] = True

    original_setting = settings.WORKSPACE_BASE_PATH
    try:
        settings.WORKSPACE_BASE_PATH = ws_b.resolve()

        res = await apply_approved_patch(state_a)

        assert res["error"] is None
        assert file_a.read_text(encoding="utf-8") == "VERSION = '2.0'\n"
        assert file_b.read_text(encoding="utf-8") == initial_b
    finally:
        settings.WORKSPACE_BASE_PATH = original_setting


@pytest.mark.asyncio
async def test_inspect_workspace_does_not_mutate_settings(tmp_path: Path):
    """Proves inspect_workspace indexes workspace files without mutating global settings."""
    ws = tmp_path / "ws_inspect"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "main.py").write_text("print('hello')", encoding="utf-8")
    (ws / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")

    state = create_initial_state("task-insp", str(ws), "th-insp")
    original_setting = settings.WORKSPACE_BASE_PATH

    res = await inspect_workspace(state)

    assert res["current_step"] == 1
    assert "main.py" in res["workspace_summary"]
    assert settings.WORKSPACE_BASE_PATH == original_setting


@pytest.mark.asyncio
async def test_coder_exception_clears_stale_authorization_unit(tmp_path: Path):
    """Proves that a coder exception explicitly invalidates stale approval and proposal fields."""
    state = create_initial_state("task-stale-1", str(tmp_path), "th-stale-1")
    state["approval"] = True
    state["pending_patch"] = "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n"
    state["applied_diff"] = "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n"
    state["coder_proposal"] = CoderOutput(
        summary="Old proposal",
        patch=state["pending_patch"],
        files_changed=["app.py"],
    )

    mock_gw = MagicMock(spec=LLMGateway)
    mock_gw.generate_structured = AsyncMock(
        side_effect=RuntimeError("LLM Provider Timeout")
    )
    set_llm_gateway(mock_gw)

    update = await coder(state)

    assert update["approval"] is None
    assert update["pending_patch"] is None
    assert update["coder_proposal"] is None
    assert update["applied_diff"] is None
    assert "Coder failed" in update["error"]

    state.update(update)
    assert state["approval"] is None
    assert state["pending_patch"] is None
    assert state["coder_proposal"] is None
    assert state["applied_diff"] is None

    set_llm_gateway(None)


@pytest.mark.asyncio
async def test_graph_repair_coder_failure_cannot_bypass_hitl(tmp_path: Path):
    """Proves a repair-cycle coder failure clears authorization and cannot bypass approval gate."""
    target = tmp_path / "module.py"
    target.write_text("val = 1\n", encoding="utf-8")
    init_test_git_repo(tmp_path)

    mock_exec = MagicMock()
    mock_exec.execute_in_sandbox.return_value = make_mock_exec_result(
        exit_code=1,
        stdout="FAILED assert val == 2\n",
        stderr="",
        command=["pytest"],
    )

    patch_v1 = "--- a/module.py\n+++ b/module.py\n@@ -1 +1 @@\n-val = 1\n+val = 2\n"
    coder_call_count = 0

    async def mock_structured(prompt, response_schema, **kwargs):
        nonlocal coder_call_count
        if response_schema is PlannerOutput:
            return PlannerOutput(
                summary="Plan", steps=["Step 1"], files_expected=["module.py"]
            )
        if response_schema is CoderOutput:
            coder_call_count += 1
            if coder_call_count == 1:
                return CoderOutput(
                    summary="Initial proposal",
                    patch=patch_v1,
                    files_changed=["module.py"],
                )
            raise RuntimeError("LLM service temporarily unavailable")
        if response_schema is DebuggerOutput:
            return DebuggerOutput(
                diagnosis="Failed assert",
                proposed_fix="Fix code",
                files_to_change=["module.py"],
            )
        return response_schema.model_validate({})

    mock_gw = MagicMock(spec=LLMGateway)
    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)
    set_execution_service(mock_exec)

    thread_id = "th-stale-bypass"
    config = {"configurable": {"thread_id": thread_id}}
    shared_saver = MemorySaver()
    graph = build_agent_graph(checkpointer=shared_saver)

    state = create_initial_state("task-sb", str(tmp_path), thread_id)
    await graph.ainvoke(state, config=config)

    # Operator approves initial patch -> applied -> test runner fails -> debugger -> coder fails
    await graph.ainvoke(Command(resume={"approved": True}), config=config)

    snap = await graph.aget_state(config)

    assert snap.values["approval"] is None
    assert snap.values["pending_patch"] is None
    assert snap.values["coder_proposal"] is None
    assert snap.values.get("error") is not None
    assert "Coder failed" in snap.values["error"]
    assert target.read_text(encoding="utf-8") == "val = 2\n"

    set_llm_gateway(None)
    set_execution_service(None)
