import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agent.graph import build_agent_graph
from app.agent.nodes import apply_approved_patch, coder, set_llm_gateway
from app.agent.state import create_initial_state, validate_state_invariants
from app.schemas.agent_contracts import CoderOutput, PlannerOutput, ReviewerOutput
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


@pytest.mark.asyncio
async def test_approved_valid_patch_applied_to_filesystem(tmp_path: Path):
    """Proves that explicit approval applies the pending patch to disk and records applied_diff."""
    target_file = tmp_path / "calc.py"
    target_file.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    init_test_git_repo(tmp_path)

    patch_text = (
        "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n"
        " def add(a, b):\n-    return a - b\n+    return a + b\n"
    )

    state = create_initial_state("task-p1", str(tmp_path), "th-p1")
    state["pending_patch"] = patch_text
    state["approval"] = True

    res = await apply_approved_patch(state)

    assert res["error"] is None
    assert res["applied_diff"] is not None
    assert "-    return a - b" in res["applied_diff"]
    assert "+    return a + b" in res["applied_diff"]
    assert (
        target_file.read_text(encoding="utf-8") == "def add(a, b):\n    return a + b\n"
    )


@pytest.mark.asyncio
async def test_rejected_patch_never_mutates_filesystem(tmp_path: Path):
    """Proves that when approval is False, apply_approved_patch aborts with zero filesystem changes."""
    target_file = tmp_path / "service.py"
    initial_code = "SECRET_CONFIG = True\n"
    target_file.write_text(initial_code, encoding="utf-8")
    init_test_git_repo(tmp_path)

    patch_text = (
        "--- a/service.py\n+++ b/service.py\n@@ -1 +1 @@\n"
        "-SECRET_CONFIG = True\n+SECRET_CONFIG = False\n"
    )

    state = create_initial_state("task-p2", str(tmp_path), "th-p2")
    state["pending_patch"] = patch_text
    state["approval"] = False

    res = await apply_approved_patch(state)

    assert res["applied_diff"] is None
    assert "approval was not granted" in res["error"]
    assert target_file.read_text(encoding="utf-8") == initial_code


@pytest.mark.asyncio
async def test_unresolved_hitl_interrupt_never_mutates_filesystem(tmp_path: Path):
    """Proves that a workflow pausing at approval_gate leaves disk untouched before operator response."""
    target_file = tmp_path / "endpoint.py"
    initial_content = "def handler(): return 404\n"
    target_file.write_text(initial_content, encoding="utf-8")
    init_test_git_repo(tmp_path)

    patch_text = (
        "--- a/endpoint.py\n+++ b/endpoint.py\n@@ -1 +1 @@\n"
        "-def handler(): return 404\n+def handler(): return 200\n"
    )
    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_generate_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(
                summary="Plan endpoint fix",
                steps=["Inspect endpoint", "Update return code"],
                files_expected=["endpoint.py"],
            )
        return CoderOutput(
            summary="Fix endpoint",
            patch=patch_text,
            files_changed=["endpoint.py"],
        )

    mock_gw.generate_structured = AsyncMock(side_effect=mock_generate_structured)
    set_llm_gateway(mock_gw)

    graph = build_agent_graph()
    thread_id = "th-hitl-unresolved"
    config = {"configurable": {"thread_id": thread_id}}

    state = create_initial_state("task-p3", str(tmp_path), thread_id, prompt="Fix 404")
    await graph.ainvoke(state, config=config)

    snap = await graph.aget_state(config)
    assert snap.next == ("approval_gate",)
    assert snap.values["pending_patch"] == patch_text
    assert snap.values.get("applied_diff") is None
    assert target_file.read_text(encoding="utf-8") == initial_content
    set_llm_gateway(None)


@pytest.mark.asyncio
async def test_coder_proposal_alone_does_not_mutate_filesystem(tmp_path: Path):
    """Proves that coder generates pending_patch without writing to the target file."""
    target_file = tmp_path / "models.py"
    initial_text = "class User: pass\n"
    target_file.write_text(initial_text, encoding="utf-8")

    mock_gw = MagicMock(spec=LLMGateway)
    patch_text = "--- a/models.py\n+++ b/models.py\n@@ -1 +1 @@\n-class User: pass\n+class User: id: int\n"
    mock_gw.generate_structured = AsyncMock(
        return_value=CoderOutput(
            summary="Add model id",
            patch=patch_text,
            files_changed=["models.py"],
        )
    )

    state = create_initial_state("task-p4", str(tmp_path), "th-p4", prompt="Add id")
    res = await coder(state, config={"configurable": {"llm_gateway": mock_gw}})

    assert res["pending_patch"] == patch_text
    assert target_file.read_text(encoding="utf-8") == initial_text


