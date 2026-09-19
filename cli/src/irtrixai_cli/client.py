import contextlib
import types
from typing import Any, Self

import httpx

from irtrixai_cli.config import sanitize_url_for_display
from irtrixai_cli.events import parse_sse_snapshot
from irtrixai_cli.models import (
    CombinedStatus,
    ExecutionResponse,
    LLMInfo,
    SystemStatus,
    TaskResponse,
    Workspace,
    WorkspaceTree,
)


class CLIError(Exception):
    def __init__(self, message: str, exit_code: int = 1):
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


class BackendUnavailableError(CLIError):
    def __init__(self, message: str = "Cannot reach backend. Verify the server is running."):
        super().__init__(message, exit_code=3)


class ConflictError(CLIError):
    def __init__(
        self, message: str = "Task is already running or conflicting operation in progress."
    ):
        super().__init__(message, exit_code=4)


class ApprovalStateError(CLIError):
    def __init__(self, message: str = "Task is no longer awaiting approval."):
        super().__init__(message, exit_code=4)


class NotFoundError(CLIError):
    def __init__(self, message: str = "Requested resource not found."):
        super().__init__(message, exit_code=5)


class APIValidationError(CLIError):
    def __init__(self, message: str = "Validation error from backend."):
        super().__init__(message, exit_code=2)


