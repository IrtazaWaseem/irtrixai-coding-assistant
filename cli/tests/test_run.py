import httpx
from irtrixai_cli.main import app
from typer.testing import CliRunner

_real_client = httpx.Client
runner = CliRunner()


def test_composite_run_approval_and_completion(monkeypatch):
    def mock_workflow(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/tasks" and request.method == "POST":
            return httpx.Response(
                201, json={"id": "task-abc-123", "workspace_id": "ws-1", "status": "pending"}
            )
        if path == "/api/v1/tasks/task-abc-123/run" and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "task_id": "task-abc-123",
                    "status": "awaiting_approval",
                    "coder_summary": "Implement multiply",
                    "pending_patch": "--- a/calc.py\n+++ b/calc.py\n@@ -1 +1 @@\n-pass\n+return a * b",
                },
            )
        if path == "/api/v1/tasks/task-abc-123/approval" and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "task_id": "task-abc-123",
                    "status": "completed",
                    "final_result": {"summary": "All tests passed", "files_changed": ["calc.py"]},
                },
            )
        return httpx.Response(404, json={})

    monkeypatch.setattr(
        "irtrixai_cli.client.httpx.Client",
        lambda *args, **kwargs: _real_client(
            *args,
            **{**kwargs, "transport": httpx.MockTransport(mock_workflow)},
        ),
    )

    result = runner.invoke(
        app, ["run", "--workspace", "D:\\test-repo", "--prompt", "Implement multiply"], input="y\n"
    )
    assert result.exit_code == 0
    assert "Task registered: task-abc-123" in result.output
    assert "Execution Finalized" in result.output