@pytest.mark.asyncio
async def test_path_traversal_patch_rejected_and_aborts_mutation(tmp_path: Path):
    """Proves that patches attempting directory traversal are rejected by the Day 2 tool layer."""
    (tmp_path / "safe.py").write_text("x = 1\n", encoding="utf-8")
    init_test_git_repo(tmp_path)

    traversal_patch = (
        "--- a/../../outside.py\n+++ b/../../outside.py\n@@ -1 +1 @@\n"
        "-evil = False\n+evil = True\n"
    )

    state = create_initial_state("task-p5", str(tmp_path), "th-p5")
    state["pending_patch"] = traversal_patch
    state["approval"] = True

    res = await apply_approved_patch(state)

    assert res["applied_diff"] is None
    assert res["tool_result"]["success"] is False
    assert "Patch application failed" in res["error"]


@pytest.mark.asyncio
async def test_absolute_path_patch_rejected(tmp_path: Path):
    """Proves that patches with absolute paths are rejected by the Day 2 tool layer."""
    (tmp_path / "safe.py").write_text("x = 1\n", encoding="utf-8")
    init_test_git_repo(tmp_path)

    absolute_patch = (
        "--- a//etc/shadow\n+++ b//etc/shadow\n@@ -1 +1 @@\n-root:*\n+root:pwned\n"
    )

    state = create_initial_state("task-p6", str(tmp_path), "th-p6")
    state["pending_patch"] = absolute_patch
    state["approval"] = True

    res = await apply_approved_patch(state)

    assert res["applied_diff"] is None
    assert res["tool_result"]["success"] is False
    assert "Patch application failed" in res["error"]


@pytest.mark.asyncio
async def test_protected_env_file_patch_rejected(tmp_path: Path):
    """Proves that patches attempting to mutate .env are rejected and left unmodified."""
    env_file = tmp_path / ".env"
    initial_env = "DATABASE_PASSWORD=secret_pg_pwd_1234\n"
    env_file.write_text(initial_env, encoding="utf-8")
    init_test_git_repo(tmp_path)

    env_patch = (
        "--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n"
        "-DATABASE_PASSWORD=secret_pg_pwd_1234\n+DATABASE_PASSWORD=leaked\n"
    )

    state = create_initial_state("task-p7", str(tmp_path), "th-p7")
    state["pending_patch"] = env_patch
    state["approval"] = True

    res = await apply_approved_patch(state)

    assert res["applied_diff"] is None
    assert res["tool_result"]["success"] is False
    assert "protected" in str(res["tool_result"]["error"]).lower()
    assert env_file.read_text(encoding="utf-8") == initial_env


@pytest.mark.asyncio
async def test_malformed_patch_syntax_rejected_safely(tmp_path: Path):
    """Proves that malformed patch strings return a clean failure without corrupting files."""
    target = tmp_path / "valid.py"
    target.write_text("x = 10\n", encoding="utf-8")
    init_test_git_repo(tmp_path)

    malformed_patch = "This is definitely not a valid unified diff format string."

    state = create_initial_state("task-p8", str(tmp_path), "th-p8")
    state["pending_patch"] = malformed_patch
    state["approval"] = True

    res = await apply_approved_patch(state)

    assert res["applied_diff"] is None
    assert res["tool_result"]["success"] is False
    assert "Patch application failed" in res["error"]
    assert target.read_text(encoding="utf-8") == "x = 10\n"


