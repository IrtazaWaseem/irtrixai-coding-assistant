import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.exceptions import (
    EntityNotFoundException,
    SecurityViolationException,
    ToolExecutionException,
)
from app.tools.git_tools import (
    get_diff,
    git_diff,
    git_status,
)


@pytest.fixture
def temp_git_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=str(root),
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=str(root),
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=str(root),
            check=True,
        )

        (root / "hello.txt").write_text("hello\nworld\n", encoding="utf-8")
        subprocess.run(["git", "add", "hello.txt"], cwd=str(root), check=True)
        subprocess.run(
            ["git", "commit", "-m", "initial commit"],
            cwd=str(root),
            check=True,
        )
        yield root


@pytest.fixture
def non_git_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir).resolve()


def test_git_status_clean(temp_git_workspace):
    res = git_status(workspace_root=temp_git_workspace)
    assert res.success is True
    assert res.output["is_clean"] is True
    assert res.output["modified"] == []
    assert res.output["untracked"] == []
    assert res.output["deleted"] == []
    assert res.output["staged"] == []
    assert res.output["branch"] == "main"


def test_git_status_modified_untracked_deleted_staged(temp_git_workspace):
    # Untracked file
    (temp_git_workspace / "new.txt").write_text("new content", encoding="utf-8")

    # Modified file
    (temp_git_workspace / "hello.txt").write_text("hello\nmodified world\n", encoding="utf-8")

    # Deleted file (create, commit, then delete on disk)
    (temp_git_workspace / "to_delete.txt").write_text("delete me", encoding="utf-8")
    subprocess.run(["git", "add", "to_delete.txt"], cwd=str(temp_git_workspace), check=True)
    subprocess.run(
        ["git", "commit", "-m", "add delete target"], cwd=str(temp_git_workspace), check=True
    )
    os.unlink(temp_git_workspace / "to_delete.txt")

    # Staged file
    (temp_git_workspace / "staged.txt").write_text("staged file", encoding="utf-8")
    subprocess.run(["git", "add", "staged.txt"], cwd=str(temp_git_workspace), check=True)

    res = git_status(workspace_root=temp_git_workspace)
    assert res.success is True
    assert res.output["is_clean"] is False
    assert "hello.txt" in res.output["modified"]
    assert "new.txt" in res.output["untracked"]
    assert "to_delete.txt" in res.output["deleted"]
    assert any(s["path"] == "staged.txt" and s["status"] == "A" for s in res.output["staged"])


def test_git_status_non_git_directory(non_git_workspace):
    res = git_status(workspace_root=non_git_workspace)
    assert res.success is False
    assert "not a git repository" in res.error.lower()

    with pytest.raises(ToolExecutionException):
        git_status(workspace_root=non_git_workspace, raise_on_error=True)


def test_git_diff_normal_and_file_specific(temp_git_workspace):
    (temp_git_workspace / "hello.txt").write_text("hello\nmodified world\n", encoding="utf-8")
    (temp_git_workspace / "other.txt").write_text("other text\n", encoding="utf-8")
    subprocess.run(["git", "add", "other.txt"], cwd=str(temp_git_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "add other"], cwd=str(temp_git_workspace), check=True)
    (temp_git_workspace / "other.txt").write_text("other text modified\n", encoding="utf-8")

    # Full unstaged diff
    full_diff = git_diff(workspace_root=temp_git_workspace)
    assert full_diff.success is True
    assert "diff --git a/hello.txt b/hello.txt" in full_diff.output
    assert "diff --git a/other.txt b/other.txt" in full_diff.output
    assert isinstance(full_diff.output, str)

    # File-specific diff
    file_diff = git_diff(file_path="hello.txt", workspace_root=temp_git_workspace)
    assert file_diff.success is True
    assert "hello.txt" in file_diff.output
    assert "other.txt" not in file_diff.output


