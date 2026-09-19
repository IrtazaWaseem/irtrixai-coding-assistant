import httpx
from irtrixai_cli.main import app
from typer.testing import CliRunner

_real_client = httpx.Client
runner = CliRunner()


def test_task_create(monkeypatch):
    def mock_transport(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/tasks" and request.method == "POST":
            return httpx.Response(
                201, json={"id": "task-123", "workspace_id": "ws-1", "status": "pending"}
            )
        return httpx.Response(404)

    monkeypatch.setattr(
        "irtrixai_cli.client.httpx.Client",
        lambda *args, **kwargs: _real_client(
            *args,
            **{**kwargs, "transport": httpx.MockTransport(mock_transport)},
        ),
    )

    result = runner.invoke(
        app, ["task", "create", "--workspace", "D:\\repo", "--prompt", "Fix tests"]
    )
    assert result.exit_code == 0
    assert "task-123" in result.output


def test_task_status(monkeypatch):
    def mock_transport(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/tasks/task-123":
            return httpx.Response(
                200, json={"id": "task-123", "workspace_id": "ws-1", "status": "running"}
            )
        return httpx.Response(404)

    monkeypatch.setattr(
        "irtrixai_cli.client.httpx.Client",
        lambda *args, **kwargs: _real_client(
            *args,
            **{**kwargs, "transport": httpx.MockTransport(mock_transport)},
        ),
    )

    result = runner.invoke(app, ["task", "status", "task-123"])
    assert result.exit_code == 0
    assert "RUNNING" in result.output


def test_task_run_awaiting_approval(monkeypatch):
    def mock_transport(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/tasks/task-123/run":
            return httpx.Response(
                200,
                json={
                    "task_id": "task-123",
                    "status": "awaiting_approval",
                    "coder_summary": "Proposed fix",
                    "pending_patch": "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-a\n+b",
                },
            )
        return httpx.Response(404)

    monkeypatch.setattr(
        "irtrixai_cli.client.httpx.Client",
        lambda *args, **kwargs: _real_client(
            *args,
            **{**kwargs, "transport": httpx.MockTransport(mock_transport)},
        ),
    )

    result = runner.invoke(app, ["task", "run", "task-123"])
    assert result.exit_code == 0
    assert "Human Approval Gate" in result.output


def test_task_approve(monkeypatch):
    def mock_transport(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/tasks/task-123/approval" and request.method == "POST":
            return httpx.Response(200, json={"task_id": "task-123", "status": "completed"})
        return httpx.Response(404)

    monkeypatch.setattr(
        "irtrixai_cli.client.httpx.Client",
        lambda *args, **kwargs: _real_client(
            *args,
            **{**kwargs, "transport": httpx.MockTransport(mock_transport)},
        ),
    )

    result = runner.invoke(app, ["task", "approve", "task-123"])
    assert result.exit_code == 0
    assert "completed successfully" in result.output


def test_task_reject(monkeypatch):
    def mock_transport(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/tasks/task-123/approval" and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "task_id": "task-123",
                    "status": "aborted",
                    "error": "Operator rejected changes",
                },
            )
        return httpx.Response(404)

    monkeypatch.setattr(
        "irtrixai_cli.client.httpx.Client",
        lambda *args, **kwargs: _real_client(
            *args,
            **{**kwargs, "transport": httpx.MockTransport(mock_transport)},
        ),
    )

    result = runner.invoke(app, ["task", "reject", "task-123", "--feedback", "Not correct"])
    assert result.exit_code == 0
    assert "ABORTED" in result.output


def test_task_events(monkeypatch):
    def mock_transport(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/tasks/task-123/events":
            raw_sse = (
                "event: workspace_inspected\n"
                'data: {"id": "1", "timestamp": "2026-09-19T06:00:00", "type": "workspace_inspected", "title": "Inspected", "description": "Done"}\n\n'
            )
            return httpx.Response(200, text=raw_sse, headers={"content-type": "text/event-stream"})
        return httpx.Response(404)

    monkeypatch.setattr(
        "irtrixai_cli.client.httpx.Client",
        lambda *args, **kwargs: _real_client(
            *args,
            **{**kwargs, "transport": httpx.MockTransport(mock_transport)},
        ),
    )

    result = runner.invoke(app, ["task", "events", "task-123"])
    assert result.exit_code == 0
    assert "Inspected" in result.output
