import tempfile
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.exceptions import (
    EntityNotFoundException,
    FileSizeLimitExceededException,
    SecurityViolationException,
    ToolExecutionException,
)
from app.tools.file_tools import (
    apply_patch,
    list_files,
    read_file,
    search_code,
    write_file,
)


@pytest.fixture
def workspace_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        (root / "src").mkdir()
        (root / "src" / "main.py").write_text(
            "def main():\n    return 'production ready'\n", encoding="utf-8"
        )
        (root / "src" / "helpers.py").write_text(
            "def add(a, b):\n    return a + b\n", encoding="utf-8"
        )
        (root / "empty.txt").write_text("", encoding="utf-8")
        (root / "binary.bin").write_bytes(b"\x00\x01\x02\x03\x04")
        (root / "large.txt").write_text("A" * 200, encoding="utf-8")
        (root / ".git").mkdir()
        (root / ".git" / "config").write_text("git config", encoding="utf-8")
        yield root


def test_list_files_shallow_and_recursive(workspace_env):
    shallow = list_files(".", recursive=False, workspace_root=workspace_env)
    assert shallow.success is True
    paths = [e["path"] for e in shallow.output["entries"]]
    assert "src" in paths
    assert "empty.txt" in paths
    assert "src/main.py" not in paths

    rec = list_files(".", recursive=True, max_depth=2, workspace_root=workspace_env)
    assert rec.success is True
    rec_paths = [e["path"] for e in rec.output["entries"]]
    assert "src/main.py" in rec_paths
    assert ".git" not in rec_paths


def test_list_files_traversal_and_invalid_dir(workspace_env):
    traversal = list_files("../", workspace_root=workspace_env)
    assert traversal.success is False
    assert "escapes workspace" in traversal.error.lower()

    with pytest.raises(SecurityViolationException):
        list_files("../", workspace_root=workspace_env, raise_on_error=True)

    nonexistent = list_files("missing_dir", workspace_root=workspace_env)
    assert nonexistent.success is False


def test_read_file_normal_empty_and_ranges(workspace_env):
    res = read_file("src/main.py", workspace_root=workspace_env)
    assert res.success is True
    assert res.output["total_lines"] == 2
    assert "production ready" in res.output["content"]

    empty_res = read_file("empty.txt", workspace_root=workspace_env)
    assert empty_res.success is True
    assert empty_res.output["content"] == ""
    assert empty_res.output["total_lines"] == 0

    range_res = read_file(
        "src/main.py", start_line=2, end_line=2, workspace_root=workspace_env
    )
    assert range_res.success is True
    assert range_res.output["content"] == "    return 'production ready'"
    assert range_res.output["start_line"] == 2
    assert range_res.output["end_line"] == 2


def test_read_file_guards_and_exceptions(workspace_env):
    missing = read_file("missing.py", workspace_root=workspace_env)
    assert missing.success is False
    with pytest.raises(EntityNotFoundException):
        read_file("missing.py", workspace_root=workspace_env, raise_on_error=True)

    dir_target = read_file("src", workspace_root=workspace_env)
    assert dir_target.success is False
    assert "directory" in dir_target.error.lower()

    bin_target = read_file("binary.bin", workspace_root=workspace_env)
    assert bin_target.success is False
    assert "binary" in bin_target.error.lower()

    traversal = read_file("../../etc/passwd", workspace_root=workspace_env)
    assert traversal.success is False
    with pytest.raises(SecurityViolationException):
        read_file("../../etc/passwd", workspace_root=workspace_env, raise_on_error=True)

    invalid_range = read_file(
        "src/main.py", start_line=5, end_line=2, workspace_root=workspace_env
    )
    assert invalid_range.success is False
    with pytest.raises(ToolExecutionException):
        read_file(
            "src/main.py",
            start_line=5,
            end_line=2,
            workspace_root=workspace_env,
            raise_on_error=True,
        )


