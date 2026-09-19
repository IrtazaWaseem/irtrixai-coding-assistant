import httpx
import pytest
from irtrixai_cli.client import (
    ApprovalStateError,
    BackendUnavailableError,
    ConflictError,
    IrtrixClient,
    NotFoundError,
)


def test_client_status_codes():
    def custom_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/workspaces/unknown":
            return httpx.Response(404, json={"detail": "Workspace not found"})
        if request.url.path == "/api/v1/tasks/running/run":
            return httpx.Response(409, json={"detail": "Task is already executing"})
        if request.url.path == "/api/v1/tasks/done/approval":
            return httpx.Response(400, json={"detail": "Task is no longer awaiting approval"})
        return httpx.Response(200, json={"status": "healthy"})

    client = IrtrixClient("http://test-server")
    client._client = httpx.Client(
        transport=httpx.MockTransport(custom_handler), base_url="http://test-server"
    )

    with pytest.raises(NotFoundError):
        client.get_workspace("unknown")

    with pytest.raises(ConflictError):
        client.run_task("running")

    with pytest.raises(ApprovalStateError):
        client.submit_approval("done", approved=True)


def test_client_connection_failure():
    def connection_error_handler(request: httpx.Request):
        raise httpx.ConnectError("Connection refused", request=request)

    client = IrtrixClient("http://offline-server")
    client._client = httpx.Client(
        transport=httpx.MockTransport(connection_error_handler), base_url="http://offline-server"
    )

    with pytest.raises(BackendUnavailableError):
        client.get_status()
