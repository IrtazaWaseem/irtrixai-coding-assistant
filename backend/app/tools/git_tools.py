import os
import subprocess
from pathlib import Path

from app.core.config import settings
from app.core.exceptions import (
    EntityNotFoundException,
    ExecutionTimeoutException,
    ToolExecutionException,
)
from app.tools.base import ToolResult
from app.tools.schemas import GitStagedItem, GitStatusOutput
from app.tools.validators import (
    truncate_output,
    validate_safe_path,
    validate_workspace_dir,
)


def _handle_git_error(
    tool_name: str,
    exc: Exception,
    raise_on_error: bool,
    metadata: dict | None = None,
) -> ToolResult:
    if raise_on_error:
        raise exc
    meta = metadata or {}
    meta["error_type"] = type(exc).__name__
    if hasattr(exc, "details"):
        meta["details"] = exc.details
    return ToolResult.fail(tool_name=tool_name, error=str(exc), metadata=meta)


def _execute_git_cmd(
    cmd: list[str],
    workspace_root: Path,
    timeout_seconds: int = settings.COMMAND_TIMEOUT_SECONDS,
) -> tuple[int, str, str]:
    """Deterministically executes a pre-tokenized Git command without shell=True."""
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
    }
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workspace_root),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
            env=env,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as err:
        raise ExecutionTimeoutException(
            timeout_seconds=timeout_seconds, command=" ".join(cmd)
        ) from err


def _verify_git_repo(base_dir: Path) -> None:
    """Verifies that the target workspace root is an initialized Git repository."""
    code, stdout, stderr = _execute_git_cmd(
        ["git", "-C", str(base_dir), "rev-parse", "--is-inside-work-tree"],
        workspace_root=base_dir,
    )
    if code != 0 or stdout.strip() != "true":
        raise ToolExecutionException(
            f"Workspace '{base_dir}' is not a Git repository.",
            details={"workspace": str(base_dir), "error": stderr.strip()},
        )


def git_status(
    workspace_root: str | Path | None = None,
    raise_on_error: bool = False,
) -> ToolResult:
    """Returns deterministic status information about modified, untracked, deleted, and staged files."""
    try:
        base_dir = validate_workspace_dir(workspace_root)
        _verify_git_repo(base_dir)

        code, stdout, stderr = _execute_git_cmd(
            ["git", "-C", str(base_dir), "status", "--porcelain=v1", "-b"],
            workspace_root=base_dir,
        )
        if code != 0:
            raise ToolExecutionException(f"git status failed: {stderr.strip() or stdout.strip()}")

        lines = stdout.splitlines()
        branch = "HEAD"
        modified: list[str] = []
        untracked: list[str] = []
        deleted: list[str] = []
        staged: list[GitStagedItem] = []

        for line in lines:
            if line.startswith("## "):
                branch_part = line[3:].split("...")[0].strip()
                if "No commits yet on " in branch_part:
                    branch = branch_part.replace("No commits yet on ", "").strip()
                elif "Initial commit on " in branch_part:
                    branch = branch_part.replace("Initial commit on ", "").strip()
                else:
                    branch = branch_part
                continue

            if len(line) < 4:
                continue

            x, y = line[0], line[1]
            path_str = line[3:].strip()
            if " -> " in path_str:
                path_str = path_str.split(" -> ")[1]
            path_str = path_str.replace("\\", "/")

            if x == "?" and y == "?":
                untracked.append(path_str)
                continue

            if x in {"M", "A", "D", "R", "C"}:
                staged.append(GitStagedItem(path=path_str, status=x))

            if y == "M":
                modified.append(path_str)
            elif y == "D":
                deleted.append(path_str)

        modified = sorted(list(set(modified)))
        untracked = sorted(list(set(untracked)))
        deleted = sorted(list(set(deleted)))
        staged.sort(key=lambda s: (s.path, s.status))

        is_clean = not (modified or untracked or deleted or staged)

        result_data = GitStatusOutput(
            branch=branch,
            is_clean=is_clean,
            modified=modified,
            untracked=untracked,
            deleted=deleted,
            staged=staged,
        )
        return ToolResult.ok(tool_name="git_status", output=result_data.model_dump())
    except Exception as err:
        return _handle_git_error("git_status", err, raise_on_error)


def git_diff(
    file_path: str | None = None,
    workspace_root: str | Path | None = None,
    raise_on_error: bool = False,
) -> ToolResult:
    """Returns the unstaged working tree diff, optionally bounded to a specific file."""
    try:
        base_dir = validate_workspace_dir(workspace_root)
        _verify_git_repo(base_dir)

        cmd = ["git", "-C", str(base_dir), "diff"]

        rel_path: str | None = None
        if file_path is not None:
            safe_path = validate_safe_path(base_dir, file_path, must_exist=False)
            rel_path = str(safe_path.relative_to(base_dir)).replace("\\", "/")

            if not safe_path.exists():
                code, stdout, _ = _execute_git_cmd(
                    ["git", "-C", str(base_dir), "ls-files", "--", rel_path],
                    workspace_root=base_dir,
                )
                if code != 0 or not stdout.strip():
                    raise EntityNotFoundException("File", file_path)

            cmd.extend(["--", rel_path])

        code, stdout, stderr = _execute_git_cmd(cmd, workspace_root=base_dir)
        if code != 0:
            raise ToolExecutionException(f"git diff failed: {stderr.strip() or stdout.strip()}")

        content, truncated = truncate_output(stdout, max_bytes=settings.MAX_TOOL_OUTPUT_BYTES)
        metadata = {
            "truncated": truncated,
            "byte_count": len(content.encode("utf-8")),
            "file_path": rel_path,
        }
        return ToolResult.ok(tool_name="git_diff", output=content, metadata=metadata)
    except Exception as err:
        return _handle_git_error("git_diff", err, raise_on_error)


def get_diff(
    cached: bool = False,
    workspace_root: str | Path | None = None,
    raise_on_error: bool = False,
) -> ToolResult:
    """Returns the complete unstaged diff (cached=False) or staged diff (cached=True)."""
    try:
        base_dir = validate_workspace_dir(workspace_root)
        _verify_git_repo(base_dir)

        cmd = ["git", "-C", str(base_dir), "diff"]
        if cached:
            cmd.append("--cached")

        code, stdout, stderr = _execute_git_cmd(cmd, workspace_root=base_dir)
        if code != 0:
            raise ToolExecutionException(f"git diff failed: {stderr.strip() or stdout.strip()}")

        content, truncated = truncate_output(stdout, max_bytes=settings.MAX_TOOL_OUTPUT_BYTES)
        metadata = {
            "cached": cached,
            "truncated": truncated,
            "byte_count": len(content.encode("utf-8")),
        }
        return ToolResult.ok(tool_name="get_diff", output=content, metadata=metadata)
    except Exception as err:
        return _handle_git_error("get_diff", err, raise_on_error)
