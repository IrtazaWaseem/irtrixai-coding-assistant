import httpx
from irtrixai_cli.main import app
from typer.testing import CliRunner

_real_client = httpx.Client
runner = CliRunner()


def test_status_success(monkeypatch):
    def mock_transport(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/status":
            return httpx.Response(
                200, json={"status": "healthy", "version": "0.1.0", "environment": "development"}
            )
        if request.url.path == "/api/v1/llm/info":
            return httpx.Response(
                200,
                json={
                    "provider": "gemini",
                    "model": "gemini-2.5-flash",
                    "display_name": "Google Gemini (gemini-2.5-flash)",
                    "capabilities": {
                        "supports_structured_output": True,
                        "supports_streaming": True,
                    },
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

    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "healthy" in result.output
    assert "gemini-2.5-flash" in result.output


def test_status_backend_offline(monkeypatch):
    def error_transport(request: httpx.Request):
        raise httpx.ConnectError("Connection refused", request=request)

    monkeypatch.setattr(
        "irtrixai_cli.client.httpx.Client",
        lambda *args, **kwargs: _real_client(
            *args,
            **{**kwargs, "transport": httpx.MockTransport(error_transport)},
        ),
    )

    result = runner.invoke(app, ["status"])
    assert result.exit_code == 3
    assert "Offline" in result.output or "Cannot reach backend" in result.output


def test_status_partial_llm_failure(monkeypatch):
    def mock_transport(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/status":
            return httpx.Response(
                200, json={"status": "healthy", "version": "0.1.0", "environment": "development"}
            )
        if request.url.path == "/api/v1/llm/info":
            return httpx.Response(500, json={"detail": "LLM Provider Unavailable"})
        return httpx.Response(404)

    monkeypatch.setattr(
        "irtrixai_cli.client.httpx.Client",
        lambda *args, **kwargs: _real_client(
            *args,
            **{**kwargs, "transport": httpx.MockTransport(mock_transport)},
        ),
    )

    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "healthy" in result.output
    assert "Unavailable" in result.output
