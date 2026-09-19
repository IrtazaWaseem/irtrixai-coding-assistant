import json

import httpx
from irtrixai_cli.main import app
from typer.testing import CliRunner

_real_client = httpx.Client
runner = CliRunner()


def test_windows_paths_preserved_exactly(monkeypatch):
    captured_path = {}

    def mock_transport(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/workspaces" and request.method == "POST":
            data = json.loads(request.content)
            captured_path["root_path"] = data["root_path"]
            return httpx.Response(
                201, json={"id": "ws-1", "name": data["name"], "root_path": data["root_path"]}
            )
        return httpx.Response(200, json={})

    monkeypatch.setattr(
        "irtrixai_cli.client.httpx.Client",
        lambda *args, **kwargs: _real_client(
            *args,
            **{**kwargs, "transport": httpx.MockTransport(mock_transport)},
        ),
    )

    # Windows drive letter with backslashes
    result = runner.invoke(
        app, ["workspace", "add", "--name", "repo", "--root-path", "D:\\irtrixai-test-repo"]
    )
    assert result.exit_code == 0
    assert captured_path["root_path"] == "D:\\irtrixai-test-repo"

    # Windows path with spaces
    result = runner.invoke(
        app,
        ["workspace", "add", "--name", "repo-space", "--root-path", "C:\\My Projects\\test repo"],
    )
    assert result.exit_code == 0
    assert captured_path["root_path"] == "C:\\My Projects\\test repo"