class IrtrixClient:
    """Centralized thin-client abstraction for IrtrixAI FastAPI backend."""

    def __init__(self, base_url: str, timeout: float = 45.0):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout, connect=10.0),
            headers={"Accept": "application/json", "User-Agent": "irtrixai-cli/0.1.0"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        self.close()

    def _handle_request_error(self, exc: Exception) -> None:
        if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError)):
            clean_url = sanitize_url_for_display(self.base_url)
            raise BackendUnavailableError(
                f"Cannot reach backend at {clean_url}. Is the service running?"
            ) from exc
        if isinstance(exc, httpx.TimeoutException):
            raise BackendUnavailableError(
                "Request timed out waiting for backend response."
            ) from exc

    def _handle_status_codes(
        self, response: httpx.Response, resource_context: str = ""
    ) -> dict[str, Any]:
        if response.status_code == 404:
            raise NotFoundError(f"{resource_context or 'Resource'} not found.")
        if response.status_code == 409:
            detail = self._extract_detail(response, "Task is already running.")
            raise ConflictError(detail)
        if response.status_code == 400:
            detail = self._extract_detail(response, "Invalid request.")
            if "approval" in detail.lower() or "awaiting" in detail.lower():
                raise ApprovalStateError(detail)
            raise CLIError(detail, exit_code=1)
        if response.status_code == 422:
            detail = self._extract_detail(response, "Validation error.")
            raise APIValidationError(f"Invalid input: {detail}")
        if response.status_code >= 500:
            detail = self._extract_detail(response, "Internal server error.")
            raise CLIError(
                f"Backend internal error ({response.status_code}): {detail}", exit_code=1
            )

        try:
            return response.json()
        except Exception as err:
            raise CLIError(f"Malformed JSON response from server: {err}", exit_code=1) from err

    def _extract_detail(self, response: httpx.Response, fallback: str) -> str:
        with contextlib.suppress(ValueError, TypeError, KeyError, httpx.HTTPError):
            body = response.json()
            if isinstance(body, dict):
                return str(body.get("detail", body.get("error", fallback)))
        return fallback

    # SYSTEM COMMANDS
    def get_status(self) -> SystemStatus:
        try:
            resp = self._client.get("/api/v1/status")
        except Exception as exc:
            self._handle_request_error(exc)
            raise
        data = self._handle_status_codes(resp, "System status")
        return SystemStatus.from_dict(data)

    def get_llm_info(self) -> LLMInfo:
        try:
            resp = self._client.get("/api/v1/llm/info")
        except Exception as exc:
            self._handle_request_error(exc)
            raise
        data = self._handle_status_codes(resp, "LLM info")
        return LLMInfo.from_dict(data)

    def get_combined_status(self) -> CombinedStatus:
        backend_stat: SystemStatus | None = None
        llm_stat: LLMInfo | None = None
        backend_err: str | None = None
        llm_err: str | None = None

        try:
            backend_stat = self.get_status()
        except CLIError as e:
            backend_err = e.message

        try:
            llm_stat = self.get_llm_info()
        except CLIError as e:
            llm_err = e.message

        return CombinedStatus(
            backend=backend_stat,
            llm=llm_stat,
            backend_error=backend_err,
            llm_error=llm_err,
        )

    # WORKSPACE COMMANDS
    def list_workspaces(self) -> list[Workspace]:
        try:
            resp = self._client.get("/api/v1/workspaces")
        except Exception as exc:
            self._handle_request_error(exc)
            raise
        data = self._handle_status_codes(resp, "Workspaces")
        if isinstance(data, list):
            return [Workspace.from_dict(w) for w in data if isinstance(w, dict)]
        return []

    def create_workspace(self, name: str, root_path: str) -> Workspace:
        try:
            resp = self._client.post(
                "/api/v1/workspaces", json={"name": name, "root_path": root_path}
            )
        except Exception as exc:
            self._handle_request_error(exc)
            raise
        data = self._handle_status_codes(resp, "Workspace")
        return Workspace.from_dict(data)

    def get_workspace(self, workspace_id: str) -> Workspace:
        try:
            resp = self._client.get(f"/api/v1/workspaces/{workspace_id}")
        except Exception as exc:
            self._handle_request_error(exc)
            raise
        data = self._handle_status_codes(resp, f"Workspace '{workspace_id}'")
        return Workspace.from_dict(data)

    def get_workspace_tree(self, workspace_id: str, max_depth: int = 3) -> WorkspaceTree:
        try:
            resp = self._client.get(
                f"/api/v1/workspaces/{workspace_id}/tree",
                params={"max_depth": max_depth},
            )
        except Exception as exc:
            self._handle_request_error(exc)
            raise
        data = self._handle_status_codes(resp, f"Workspace tree for '{workspace_id}'")
        return WorkspaceTree.from_dict(data)

    # TASK COMMANDS
    def create_task(self, workspace_path: str, prompt: str) -> TaskResponse:
        try:
            resp = self._client.post(
                "/api/v1/tasks",
                json={"workspace_path": workspace_path, "prompt": prompt},
            )
        except Exception as exc:
            self._handle_request_error(exc)
            raise
        data = self._handle_status_codes(resp, "Task")
        return TaskResponse.from_dict(data)

    def get_task(self, task_id: str) -> TaskResponse:
        try:
            resp = self._client.get(f"/api/v1/tasks/{task_id}")
        except Exception as exc:
            self._handle_request_error(exc)
            raise
        data = self._handle_status_codes(resp, f"Task '{task_id}'")
        return TaskResponse.from_dict(data)

    def run_task(self, task_id: str) -> ExecutionResponse:
        try:
            resp = self._client.post(f"/api/v1/tasks/{task_id}/run")
        except Exception as exc:
            self._handle_request_error(exc)
            raise
        data = self._handle_status_codes(resp, f"Task execution '{task_id}'")
        return ExecutionResponse.from_dict(data)

    def submit_approval(
        self, task_id: str, approved: bool, feedback: str | None = None
    ) -> ExecutionResponse:
        try:
            resp = self._client.post(
                f"/api/v1/tasks/{task_id}/approval",
                json={"approved": approved, "feedback": feedback},
            )
        except Exception as exc:
            self._handle_request_error(exc)
            raise
        data = self._handle_status_codes(resp, f"Approval for '{task_id}'")
        return ExecutionResponse.from_dict(data)

    def get_task_events(self, task_id: str) -> list[Any]:
        try:
            resp = self._client.get(
                f"/api/v1/tasks/{task_id}/events",
                headers={"Accept": "text/event-stream"},
            )
        except Exception as exc:
            self._handle_request_error(exc)
            raise

        if resp.status_code == 404:
            raise NotFoundError(f"Task '{task_id}' not found.")
        if resp.status_code >= 400:
            raise CLIError(f"Failed to fetch events: HTTP {resp.status_code}", exit_code=1)

        return parse_sse_snapshot(resp.text)
