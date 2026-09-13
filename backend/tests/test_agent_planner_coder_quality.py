import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.nodes import (
    coder,
    debugger,
    planner,
    reviewer,
    set_llm_gateway,
)
from app.agent.state import create_initial_state, validate_state_invariants
from app.schemas.agent_contracts import (
    CoderOutput,
    DebuggerOutput,
    PlannerOutput,
    ReviewerOutput,
    ReviewerVerdict,
)
from app.services.llm.gateway import LLMGateway


def test_planner_output_schema_day10_fields_and_backwards_compat():
    plan = PlannerOutput(
        summary="Refactor token validation",
        steps=["Inspect token signature", "Update expiration logic"],
        objective="Ensure JWT expiration is strictly verified",
        affected_files=["auth/token.py"],
        supporting_files=["auth/keys.py"],
        test_strategy="Run pytest tests/test_token.py",
        tests_to_run_or_add=["tests/test_token.py"],
        out_of_scope=["auth/oauth.py"],
        minimality_rationale="Only token.py requires expiration checking logic",
    )
    assert plan.summary == "Refactor token validation"
    assert plan.objective == "Ensure JWT expiration is strictly verified"
    assert plan.files_expected == ["auth/token.py"]
    assert plan.affected_files == ["auth/token.py"]
    assert plan.supporting_files == ["auth/keys.py"]
    assert plan.out_of_scope == ["auth/oauth.py"]

    # Backward compatibility with minimal legacy input
    legacy_plan = PlannerOutput(
        summary="Minimal legacy plan",
        steps=["Step 1"],
        files_expected=["core.py"],
    )
    assert legacy_plan.affected_files == ["core.py"]
    assert legacy_plan.objective == "Minimal legacy plan"


def test_coder_output_schema_day10_fields_and_backwards_compat():
    coder_out = CoderOutput(
        summary="Update expiration delta",
        patch="--- a/token.py\n+++ b/token.py\n@@ -1 +1 @@\n-delta = 60\n+delta = 3600\n",
        files_changed=["token.py"],
        explanation="Expands token lifetime to 1 hour",
        is_minimal=True,
        tests_modified=["tests/test_token.py"],
    )
    assert coder_out.is_minimal is True
    assert coder_out.explanation == "Expands token lifetime to 1 hour"
    assert coder_out.tests_modified == ["tests/test_token.py"]

    # Backward compatibility
    legacy_coder = CoderOutput(summary="Quick fix")
    assert legacy_coder.is_minimal is True
    assert legacy_coder.files_changed == []


def test_debugger_output_schema_day10_fields_and_backwards_compat():
    debug_out = DebuggerOutput(
        diagnosis="Token expired prematurely",
        proposed_fix="Increase delta value in token.py",
        symptom="AssertionError: TokenExpired",
        root_cause="Delta was set to 0 seconds",
        evidence="test_token.py:42: AssertionError",
        repair_strategy="Set delta to positive integer",
        regression_risk="Must not allow negative expiration",
        files_to_change=["token.py"],
    )
    assert debug_out.symptom == "AssertionError: TokenExpired"
    assert debug_out.root_cause == "Delta was set to 0 seconds"
    assert debug_out.repair_strategy == "Set delta to positive integer"

    # Backward compatibility
    legacy_debug = DebuggerOutput(
        diagnosis="Old diagnosis",
        proposed_fix="Old fix",
    )
    assert legacy_debug.root_cause == "Old diagnosis"
    assert legacy_debug.repair_strategy == "Old fix"


