from pathlib import Path

from app.core.config import settings
from app.core.exceptions import (
    ContainerTimeoutException,
    DisallowedCommandException,
    ProtectedFileAccessViolationException,
    SecurityViolationException,
    ToolExecutionException,
)
from app.services.execution_service import ExecutionService
from app.tools.base import ToolResult
from app.tools.schemas import RunCommandOutput
from app.tools.validators import (
    validate_safe_path,
    validate_workspace_dir,
)


def run_command(
    command: str,
    relative_directory: str = ".",
    workspace_root: str | Path | None = None,
    timeout_seconds: int | None = None,
    raise_on_error: bool = False,
    image: str | None = None,
) -> ToolResult:
    """Executes an allowlisted command securely inside an ephemeral Docker sandbox."""
    effective_timeout = (
        timeout_seconds if timeout_seconds is not None else settings.SANDBOX_TIMEOUT_SECONDS
    )
    try:
        base_dir = validate_workspace_dir(workspace_root)
        safe_target_dir = validate_safe_path(base_dir, relative_directory, must_exist=True)

        if not safe_target_dir.is_dir():
            raise ToolExecutionException(
                f"Relative path '{relative_directory}' is not a directory."
            )

        if effective_timeout < 1:
            raise ToolExecutionException("timeout_seconds must be at least 1.")

        service = ExecutionService()
        result_dict = service.execute_in_sandbox(
            command=command,
            workspace_path=base_dir,
            timeout_seconds=effective_timeout,
            image=image,
        )

        output_data = RunCommandOutput(**result_dict)
        return ToolResult.ok(tool_name="run_command", output=output_data.model_dump())

    except (
        SecurityViolationException,
        ProtectedFileAccessViolationException,
        DisallowedCommandException,
    ) as err:
        if raise_on_error:
            raise
        return ToolResult.fail(
            tool_name="run_command",
            error=str(err),
            metadata={"security_violation": True, "error_type": type(err).__name__},
        )
    except ContainerTimeoutException:
        if raise_on_error:
            raise
        return ToolResult.fail(
            tool_name="run_command",
            error=f"Command execution timed out after {effective_timeout}s.",
            metadata={"timeout": True, "error_type": "ContainerTimeoutException"},
        )
    except Exception as err:
        if raise_on_error:
            raise
        return ToolResult.fail(
            tool_name="run_command",
            error=str(err),
            metadata={"error_type": type(err).__name__},
        )
