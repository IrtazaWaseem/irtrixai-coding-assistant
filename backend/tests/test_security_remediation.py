import os
import tempfile
from pathlib import Path

import pytest

from app.core.exceptions import (
    ProtectedFileAccessViolationException,
    SecurityViolationException,
)
from app.tools.file_tools import (
    apply_patch,
    list_files,
    read_file,
    search_code,
    write_file,
)
from app.tools.validators import truncate_output, validate_file_size


@pytest.fixture
def remediation_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        (root / "src").mkdir()
        (root / "src" / "main.py").write_text(
            "def run():\n    return 'safe code'\n", encoding="utf-8"
        )
        (root / "normal.txt").write_text("ordinary text file", encoding="utf-8")
        (root / ".env").write_text(
            "DB_PASSWORD=secret_in_root_env\nAPI_KEY=key123\n", encoding="utf-8"
        )
        (root / ".env.production").write_text(
            "PROD_SECRET=production_password\n", encoding="utf-8"
        )
        yield root


def test_issue_1_search_code_symlink_escape(remediation_env):
    """Verifies that search_code cannot escape the workspace via file symlinks."""
    with tempfile.TemporaryDirectory() as outside_dir:
        outside_path = Path(outside_dir).resolve() / "external_secret.txt"
        outside_path.write_text("DB_PASSWORD=supersecret123", encoding="utf-8")

        symlink_target = remediation_env / "leaked.txt"
        try:
            os.symlink(outside_path, symlink_target)
        except OSError:
            pytest.skip("Host OS requires elevation to create symlinks.")

        # 1. External secret must NOT be searchable through symlink
        res = search_code("supersecret123", workspace_root=remediation_env)
        assert res.success is True
        assert res.output["total_matches"] == 0

        # 2. Normal workspace files remain fully searchable
        safe_res = search_code("safe code", workspace_root=remediation_env)
        assert safe_res.success is True
        assert safe_res.output["total_matches"] == 1
        assert safe_res.output["matches"][0]["file_path"] == "src/main.py"


def test_issue_2_protected_files_read_rejected(remediation_env):
    """Verifies that protected files (.env, .env.*) cannot be read directly."""
    res_env = read_file(".env", workspace_root=remediation_env)
    assert res_env.success is False
    assert "is protected" in res_env.error

    with pytest.raises(ProtectedFileAccessViolationException):
        read_file(".env", workspace_root=remediation_env, raise_on_error=True)

    res_prod = read_file(".env.production", workspace_root=remediation_env)
    assert res_prod.success is False
    assert "is protected" in res_prod.error

    # Normal file reads cleanly
    normal = read_file("src/main.py", workspace_root=remediation_env)
    assert normal.success is True
    assert "safe code" in normal.output["content"]


def test_issue_2_protected_files_write_and_patch_rejected(remediation_env):
    """Verifies write_file and apply_patch reject mutating protected files."""
    write_res = write_file(".env", "MALICIOUS=true", workspace_root=remediation_env)
    assert write_res.success is False
    assert "is protected" in write_res.error
    assert "MALICIOUS=true" not in (remediation_env / ".env").read_text()

    patch = "<<<<<<< SEARCH\nAPI_KEY=key123\n=======\nAPI_KEY=hacked\n>>>>>>> REPLACE"
    patch_res = apply_patch(".env", patch, workspace_root=remediation_env)
    assert patch_res.success is False
    assert "is protected" in patch_res.error
    assert "API_KEY=hacked" not in (remediation_env / ".env").read_text()


def test_issue_2_protected_files_search_and_symlink(remediation_env):
    """Verifies protected files are excluded from search and internal symlink access."""
    # Search exclusion
    search_res = search_code("secret_in_root_env", workspace_root=remediation_env)
    assert search_res.success is True
    assert search_res.output["total_matches"] == 0

    # Symlink targeting protected file inside workspace
    link_env = remediation_env / "symlink_to_env.txt"
    try:
        os.symlink(remediation_env / ".env", link_env)
    except OSError:
        pytest.skip("Host OS requires elevation to create symlinks.")

    read_symlink = read_file("symlink_to_env.txt", workspace_root=remediation_env)
    assert read_symlink.success is False
    assert "is protected" in read_symlink.error


def test_issue_3_list_files_survives_bad_symlink(remediation_env):
    """Verifies list_files skips unsafe escaping symlinks without failing the listing."""
    with tempfile.TemporaryDirectory() as outside_dir:
        outside_path = Path(outside_dir).resolve() / "secret.txt"
        outside_path.write_text("external", encoding="utf-8")

        bad_link = remediation_env / "escaping_symlink.txt"
        try:
            os.symlink(outside_path, bad_link)
        except OSError:
            pytest.skip("Host OS requires elevation to create symlinks.")

        res = list_files(".", recursive=True, workspace_root=remediation_env)
        assert res.success is True
        paths = [e["path"] for e in res.output["entries"]]
        assert "normal.txt" in paths
        assert "src/main.py" in paths
        assert "escaping_symlink.txt" not in paths


def test_issue_4_security_error_does_not_leak_absolute_workspace_path(remediation_env):
    """Verifies error responses do not leak host absolute directory paths."""
    res = read_file("../../secret.txt", workspace_root=remediation_env)
    assert res.success is False
    assert str(remediation_env) not in res.error
    assert str(remediation_env.resolve()) not in res.error
    assert "escapes workspace boundary" in res.error

    with pytest.raises(SecurityViolationException) as exc_info:
        read_file(
            "../../secret.txt", workspace_root=remediation_env, raise_on_error=True
        )
    assert str(remediation_env) not in str(exc_info.value)


def test_issue_7_call_time_settings_resolution(remediation_env):
    """Verifies validators evaluate settings limits at call time."""
    test_file = remediation_env / "normal.txt"
    file_size = test_file.stat().st_size

    # Explicit override takes precedence
    with pytest.raises(Exception) as exc:
        validate_file_size(test_file, max_bytes=file_size - 1)
    assert "exceeds limit" in str(exc.value).lower()

    # Truncate output respects dynamic limit parameter
    content, truncated = truncate_output("1234567890", max_bytes=5)
    assert truncated is True
    assert content == "12345"


def test_issue_8_broken_symlink_handling(remediation_env):
    """Verifies broken symlinks do not crash filesystem tools."""
    broken_link = remediation_env / "broken.txt"
    try:
        os.symlink(remediation_env / "nonexistent_target.txt", broken_link)
    except OSError:
        pytest.skip("Host OS requires elevation to create symlinks.")

    listing = list_files(".", workspace_root=remediation_env)
    assert listing.success is True

    res = read_file("broken.txt", workspace_root=remediation_env)
    assert res.success is False