@pytest.mark.asyncio
async def test_planner_node_enforces_structured_reasoning_and_minimality(
    tmp_path: Path,
):
    mock_gw = MagicMock(spec=LLMGateway)
    captured_prompt = ""

    async def mock_structured(prompt, response_schema, **kwargs):
        nonlocal captured_prompt
        captured_prompt = prompt
        return PlannerOutput(
            summary="Add multiply function",
            steps=["Define multiply in math.py", "Add unit test"],
            objective="Provide multiplication utility",
            affected_files=["math.py"],
            supporting_files=["types.py"],
            test_strategy="Add test_multiply in tests/test_math.py",
            tests_to_run_or_add=["tests/test_math.py"],
            out_of_scope=["math_advanced.py"],
            minimality_rationale="Single helper function needed",
        )

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)

    state = create_initial_state(
        "task-q1", str(tmp_path), "th-q1", prompt="Implement multiply"
    )
    state["workspace_summary"] = "Workspace contains math.py and types.py"
    state["repository_context"] = {
        "summary": "math.py found",
        "relevant_files": [
            {
                "path": "math.py",
                "reason": "Target module",
                "excerpt": "def add(a, b): return a + b\n",
            }
        ],
    }

    res = await planner(state)
    assert res["current_step"] == 2
    assert "PLANNING INSTRUCTIONS (DISCIPLINED REASONING ORDER):" in captured_prompt
    assert "'affected_files': Smallest set of existing/new files" in captured_prompt
    assert "'out_of_scope': Related files, components, or refactors" in captured_prompt
    assert "'minimality_rationale': Explain why this plan represents" in captured_prompt
    assert '<code_context path="math.py"' in captured_prompt

    plan = res["plan"]
    assert plan.objective == "Provide multiplication utility"
    assert plan.affected_files == ["math.py"]
    assert plan.out_of_scope == ["math_advanced.py"]

    set_llm_gateway(None)


@pytest.mark.asyncio
async def test_planner_distinguishes_affected_supporting_and_test_files(tmp_path: Path):
    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        return PlannerOutput(
            summary="Secure endpoint authentication",
            steps=["Validate token header in endpoint.py"],
            objective="Ensure request is authenticated",
            affected_files=["endpoint.py"],
            supporting_files=["auth.py"],
            tests_to_run_or_add=["tests/test_endpoint.py"],
            out_of_scope=["billing.py", "users.py"],
            minimality_rationale="Only endpoint auth check is missing",
        )

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)

    state = create_initial_state(
        "task-q2", str(tmp_path), "th-q2", prompt="Secure endpoint"
    )
    res = await planner(state)
    plan = res["plan"]

    assert plan.affected_files == ["endpoint.py"]
    assert plan.supporting_files == ["auth.py"]
    assert "billing.py" in plan.out_of_scope
    assert "users.py" in plan.out_of_scope

    set_llm_gateway(None)


@pytest.mark.asyncio
async def test_coder_node_receives_minimality_and_repository_context(tmp_path: Path):
    mock_gw = MagicMock(spec=LLMGateway)
    captured_prompt = ""

    async def mock_structured(prompt, response_schema, **kwargs):
        nonlocal captured_prompt
        captured_prompt = prompt
        return CoderOutput(
            summary="Implement multiply",
            patch="--- a/math.py\n+++ b/math.py\n@@ -1 +1,2 @@\n def add(a, b): return a + b\n+def multiply(a, b): return a * b\n",
            files_changed=["math.py"],
            explanation="Added multiply function",
            is_minimal=True,
            tests_modified=["tests/test_math.py"],
        )

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)

    state = create_initial_state(
        "task-q3", str(tmp_path), "th-q3", prompt="Implement multiply"
    )
    state["plan"] = PlannerOutput(
        summary="Add multiply",
        steps=["Add multiply function"],
        objective="Support multiply",
        affected_files=["math.py"],
        supporting_files=["types.py"],
        test_strategy="Add test_multiply in tests/test_math.py",
        out_of_scope=["matrix.py"],
        minimality_rationale="Surgical one-function addition",
    )
    state["repository_context"] = {
        "summary": "Existing math module",
        "relevant_files": [
            {
                "path": "math.py",
                "reason": "Target",
                "excerpt": "def add(a, b): return a + b\n",
            }
        ],
    }

    res = await coder(state)
    assert res["current_step"] == 3
    assert (
        "CODER IMPLEMENTATION REQUIREMENTS (MINIMAL PATCH PRINCIPLE):"
        in captured_prompt
    )
    assert "Objective: Support multiply" in captured_prompt
    assert "Expected Target Files: math.py" in captured_prompt
    assert "Minimality Rationale: Surgical one-function addition" in captured_prompt
    assert "Explicitly Out of Scope: matrix.py" in captured_prompt
    assert '<code_context path="math.py"' in captured_prompt

    set_llm_gateway(None)


