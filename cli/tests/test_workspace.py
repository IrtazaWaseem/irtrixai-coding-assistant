import httpx
from irtrixai_cli.main import app
from typer.testing import CliRunner

_real_client = httpx.Client
runner = CliRunner()


def test_workspace_list(monkeypatch):
    def mock_transport(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/workspaces":
            return httpx.Response(
                200, json=[{"id": "ws-1", "name": "backend", "root_path": "D:\\repo\\backend"}]
            )
        return httpx.Response(404)

    monkeypatch.setattr(
        "irtrixai_cli.client.httpx.Client",
        lambda *args, **kwargs: _real_client(
            *args,
            **{**kwargs, "transport": httpx.MockTransport(mock_transport)},
        ),
    )

    result = runner.invoke(app, ["workspace", "list"])
    assert result.exit_code == 0
    assert "backend" in result.output
    assert "D:\\repo\\backend" in result.output


def test_workspace_add(monkeypatch):
    def mock_transport(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/workspaces" and request.method == "POST":
            return httpx.Response(
                201, json={"id": "ws-2", "name": "my-app", "root_path": "D:\\my-app"}
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
        app, ["workspace", "add", "--name", "my-app", "--root-path", "D:\\my-app"]
    )
    assert result.exit_code == 0
    assert "Registered workspace my-app" in result.output


def test_workspace_tree(monkeypatch):
    def mock_transport(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/workspaces/ws-1/tree":
            return httpx.Response(
                200,
                json={
                    "workspace_id": "ws-1",
                    "root_path": "D:\\repo\\backend",
                    "max_depth": 3,
                    "total_entries": 2,
                    "truncated": False,
                    "tree": [
                        {
                            "name": "app",
                            "path": "app",
                            "type": "directory",
                            "children": [
                                {
                                    "name": "main.py",
                                    "path": "app/main.py",
                                    "type": "file",
                                    "size": 1024,
                                }
                            ],
                        }
                    ],
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

    result = runner.invoke(app, ["workspace", "tree", "ws-1", "--max-depth", "3"])
    assert result.exit_code == 0
    assert "main.py" in result.output


def test_workspace_tree_invalid_depth():
    result = runner.invoke(app, ["workspace", "tree", "ws-1", "--max-depth", "15"])
    assert result.exit_code == 2
    assert "between 1 and 10" in result.output


def test_workspace_not_found(monkeypatch):
    def mock_transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Workspace not found"})

    monkeypatch.setattr(
        "irtrixai_cli.client.httpx.Client",
        lambda *args, **kwargs: _real_client(
            *args,
            **{**kwargs, "transport": httpx.MockTransport(mock_transport)},
        ),
    )

    result = runner.invoke(app, ["workspace", "tree", "unknown-id"])
    assert result.exit_code == 5
    assert "not found" in result.output.lower()