def test_read_file_oversized_guard(workspace_env):
    oversized_file = workspace_env / "oversized.txt"
    oversized_file.write_text(
        "B" * (settings.MAX_READ_FILE_BYTES + 1024), encoding="utf-8"
    )

    res = read_file("oversized.txt", workspace_root=workspace_env)
    assert res.success is False
    assert "exceeds limit" in res.error.lower()


def test_search_code_literal_and_redos_safety(workspace_env):
    res = search_code("production ready", workspace_root=workspace_env)
    assert res.success is True
    assert res.output["total_matches"] == 1
    assert res.output["matches"][0]["file_path"] == "src/main.py"

    py_res = search_code("return", file_pattern="*.py", workspace_root=workspace_env)
    assert py_res.success is True
    assert len(py_res.output["matches"]) == 2

    malicious_pattern = "((((a+)+)+)+)$"
    safe_run = search_code(malicious_pattern, workspace_root=workspace_env)
    assert safe_run.success is True
    assert safe_run.output["total_matches"] == 0

    empty_q = search_code("", workspace_root=workspace_env)
    assert empty_q.success is False


def test_write_file_atomic_and_traversal(workspace_env):
    new_path = "src/sub/nested/file.py"
    write_res = write_file(new_path, "secret = 123\n", workspace_root=workspace_env)
    assert write_res.success is True
    assert write_res.output["is_new_file"] is True
    assert (workspace_env / "src" / "sub" / "nested" / "file.py").exists()

    overwrite_res = write_file(new_path, "secret = 456\n", workspace_root=workspace_env)
    assert overwrite_res.success is True
    assert overwrite_res.output["is_new_file"] is False
    assert (
        workspace_env / "src" / "sub" / "nested" / "file.py"
    ).read_text() == "secret = 456\n"

    bad_write = write_file("../escaped.txt", "payload", workspace_root=workspace_env)
    assert bad_write.success is False
    with pytest.raises(SecurityViolationException):
        write_file(
            "../escaped.txt",
            "payload",
            workspace_root=workspace_env,
            raise_on_error=True,
        )


def test_write_file_oversized_payload_rejected(workspace_env):
    huge_content = "C" * (settings.MAX_READ_FILE_BYTES + 1024)
    res = write_file("huge.txt", huge_content, workspace_root=workspace_env)
    assert res.success is False
    assert "exceeds limit" in res.error.lower()
    assert not (workspace_env / "huge.txt").exists()


def test_apply_patch_unified_and_rollback(workspace_env):
    target = "src/helpers.py"

    unified_patch = (
        "--- a/src/helpers.py\n"
        "+++ b/src/helpers.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def add(a, b):\n"
        "-    return a + b\n"
        "+    return a * b\n"
    )
    ok_patch = apply_patch(target, unified_patch, workspace_root=workspace_env)
    assert ok_patch.success is True
    assert "return a * b" in (workspace_env / target).read_text()

    bad_patch = (
        "--- a/src/helpers.py\n"
        "+++ b/src/helpers.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def non_existent_function():\n"
        "-    return 0\n"
        "+    return 1\n"
    )
    curr_content = (workspace_env / target).read_text()
    fail_patch = apply_patch(target, bad_patch, workspace_root=workspace_env)
    assert fail_patch.success is False
    assert fail_patch.metadata["original_preserved"] is True
    assert (workspace_env / target).read_text() == curr_content


def test_apply_patch_search_replace_and_oversized(workspace_env):
    target = "src/main.py"
    sr_patch = (
        "<<<<<<< SEARCH\n"
        "    return 'production ready'\n"
        "=======\n"
        "    return 'fully tested'\n"
        ">>>>>>> REPLACE"
    )
    ok_sr = apply_patch(target, sr_patch, workspace_root=workspace_env)
    assert ok_sr.success is True
    assert "fully tested" in (workspace_env / target).read_text()

    huge_patch = "A" * (settings.MAX_PATCH_SIZE + 10)
    oversized = apply_patch(target, huge_patch, workspace_root=workspace_env)
    assert oversized.success is False
    with pytest.raises(FileSizeLimitExceededException):
        apply_patch(
            target, huge_patch, workspace_root=workspace_env, raise_on_error=True
        )