@pytest.mark.asyncio
async def test_coder_proposal_does_not_mutate_filesystem(tmp_path: Path):
    target = tmp_path / "math.py"
    target.write_text("def add(a, b): return a + b\n", encoding="utf-8")

    mock_gw = MagicMock(spec=LLMGateway)
    mock_gw.generate_structured = AsyncMock(
        return_value=CoderOutput(
            summary="Proposal",
            patch="--- a/math.py\n+++ b/math.py\n@@ -1 +1 @@\n-def add(a, b): return a + b\n+def add(a, b): return 42\n",
            files_changed=["math.py"],
        )
    )
    set_llm_gateway(mock_gw)

    state = create_initial_state("task-q4", str(tmp_path), "th-q4", prompt="Change add")
    res = await coder(state)

    assert res["pending_patch"] is not None
    assert target.read_text(encoding="utf-8") == "def add(a, b): return a + b\n"

    set_llm_gateway(None)


@pytest.mark.asyncio
async def test_coder_proposal_is_advisory_no_hallucinated_execution(tmp_path: Path):
    mock_gw = MagicMock(spec=LLMGateway)
    mock_gw.generate_structured = AsyncMock(
        return_value=CoderOutput(
            summary="Proposed diff",
            patch="diff --git a/x.py b/x.py\n",
            files_changed=["x.py"],
        )
    )
    set_llm_gateway(mock_gw)

    state = create_initial_state("task-q5", str(tmp_path), "th-q5", prompt="Test")
    res = await coder(state)

    assert res.get("approval") is None
    assert res.get("applied_diff") is None
    assert state.get("applied_diff") is None

    set_llm_gateway(None)


@pytest.mark.asyncio
async def test_coder_handles_repair_mode_with_debugger_context(tmp_path: Path):
    mock_gw = MagicMock(spec=LLMGateway)
    captured_prompt = ""

    async def mock_structured(prompt, response_schema, **kwargs):
        nonlocal captured_prompt
        captured_prompt = prompt
        return CoderOutput(
            summary="Fix boundary error",
            patch="--- a/calc.py\n+++ b/calc.py\n@@ -1 +1 @@\n-return a - b\n+return a + b\n",
            files_changed=["calc.py"],
        )

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)

    state = create_initial_state("task-q6", str(tmp_path), "th-q6", prompt="Fix calc")
    state["repair_count"] = 1
    state["debugger_output"] = DebuggerOutput(
        diagnosis="Subtraction used instead of addition",
        proposed_fix="Replace minus with plus operator in calc.py",
        symptom="AssertionError: 2 != 4",
        root_cause="calc.py subtracts arguments",
        evidence="calc_test.py:12: AssertionError: 2 != 4",
        repair_strategy="Change '-' to '+' in calc.py",
        regression_risk="Do not modify sub() function",
        files_to_change=["calc.py"],
    )

    res = await coder(state)
    assert res["current_step"] == 3
    assert "Debugger Failure Analysis (REPAIR IN PROGRESS):" in captured_prompt
    assert "Failure Symptom: AssertionError: 2 != 4" in captured_prompt
    assert (
        "Failure Evidence: calc_test.py:12: AssertionError: 2 != 4" in captured_prompt
    )
    assert "Target Repair Files: calc.py" in captured_prompt

    set_llm_gateway(None)


