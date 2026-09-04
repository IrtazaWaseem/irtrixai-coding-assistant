import tempfile
from pathlib import Path

import pytest

from app.core.exceptions import AppException, SecurityViolationException
from app.core.security import resolve_safe_path
from app.services.workspace_service import WorkspaceService


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir).resolve()

        (base / "src" / "utils").mkdir(parents=True, exist_ok=True)
        (base / ".git").mkdir(parents=True, exist_ok=True)
        (base / "node_modules" / "package").mkdir(parents=True, exist_ok=True)
        (base / "__pycache__").mkdir(parents=True, exist_ok=True)

        (base / "src" / "app.py").write_text("print('hello')", encoding="utf-8")
        (base / "src" / "utils" / "helper.py").write_text(
            "def help(): pass", encoding="utf-8"
        )
        (base / ".git" / "config").write_text("[core]", encoding="utf-8")
        (base / "node_modules" / "package" / "index.js").write_text(
            "module.exports = {}", encoding="utf-8"
        )
        (base / "__pycache__" / "app.cpython-312.pyc").write_bytes(b"\x00\x01")
        (base / "README.md").write_text("# Test Workspace", encoding="utf-8")

        yield base


def test_valid_path_resolution(temp_workspace):
    resolved = resolve_safe_path(temp_workspace, "src/app.py")
    assert resolved == (temp_workspace / "src" / "app.py").resolve()
    assert resolved.exists()


def test_path_traversal_parent_directory(temp_workspace):
    with pytest.raises(SecurityViolationException):
        resolve_safe_path(temp_workspace, "../outside.txt")


def test_path_traversal_deep_escape(temp_workspace):
    with pytest.raises(SecurityViolationException):
        resolve_safe_path(temp_workspace, "src/utils/../../../../etc/passwd")


def test_absolute_path_escape(temp_workspace):
    escape_target = Path(tempfile.gettempdir()).resolve().parent
    with pytest.raises(SecurityViolationException):
        resolve_safe_path(temp_workspace, str(escape_target))


def test_symlink_escape_rejected(temp_workspace):
    """Verifies that symlinks pointing to targets outside the workspace are blocked."""
    with tempfile.TemporaryDirectory() as external_dir:
        external_target = Path(external_dir).resolve() / "sensitive.txt"
        external_target.write_text("secret_host_content", encoding="utf-8")

        symlink_path = temp_workspace / "symlinked_secret.txt"
        try:
            symlink_path.symlink_to(external_target)
        except (OSError, NotImplementedError):
            pytest.skip(
                "Symlink creation requires elevated permissions on this host OS."
            )

        with pytest.raises(SecurityViolationException):
            resolve_safe_path(temp_workspace, "symlinked_secret.txt")


def test_nonexistent_workspace_build_tree():
    with pytest.raises(AppException) as exc_info:
        WorkspaceService.build_file_tree("/nonexistent/directory/path/12345")
    assert exc_info.value.status_code == 404


def test_ignored_directories_filtered_out(temp_workspace):
    tree, _, _ = WorkspaceService.build_file_tree(temp_workspace, max_depth=5)

    names = [node.name for node in tree]
    assert ".git" not in names
    assert "node_modules" not in names
    assert "__pycache__" not in names
    assert "src" in names
    assert "README.md" in names


def test_traversal_depth_limit(temp_workspace):
    tree_d1, _, _ = WorkspaceService.build_file_tree(temp_workspace, max_depth=1)
    src_node = next(n for n in tree_d1 if n.name == "src")
    assert src_node.children == []

    tree_d2, _, _ = WorkspaceService.build_file_tree(temp_workspace, max_depth=2)
    src_node_d2 = next(n for n in tree_d2 if n.name == "src")
    child_names = [c.name for c in src_node_d2.children]
    assert "app.py" in child_names
    assert "utils" in child_names
    utils_node = next(c for c in src_node_d2.children if c.name == "utils")
    assert utils_node.children == []
