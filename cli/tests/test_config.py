from irtrixai_cli.config import (
    DEFAULT_API_URL,
    ENV_API_URL_VAR,
    resolve_api_url,
    sanitize_url_for_display,
)


def test_resolve_api_url_default():
    assert resolve_api_url(None) == DEFAULT_API_URL
    assert resolve_api_url("") == DEFAULT_API_URL


def test_resolve_api_url_env(monkeypatch):
    monkeypatch.setenv(ENV_API_URL_VAR, "http://remote-host:9000/")
    assert resolve_api_url(None) == "http://remote-host:9000"


def test_resolve_api_url_explicit_precedence(monkeypatch):
    monkeypatch.setenv(ENV_API_URL_VAR, "http://remote-host:9000")
    assert resolve_api_url("http://custom-host:8080/") == "http://custom-host:8080"


def test_sanitize_url_for_display():
    raw = "http://admin:secret_pass@127.0.0.1:8000/api"
    sanitized = sanitize_url_for_display(raw)
    assert "secret_pass" not in sanitized
    assert "[REDACTED]" in sanitized