@pytest.mark.asyncio
async def test_debugger_node_structured_diagnosis_and_repair_strategy(tmp_path: Path):
    mock_gw = MagicMock(spec=LLMGateway)
    captured_prompt = ""

    async def mock_structured(prompt, response_schema, **kwargs):
        nonlocal captured_prompt
        captured_prompt = prompt
        return DebuggerOutput(
            diagnosis="Off-by-one in loop",
            proposed_fix="Change range(len(items) - 1) to range(len(items))",
            symptom="IndexError: list index out of range",
            root_cause="Range upper limit was truncated",
            evidence="File 'app.py', line 22, in process",
            repair_strategy="Restore complete iteration range",
            regression_risk="Ensure empty lists do not cause exception",
            files_to_change=["app.py"],
            reproduction_command="pytest tests/test_app.py",
        )

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)

    state = create_initial_state(
        "task-q7", str(tmp_path), "th-q7", prompt="Debug failure"
    )
    state["test_result"] = {
        "success": False,
        "exit_code": 1,
        "output": "FAILED tests/test_app.py::test_loop - IndexError: list index out of range",
    }
    state["repair_count"] = 0

    res = await debugger(state)
    assert res["current_step"] == 6
    assert res["repair_count"] == 1
    assert "DIAGNOSIS REQUIREMENTS:" in captured_prompt
    assert "1. Identify the 'symptom'" in captured_prompt
    assert "4. Formulate a targeted 'repair_strategy'" in captured_prompt

    debug_out = res["debugger_output"]
    assert debug_out.symptom == "IndexError: list index out of range"
    assert debug_out.root_cause == "Range upper limit was truncated"

    set_llm_gateway(None)


@pytest.mark.asyncio
async def test_debugger_repair_count_bounded_at_max(tmp_path: Path):
    mock_gw = MagicMock(spec=LLMGateway)
    mock_gw.generate_structured = AsyncMock(
        return_value=DebuggerOutput(
            diagnosis="Persistent failure",
            proposed_fix="None",
        )
    )
    set_llm_gateway(mock_gw)

    state = create_initial_state("task-q8", str(tmp_path), "th-q8", prompt="Exhaust")
    state["test_result"] = {"success": False, "exit_code": 1, "output": "Fail"}
    state["repair_count"] = 3

    res = await debugger(state)
    assert res["repair_count"] == 3

    set_llm_gateway(None)


@pytest.mark.asyncio
async def test_reviewer_cannot_approve_failed_tests_day10_invariants(tmp_path: Path):
    mock_gw = MagicMock(spec=LLMGateway)
    mock_gw.generate_structured = AsyncMock(
        return_value=ReviewerOutput(
            verdict=ReviewerVerdict.APPROVED,
            summary="Looks good to me despite failing test",
            issues=[],
        )
    )
    set_llm_gateway(mock_gw)

    state = create_initial_state("task-q9", str(tmp_path), "th-q9", prompt="Review")
    state["test_result"] = {"success": False, "output": "AssertionError"}

    res = await reviewer(state)
    rev = res["review_summary"]
    assert rev.verdict == ReviewerVerdict.REJECTED
    assert "Automated override" in rev.summary

    set_llm_gateway(None)


def test_state_invariants_and_serialization_with_day10_structures(tmp_path: Path):
    state = create_initial_state(
        "task-q10", str(tmp_path), "th-q10", prompt="Full lifecycle"
    )
    state["plan"] = PlannerOutput(
        summary="Plan",
        steps=["Step 1"],
        objective="Objective",
        affected_files=["a.py"],
        supporting_files=["b.py"],
        minimality_rationale="Minimal",
    )
    state["coder_proposal"] = CoderOutput(
        summary="Code",
        patch="diff",
        files_changed=["a.py"],
        explanation="Explanation",
        is_minimal=True,
    )
    state["debugger_output"] = DebuggerOutput(
        diagnosis="Diag",
        proposed_fix="Fix",
        symptom="Sym",
        root_cause="Cause",
    )

    assert validate_state_invariants(state) is True

    serialized = json.dumps(state, default=str)
    deserialized = json.loads(serialized)
    assert "objective" in str(deserialized["plan"])
    assert "is_minimal" in str(deserialized["coder_proposal"])
