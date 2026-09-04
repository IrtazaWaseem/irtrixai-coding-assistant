import tempfile
from pathlib import Path

import pytest

from app.core.exceptions import (
    AppException,
    EntityNotFoundException,
    FileSizeLimitExceededException,
    SecurityViolationException,
    ToolExecutionException,
)
from app.tools.base import ToolResult
from app.tools.validators import (
    truncate_output,
    validate_allowed_operation,
    validate_content_size,
    validate_file_size,
    validate_safe_path,
    validate_workspace_dir,
)


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir).resolve()
        (base / "src").mkdir()
        (base / "src" / "main.py").write_text("print('hello')", encoding="utf-8")
        (base / "data.bin").write_bytes(b"\x00\x01\x02\x03\x04")
        yield base


def test_tool_result_contracts():
    ok_res = ToolResult.ok(
        tool_name="test_tool",
        output={"lines": 10},
        metadata={"latency_ms": 5},
    )
    assert ok_res.success is True
    assert ok_res.tool_name == "test_tool"
    assert ok_res.output == {"lines": 10}
    assert ok_res.metadata["latency_ms"] == 5
    assert ok_res.error is None

    fail_res = ToolResult.fail(
        tool_name="test_tool",
        error="File locked",
        metadata={"code": 423},
    )
    assert fail_res.success is False
    assert fail_res.tool_name == "test_tool"
    assert fail_res.error == "File locked"
    assert fail_res.output is None
    assert fail_res.metadata["code"] == 423


def test_validate_workspace_dir(temp_workspace):
    resolved = validate_workspace_dir(temp_workspace)
    assert resolved == temp_workspace

    with pytest.raises(AppException) as exc_info:
        validate_workspace_dir("/nonexistent/directory_xyz_12345")
    assert exc_info.value.status_code == 404

    regular_file = temp_workspace / "src" / "main.py"
    with pytest.raises(AppException) as exc_info:
        validate_workspace_dir(regular_file)
    assert exc_info.value.status_code == 400


def test_validate_safe_path_boundaries(temp_workspace):
    safe = validate_safe_path(temp_workspace, "src/main.py", must_exist=True)
    assert safe == (temp_workspace / "src" / "main.py").resolve()

    safe_new = validate_safe_path(temp_workspace, "src/new_file.py", must_exist=False)
    assert safe_new == (temp_workspace / "src" / "new_file.py").resolve()

    with pytest.raises(EntityNotFoundException):
        validate_safe_path(temp_workspace, "src/nonexistent.py", must_exist=True)

    with pytest.raises(SecurityViolationException):
        validate_safe_path(temp_workspace, "../outside.txt")

    with pytest.raises(SecurityViolationException):
        validate_safe_path(temp_workspace, "src/../../outside.txt")

    system_root = Path(tempfile.gettempdir()).resolve().parent
    with pytest.raises(SecurityViolationException):
        validate_safe_path(temp_workspace, str(system_root))


def test_validate_safe_path_symlink_escapes(temp_workspace):
    with tempfile.TemporaryDirectory() as outside_dir:
        outside_file = Path(outside_dir).resolve() / "secret.env"
        outside_file.write_text("DB_PASS=123", encoding="utf-8")

        symlink_file = temp_workspace / "symlink_secret.env"
        try:
            symlink_file.symlink_to(outside_file)
        except (OSError, NotImplementedError):
            pytest.skip("Host OS does not permit non-elevated symlink creation.")

        with pytest.raises(SecurityViolationException):
            validate_safe_path(temp_workspace, "symlink_secret.env")


def test_validate_file_size(temp_workspace):
    target_file = temp_workspace / "src" / "main.py"
    size = validate_file_size(target_file, max_bytes=100)
    assert size == len("print('hello')")

    with pytest.raises(FileSizeLimitExceededException):
        validate_file_size(target_file, max_bytes=5)


def test_validate_content_size():
    valid_size = validate_content_size("small payload", max_bytes=50)
    assert valid_size == len("small payload")

    with pytest.raises(FileSizeLimitExceededException):
        validate_content_size("huge payload content", max_bytes=5)


def test_truncate_output():
    short_text = "clean output"
    res, truncated = truncate_output(short_text, max_bytes=50)
    assert res == short_text
    assert truncated is False

    long_text = "A" * 100
    res, truncated = truncate_output(long_text, max_bytes=10)
    assert len(res.encode("utf-8")) == 10
    assert truncated is True


def test_validate_allowed_operation():
    op = validate_allowed_operation("read", allowed={"read", "write"})
    assert op == "read"

    with pytest.raises(ToolExecutionException):
        validate_allowed_operation("delete", allowed={"read", "write"})