def test_git_diff_nonexistent_and_traversal(temp_git_workspace):
    # Nonexistent file
    missing = git_diff(file_path="nonexistent.txt", workspace_root=temp_git_workspace)
    assert missing.success is False
    with pytest.raises(EntityNotFoundException):
        git_diff(
            file_path="nonexistent.txt", workspace_root=temp_git_workspace, raise_on_error=True
        )

    # Traversal escape
    bad_path = git_diff(file_path="../../etc/passwd", workspace_root=temp_git_workspace)
    assert bad_path.success is False
    with pytest.raises(SecurityViolationException):
        git_diff(
            file_path="../../etc/passwd", workspace_root=temp_git_workspace, raise_on_error=True
        )


def test_git_diff_path_beginning_with_dash_and_injection(temp_git_workspace):
    # Legitimate file starting with a dash
    dash_file = temp_git_workspace / "-dashfile.txt"
    dash_file.write_text("dash original\n", encoding="utf-8")
    subprocess.run(["git", "add", "--", "-dashfile.txt"], cwd=str(temp_git_workspace), check=True)
    subprocess.run(["git", "commit", "-m", "add dashfile"], cwd=str(temp_git_workspace), check=True)

    dash_file.write_text("dash modified\n", encoding="utf-8")
    res = git_diff(file_path="-dashfile.txt", workspace_root=temp_git_workspace)
    assert res.success is True
    assert "-dashfile.txt" in res.output
    assert "+dash modified" in res.output

    # Argument injection attempts
    leak_target = temp_git_workspace / "leak.txt"
    inject_res = git_diff(file_path="--output=leak.txt", workspace_root=temp_git_workspace)
    assert inject_res.success is False
    assert not leak_target.exists()


def test_git_diff_non_git_dir_and_oversized(temp_git_workspace, non_git_workspace):
    # Non-git directory
    res_non_git = git_diff(workspace_root=non_git_workspace)
    assert res_non_git.success is False
    assert "not a git repository" in res_non_git.error.lower()

    # Oversized diff truncation
    huge_content = "X" * (settings.MAX_TOOL_OUTPUT_BYTES + 5000)
    (temp_git_workspace / "hello.txt").write_text(huge_content, encoding="utf-8")
    res_huge = git_diff(workspace_root=temp_git_workspace)
    assert res_huge.success is True
    assert res_huge.metadata["truncated"] is True
    assert len(res_huge.output.encode("utf-8")) <= settings.MAX_TOOL_OUTPUT_BYTES


def test_get_diff_clean_unstaged_staged_and_oversized(temp_git_workspace):
    # Clean state
    clean_res = get_diff(workspace_root=temp_git_workspace)
    assert clean_res.success is True
    assert clean_res.output == ""

    # Unstaged diff
    (temp_git_workspace / "hello.txt").write_text("hello\nworking copy\n", encoding="utf-8")
    unstaged_res = get_diff(cached=False, workspace_root=temp_git_workspace)
    assert unstaged_res.success is True
    assert "+working copy" in unstaged_res.output

    staged_res = get_diff(cached=True, workspace_root=temp_git_workspace)
    assert staged_res.success is True
    assert staged_res.output == ""

    # Staged diff
    subprocess.run(["git", "add", "hello.txt"], cwd=str(temp_git_workspace), check=True)
    post_add_unstaged = get_diff(cached=False, workspace_root=temp_git_workspace)
    assert post_add_unstaged.output == ""

    post_add_staged = get_diff(cached=True, workspace_root=temp_git_workspace)
    assert post_add_staged.success is True
    assert "+working copy" in post_add_staged.output

    # Oversized staged diff
    huge_text = "L" * (settings.MAX_TOOL_OUTPUT_BYTES + 2000)
    (temp_git_workspace / "hello.txt").write_text(huge_text, encoding="utf-8")
    subprocess.run(["git", "add", "hello.txt"], cwd=str(temp_git_workspace), check=True)

    huge_staged = get_diff(cached=True, workspace_root=temp_git_workspace)
    assert huge_staged.success is True
    assert huge_staged.metadata["truncated"] is True
    assert len(huge_staged.output.encode("utf-8")) <= settings.MAX_TOOL_OUTPUT_BYTES