@pytest.mark.asyncio
async def test_checkpoint_resume_then_apply_patch_lifecycle(tmp_path: Path):
    """Proves interrupted workflow resumes across graph instances and applies approved patch."""
    target = tmp_path / "feature.py"
    target.write_text("ENABLED = False\n", encoding="utf-8")
    init_test_git_repo(tmp_path)

    patch_text = (
        "--- a/feature.py\n+++ b/feature.py\n@@ -1 +1 @@\n"
        "-ENABLED = False\n+ENABLED = True\n"
    )
    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_generate_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(
                summary="Plan feature",
                steps=["Enable feature flag"],
                files_expected=["feature.py"],
            )
        if response_schema is CoderOutput:
            return CoderOutput(
                summary="Enable feature",
                patch=patch_text,
                files_changed=["feature.py"],
            )
        if response_schema is ReviewerOutput:
            return ReviewerOutput(
                verdict="approved",
                summary="Feature enabled and verified",
                issues=[],
                security_concerns=[],
                required_changes=[],
            )
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_generate_structured)
    set_llm_gateway(mock_gw)

    thread_id = "th-chk-patch-apply"
    execution_service = MagicMock()
    execution_service.execute_in_sandbox.return_value = {
        "command": "pytest",
        "exit_code": 0,
        "stdout": "1 passed\n",
        "stderr": "",
        "truncated": False,
        "duration_seconds": 0.01,
    }
    config = {"configurable": {"thread_id": thread_id, "execution_service": execution_service}}
    shared_saver = MemorySaver()

    # 1. Graph instance A halts at approval_gate
    graph_a = build_agent_graph(checkpointer=shared_saver)
    state = create_initial_state("task-p9", str(tmp_path), thread_id)
    await graph_a.ainvoke(state, config=config)

    snap_a = await graph_a.aget_state(config)
    assert snap_a.next == ("approval_gate",)
    assert target.read_text(encoding="utf-8") == "ENABLED = False\n"
    del graph_a

    # 2. Graph instance B attaches to the same checkpointer and resumes with approval
    graph_b = build_agent_graph(checkpointer=shared_saver)
    await graph_b.ainvoke(Command(resume={"approved": True}), config=config)

    snap_b = await graph_b.aget_state(config)
    assert snap_b.values["approval"] is True
    assert snap_b.values.get("applied_diff") is not None
    assert target.read_text(encoding="utf-8") == "ENABLED = True\n"
    set_llm_gateway(None)


@pytest.mark.asyncio
async def test_patch_application_state_invariants_and_serialization(tmp_path: Path):
    """Proves AgentState after patch application satisfies invariants and JSON serialization."""
    target = tmp_path / "core.py"
    target.write_text("val = 1\n", encoding="utf-8")
    init_test_git_repo(tmp_path)

    patch_text = "--- a/core.py\n+++ b/core.py\n@@ -1 +1 @@\n-val = 1\n+val = 2\n"
    state = create_initial_state("task-p10", str(tmp_path), "th-p10")
    state["pending_patch"] = patch_text
    state["approval"] = True

    res = await apply_approved_patch(state)
    state.update(res)

    validate_state_invariants(state)
    serialized = json.dumps(state, default=str)
    assert "core.py" in serialized
    assert "applied_diff" in serialized


# --- New Hardening Tests for Multi-File Patches & Validation Atomicity ---


@pytest.mark.asyncio
async def test_multi_file_approved_valid_patch_applied(tmp_path: Path):
    """Proves that a valid multi-file patch applies all file modifications and records full diff."""
    file1 = tmp_path / "calc.py"
    file1.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    file2 = tmp_path / "utils.py"
    file2.write_text("def sub(a, b):\n    return a + b\n", encoding="utf-8")
    init_test_git_repo(tmp_path)

    multi_patch = (
        "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n"
        " def add(a, b):\n-    return a - b\n+    return a + b\n"
        "--- a/utils.py\n+++ b/utils.py\n@@ -1,2 +1,2 @@\n"
        " def sub(a, b):\n-    return a + b\n+    return a - b\n"
    )

    state = create_initial_state("task-mf1", str(tmp_path), "th-mf1")
    state["pending_patch"] = multi_patch
    state["approval"] = True

    res = await apply_approved_patch(state)

    assert res["error"] is None
    assert res["applied_diff"] is not None
    assert "calc.py" in res["applied_diff"]
    assert "utils.py" in res["applied_diff"]
    assert file1.read_text(encoding="utf-8") == "def add(a, b):\n    return a + b\n"
    assert file2.read_text(encoding="utf-8") == "def sub(a, b):\n    return a - b\n"


@pytest.mark.asyncio
async def test_multi_file_patch_second_file_traversal_rejects_all(tmp_path: Path):
    """Proves that a multi-file patch with a traversal target rejects the entire patch before any mutation."""
    safe_file = tmp_path / "safe.py"
    initial_safe = "safe_var = 100\n"
    safe_file.write_text(initial_safe, encoding="utf-8")
    init_test_git_repo(tmp_path)

    mixed_patch = (
        "--- a/safe.py\n+++ b/safe.py\n@@ -1 +1 @@\n"
        "-safe_var = 100\n+safe_var = 999\n"
        "--- a/../../outside.py\n+++ b/../../outside.py\n@@ -1 +1 @@\n"
        "-evil = False\n+evil = True\n"
    )

    state = create_initial_state("task-mf2", str(tmp_path), "th-mf2")
    state["pending_patch"] = mixed_patch
    state["approval"] = True

    res = await apply_approved_patch(state)

    assert res["applied_diff"] is None
    assert "Patch application failed" in res["error"]
    assert safe_file.read_text(encoding="utf-8") == initial_safe


