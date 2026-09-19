import httpx
from irtrixai_cli.main import app
from typer.testing import CliRunner

_real_client = httpx.Client
runner = CliRunner()


def test_default_error_output_does_not_expose_credentials(monkeypatch):
    def error_transport(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            json={
                "detail": "Internal database error at postgresql://postgres:super_secret@localhost:5432/db"
            },
            headers={"Authorization": "Bearer secret_jwt_token"},
        )

    monkeypatch.setattr(
        "irtrixai_cli.client.httpx.Client",
        lambda *args, **kwargs: _real_client(
            *args,
            **{**kwargs, "transport": httpx.MockTransport(error_transport)},
        ),
    )

    result = runner.invoke(app, ["status"])
    assert result.exit_code == 3
    assert "secret_jwt_token" not in result.output
