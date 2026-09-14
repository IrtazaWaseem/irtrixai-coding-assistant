import os
import subprocess
from pathlib import Path

from app.core.config import settings
from app.core.exceptions import (
    EntityNotFoundException,
    SecurityViolationException,
    ToolExecutionException,
)
from app.tools.base import ToolResult
from app.tools.validators import (
    truncate_output,
    validate_safe_path,
    validate_workspace_dir,
)

SAFE_GIT_ENV = {
    **os.environ,
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_PAGER": "cat",
    "PAGER": "cat",
    "GIT_OPTIONAL_LOCKS": "0",
}


def git_status(
    directory: str | None = None,
    workspace_root: Path | str | None = None,
    raise_on_error: bool = False,
) -> ToolResult:
    """Executes non-interactive git status and returns structured status dictionary with branch and staged details."""
    try:
        ws_dir = validate_workspace_dir(workspace_root)
        target_dir = ws_dir
        if directory:
            target_dir = validate_safe_path(ws_dir, directory)

        if not (target_dir / ".git").is_dir() and not (ws_dir / ".git").is_dir():
            err_msg = f"Directory '{target_dir}' is not a git repository."
            if raise_on_error:
                raise ToolExecutionException(err_msg)
            return ToolResult(
                tool_name="git_status",
                success=False,
                error=err_msg,
            )

        # Get current branch
        branch_res = subprocess.run(
            ["git", "--no-pager", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(target_dir),
            capture_output=True,
            text=True,
            timeout=5,
            stdin=subprocess.DEVNULL,
            env=SAFE_GIT_ENV,
        )
        branch = branch_res.stdout.strip() if branch_res.returncode == 0 else "main"

        cmd = ["git", "--no-pager", "status", "--porcelain=v1"]
        res = subprocess.run(
            cmd,
            cwd=str(target_dir),
            capture_output=True,
            text=True,
            timeout=10,
            stdin=subprocess.DEVNULL,
            env=SAFE_GIT_ENV,
        )

        if res.returncode != 0:
            err_msg = res.stderr.strip() or "Git status failed."
            if raise_on_error:
                raise ToolExecutionException(err_msg)
            return ToolResult(
                tool_name="git_status",
                success=False,
                error=err_msg,
            )

        lines = res.stdout.splitlines()
        modified = []
        untracked = []
        deleted = []
        staged = []

        for line in lines:
            if len(line) < 3:
                continue
            xy = line[:2]
            file_path = line[3:].strip()

            # Staged files carry index status in xy[0]
            if xy[0] in ("M", "A", "D", "R", "C"):
                staged.append({"path": file_path, "status": xy[0]})

            # Working tree status in xy[1]
            if xy[1] == "M":
                modified.append(file_path)
            elif xy[1] == "D":
                deleted.append(file_path)
            elif xy == "??":
                untracked.append(file_path)

        is_clean = not (modified or untracked or deleted or staged)
        status_dict = {
            "branch": branch,
            "is_clean": is_clean,
            "modified": modified,
            "untracked": untracked,
            "deleted": deleted,
            "staged": staged,
        }

        return ToolResult(
            tool_name="git_status",
            success=True,
            output=status_dict,
            metadata={"directory": str(target_dir), "is_clean": is_clean},
        )
    except SecurityViolationException:
        if raise_on_error:
            raise
        return ToolResult(
            tool_name="git_status", success=False, error="Security violation detected."
        )
    except ToolExecutionException:
        if raise_on_error:
            raise
        return ToolResult(tool_name="git_status", success=False, error="Tool execution failed.")
    except Exception as err:
        err_msg = f"git_status failed: {err}"
        if raise_on_error:
            raise ToolExecutionException(err_msg) from err
        return ToolResult(
            tool_name="git_status",
            success=False,
            error=err_msg,
        )


def git_diff(
    file_path: str | None = None,
    cached: bool = False,
    workspace_root: Path | str | None = None,
    raise_on_error: bool = False,
) -> ToolResult:
    """Executes non-interactive git diff with proper path separation, error raising, and truncation metadata."""
    try:
        ws_dir = validate_workspace_dir(workspace_root)

        if not (ws_dir / ".git").is_dir():
            err_msg = f"Directory '{ws_dir}' is not a git repository."
            if raise_on_error:
                raise ToolExecutionException(err_msg)
            return ToolResult(
                tool_name="git_diff",
                success=False,
                error=err_msg,
            )

        cmd = ["git", "--no-pager", "diff"]
        if cached:
            cmd.append("--cached")

        if file_path:
            norm = file_path.strip()
            if not norm or norm == "/dev/null":
                err_msg = f"Invalid file path: '{file_path}'"
                if raise_on_error:
                    raise ToolExecutionException(err_msg)
                return ToolResult(
                    tool_name="git_diff",
                    success=False,
                    error=err_msg,
                )

            safe_target = validate_safe_path(ws_dir, norm)
            if not safe_target.exists():
                err_msg = f"File path '{file_path}' does not exist in workspace."
                if raise_on_error:
                    raise EntityNotFoundException(file_path, err_msg)
                return ToolResult(
                    tool_name="git_diff",
                    success=False,
                    error=err_msg,
                )

            cmd.extend(["--", norm])

        res = subprocess.run(
            cmd,
            cwd=str(ws_dir),
            capture_output=True,
            text=True,
            timeout=10,
            stdin=subprocess.DEVNULL,
            env=SAFE_GIT_ENV,
        )

        if res.returncode != 0:
            err_msg = res.stderr.strip() or "Git diff failed."
            if raise_on_error:
                raise ToolExecutionException(err_msg)
            return ToolResult(
                tool_name="git_diff",
                success=False,
                error=err_msg,
            )

        diff_out = res.stdout
        max_bytes = getattr(settings, "MAX_TOOL_OUTPUT_BYTES", 51_200)
        trunc_raw = truncate_output(diff_out, max_bytes=max_bytes)
        bounded_out = trunc_raw[0] if isinstance(trunc_raw, (tuple, list)) else str(trunc_raw)
        is_truncated = (
            trunc_raw[1]
            if isinstance(trunc_raw, (tuple, list)) and len(trunc_raw) > 1
            else (len(diff_out.encode("utf-8")) > max_bytes)
        )

        return ToolResult(
            tool_name="git_diff",
            success=True,
            output=bounded_out,
            metadata={
                "file_path": file_path,
                "cached": cached,
                "truncated": is_truncated,
            },
        )
    except SecurityViolationException:
        if raise_on_error:
            raise
        return ToolResult(tool_name="git_diff", success=False, error="Security violation detected.")
    except EntityNotFoundException:
        if raise_on_error:
            raise
        return ToolResult(tool_name="git_diff", success=False, error="Entity not found.")
    except ToolExecutionException:
        if raise_on_error:
            raise
        return ToolResult(tool_name="git_diff", success=False, error="Tool execution failed.")
    except Exception as err:
        err_msg = f"git_diff failed: {err}"
        if raise_on_error:
            raise ToolExecutionException(err_msg) from err
        return ToolResult(
            tool_name="git_diff",
            success=False,
            error=err_msg,
        )


def get_diff(
    workspace_root: Path | str | None = None,
    file_path: str | None = None,
    staged: bool = False,
    cached: bool = False,
    raise_on_error: bool = False,
) -> ToolResult:
    """Safely retrieves git diff with truncation metadata and error raising support."""
    return git_diff(
        file_path=file_path,
        cached=(staged or cached),
        workspace_root=workspace_root,
        raise_on_error=raise_on_error,
    )
