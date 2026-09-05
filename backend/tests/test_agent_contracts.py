from collections.abc import AsyncIterator

import pytest
from pydantic import BaseModel

from app.core.exceptions import (
    DisallowedCommandException,
    LLMResponseException,
    LLMUnsupportedCapabilityException,
    ProtectedFileAccessViolationException,
    SecurityViolationException,
)
from app.core.security import validate_command
from app.schemas.agent_contracts import (
    CoderOutput,
    DebuggerOutput,
    FinalizationResult,
    PlannerOutput,
    ReviewerOutput,
)
from app.schemas.llm import (
    LLMConfig,
    LLMResponse,
    LLMStreamChunk,
    ModelInfo,
    ProviderCapabilities,
)
from app.services.llm.base import LLMProvider
from app.services.llm.gateway import LLMGateway
from app.services.llm.parser import parse_structured_output
from app.tools.validators import validate_not_protected, validate_safe_path


class MockContractProvider(LLMProvider):
    """Self-contained mock provider adapter for isolated contract testing."""

    def __init__(
        self,
        config: LLMConfig,
        caps: ProviderCapabilities | None = None,
    ) -> None:
        super().__init__(config)
        self._caps = caps or ProviderCapabilities()

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._caps

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            provider=self.provider_name,
            model=self.model,
            display_name=f"Mock ({self.model})",
            capabilities=self.capabilities,
        )

    async def generate(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> LLMResponse:
        return LLMResponse(
            content=f"Generated: {prompt}",
            model=self.model,
            provider=self.provider_name,
            finish_reason="STOP",
        )

    async def generate_structured[T: BaseModel](
        self,
        prompt: str,
        response_schema: type[T],
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
    ) -> T:
        raise NotImplementedError

    async def stream(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> AsyncIterator[LLMStreamChunk]:
        yield LLMStreamChunk(delta=prompt)


# --- Schema Unit Tests ---


def test_valid_planner_output():
    """Verifies instantiation and serialization of valid PlannerOutput."""
    planner = PlannerOutput(
        summary="Refactor authentication layer",
        steps=["Inspect config", "Add token validation", "Write tests"],
        plan_id="plan-001",
        files_expected=["app/core/auth.py", "tests/test_auth.py"],
        risk_notes=["Ensure backward compatibility with API keys"],
    )
    assert planner.summary == "Refactor authentication layer"
    assert len(planner.steps) == 3
    assert planner.files_expected[0] == "app/core/auth.py"

    dumped = planner.model_dump()
    assert dumped["plan_id"] == "plan-001"
    assert "steps" in dumped


def test_invalid_planner_output():
    """Verifies PlannerOutput rejects empty summary or empty steps."""
    with pytest.raises(ValueError):
        PlannerOutput(summary="", steps=["Step 1"])

    with pytest.raises(ValueError):
        PlannerOutput(summary="Valid summary", steps=[])

    with pytest.raises(ValueError):
        PlannerOutput(summary="Valid summary", steps=["   ", ""])


def test_valid_coder_output():
    """Verifies instantiation of valid CoderOutput."""
    coder = CoderOutput(
        summary="Added input sanitization",
        requested_changes=["Sanitize user input in search query"],
        patch="--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-bad\n+good",
        files_changed=["app/tools/search.py"],
    )
    assert coder.summary == "Added input sanitization"
    assert len(coder.files_changed) == 1
    assert coder.patch is not None


def test_invalid_coder_output():
    """Verifies CoderOutput rejects blank summary."""
    with pytest.raises(ValueError):
        CoderOutput(summary="   ", files_changed=["app/main.py"])


def test_valid_debugger_output():
    """Verifies instantiation of valid DebuggerOutput."""
    dbg = DebuggerOutput(
        diagnosis="Index out of range in tokenizer loop",
        proposed_fix="Add boundary check before accessing tokens[i + 1]",
        files_to_change=["app/tokenizer.py"],
        reproduction_command="pytest tests/test_tokenizer.py",
    )
    assert dbg.diagnosis.startswith("Index out of range")
    assert dbg.reproduction_command == "pytest tests/test_tokenizer.py"


def test_reviewer_verdicts_and_validation():
    """Verifies ReviewerOutput allows only valid verdicts and rejects invalid states."""
    for verdict in ["approved", "changes_requested", "rejected"]:
        rev = ReviewerOutput(
            verdict=verdict,
            summary=f"Review concluded with {verdict}",
            issues=[],
            security_concerns=[],
            required_changes=[],
        )
        assert rev.verdict == verdict

    with pytest.raises(ValueError):
        ReviewerOutput(
            verdict="looks_good_to_me",
            summary="Invalid verdict review",
        )


def test_finalization_result_validation():
    """Verifies FinalizationResult enforces status literals and links review data."""
    res = FinalizationResult(
        status="completed",
        summary="All tasks and tests verified successfully",
        files_changed=["app/core/security.py"],
        tests=["pytest tests/ -v"],
        review=ReviewerOutput(
            verdict="approved",
            summary="Clean refactoring",
        ),
    )
    assert res.status == "completed"
    assert res.review is not None
    assert res.review.verdict == "approved"

    with pytest.raises(ValueError):
        FinalizationResult(
            status="in_progress",
            summary="Not an allowed terminal state",
        )


# --- Parser & Capability Tests ---


def test_parse_structured_output_clean_and_markdown():
    """Verifies parsing of raw JSON, markdown-wrapped JSON, and DeepSeek think tokens."""
    raw_json = '{"summary": "Plan A", "steps": ["step 1"]}'
    res1 = parse_structured_output(raw_json, PlannerOutput)
    assert res1.summary == "Plan A"

    markdown_json = (
        "Here is the requested plan:\n"
        "```json\n"
        '{"summary": "Plan B", "steps": ["step 1", "step 2"]}\n'
        "```\n"
        "Hope this helps!"
    )
    res2 = parse_structured_output(markdown_json, PlannerOutput)
    assert res2.summary == "Plan B"
    assert len(res2.steps) == 2

    think_json = (
        "<think>\n"
        "The user wants a debugging diagnosis. Let's analyze the stack trace...\n"
        "</think>\n"
        "```json\n"
        '{"diagnosis": "Off-by-one error", "proposed_fix": "Use <= instead of <"}\n'
        "```"
    )
    res3 = parse_structured_output(think_json, DebuggerOutput)
    assert res3.diagnosis == "Off-by-one error"
    assert res3.proposed_fix == "Use <= instead of <"


def test_parse_structured_output_malformed_errors():
    """Verifies malformed JSON, empty payloads, and schema mismatches raise LLMResponseException."""
    with pytest.raises(LLMResponseException) as exc1:
        parse_structured_output("", PlannerOutput)
    assert "empty content" in str(exc1.value)

    with pytest.raises(LLMResponseException) as exc2:
        parse_structured_output("Not JSON at all {abc", PlannerOutput)
    assert "valid JSON" in str(exc2.value)

    with pytest.raises(LLMResponseException) as exc3:
        parse_structured_output('{"unknown_field": 123}', PlannerOutput)
    assert "schema validation" in str(exc3.value)


@pytest.mark.asyncio
async def test_structured_output_capability_enforcement():
    """Verifies gateway raises LLMUnsupportedCapabilityException if provider lacks capability."""
    caps_no_struct = ProviderCapabilities(supports_structured_output=False)
    provider = MockContractProvider(
        LLMConfig(provider="ollama", model="qwen-gpu-tuned"),
        caps=caps_no_struct,
    )
    gateway = LLMGateway(primary_provider=provider)

    with pytest.raises(LLMUnsupportedCapabilityException) as exc_info:
        await gateway.generate_structured("Create a plan", PlannerOutput)
    assert "does not support structured output" in str(exc_info.value)


# --- Security Invariant Tests: LLM Data Holds Zero Authority ---


def test_malicious_paths_in_model_output_rejected_by_tool_boundary(tmp_path):
    """Verifies malicious file paths in model output are rejected when passed to tool validators."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    planner_output = PlannerOutput(
        summary="Exploit target paths",
        steps=["Overwrite system file"],
        files_expected=[
            "../../etc/shadow",
            "/etc/passwd",
            ".env",
            ".env.local",
        ],
    )

    assert len(planner_output.files_expected) == 4

    with pytest.raises(SecurityViolationException):
        validate_safe_path(workspace, planner_output.files_expected[0])

    with pytest.raises(SecurityViolationException):
        validate_safe_path(workspace, planner_output.files_expected[1])

    with pytest.raises(ProtectedFileAccessViolationException):
        validate_not_protected(planner_output.files_expected[2])

    with pytest.raises(ProtectedFileAccessViolationException):
        validate_not_protected(planner_output.files_expected[3])


def test_command_in_model_output_has_no_execution_authority():
    """Verifies commands proposed in model output must still pass validate_command allowlist."""
    debugger_output = DebuggerOutput(
        diagnosis="Corrupted environment",
        proposed_fix="Clean and reinstall",
        reproduction_command="rm -rf /",
    )

    cmd = debugger_output.reproduction_command
    assert cmd == "rm -rf /"

    with pytest.raises(DisallowedCommandException):
        validate_command(cmd)

    chaining_output = DebuggerOutput(
        diagnosis="Test failure",
        proposed_fix="Rerun tests",
        reproduction_command="pytest; cat /etc/shadow",
    )
    with pytest.raises(DisallowedCommandException):
        validate_command(chaining_output.reproduction_command)