@pytest.mark.asyncio
async def test_multi_file_patch_second_file_absolute_rejects_all(tmp_path: Path):
    """Proves that a multi-file patch with an absolute path target rejects the entire patch with zero mutation."""
    safe_file = tmp_path / "safe.py"
    initial_safe = "status = 'ok'\n"
    safe_file.write_text(initial_safe, encoding="utf-8")
    init_test_git_repo(tmp_path)

    mixed_patch = (
        "--- a/safe.py\n+++ b/safe.py\n@@ -1 +1 @@\n"
        "-status = 'ok'\n+status = 'compromised'\n"
        "--- a//etc/shadow\n+++ b//etc/shadow\n@@ -1 +1 @@\n"
        "-root:*\n+root:pwned\n"
    )

    state = create_initial_state("task-mf3", str(tmp_path), "th-mf3")
    state["pending_patch"] = mixed_patch
    state["approval"] = True

    res = await apply_approved_patch(state)

    assert res["applied_diff"] is None
    assert "Patch application failed" in res["error"]
    assert safe_file.read_text(encoding="utf-8") == initial_safe


@pytest.mark.asyncio
async def test_multi_file_patch_containing_protected_env_rejects_all(tmp_path: Path):
    """Proves that a multi-file patch containing .env rejects the entire patch and mutates nothing."""
    app_file = tmp_path / "app.py"
    initial_app = "APP_DEBUG = False\n"
    app_file.write_text(initial_app, encoding="utf-8")

    env_file = tmp_path / ".env"
    initial_env = "SECRET_API_KEY=prod_key_9999\n"
    env_file.write_text(initial_env, encoding="utf-8")
    init_test_git_repo(tmp_path)

    mixed_patch = (
        "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n"
        "-APP_DEBUG = False\n+APP_DEBUG = True\n"
        "--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n"
        "-SECRET_API_KEY=prod_key_9999\n+SECRET_API_KEY=leaked\n"
    )

    state = create_initial_state("task-mf4", str(tmp_path), "th-mf4")
    state["pending_patch"] = mixed_patch
    state["approval"] = True

    res = await apply_approved_patch(state)

    assert res["applied_diff"] is None
    assert "protected" in res["error"].lower()
    assert app_file.read_text(encoding="utf-8") == initial_app
    assert env_file.read_text(encoding="utf-8") == initial_env


@pytest.mark.asyncio
async def test_multi_file_patch_second_file_malformed_rolls_back_first(tmp_path: Path):
    """Proves that if any file fails application in a multi-file patch, previously applied files are rolled back."""
    file_a = tmp_path / "mod_a.py"
    initial_a = "x = 1\n"
    file_a.write_text(initial_a, encoding="utf-8")

    file_b = tmp_path / "mod_b.py"
    initial_b = "y = 1\n"
    file_b.write_text(initial_b, encoding="utf-8")
    init_test_git_repo(tmp_path)

    broken_multi_patch = (
        "--- a/mod_a.py\n+++ b/mod_a.py\n@@ -1 +1 @@\n"
        "-x = 1\n+x = 2\n"
        "--- a/mod_b.py\n+++ b/mod_b.py\n@@ -1 +1 @@\n"
        "-y = 9999\n+y = 2\n"
    )

    state = create_initial_state("task-mf5", str(tmp_path), "th-mf5")
    state["pending_patch"] = broken_multi_patch
    state["approval"] = True

    res = await apply_approved_patch(state)

    assert res["applied_diff"] is None
    assert "Patch application failed" in res["error"]
    assert file_a.read_text(encoding="utf-8") == initial_a
    assert file_b.read_text(encoding="utf-8") == initial_b


@pytest.mark.asyncio
async def test_multi_file_patch_duplicate_target_rejected(tmp_path: Path):
    """Proves that duplicate file targets within a patch are rejected to avoid ambiguous state."""
    dup_file = tmp_path / "dup.py"
    initial_dup = "count = 0\n"
    dup_file.write_text(initial_dup, encoding="utf-8")
    init_test_git_repo(tmp_path)

    duplicate_patch = (
        "--- a/dup.py\n+++ b/dup.py\n@@ -1 +1 @@\n"
        "-count = 0\n+count = 1\n"
        "--- a/dup.py\n+++ b/dup.py\n@@ -1 +1 @@\n"
        "-count = 1\n+count = 2\n"
    )

    state = create_initial_state("task-mf6", str(tmp_path), "th-mf6")
    state["pending_patch"] = duplicate_patch
    state["approval"] = True

    res = await apply_approved_patch(state)

    assert res["applied_diff"] is None
    assert "duplicate" in res["error"].lower()
    assert dup_file.read_text(encoding="utf-8") == initial_dup
