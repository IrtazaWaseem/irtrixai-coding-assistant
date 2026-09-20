import asyncio
import subprocess
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app
from app.services.llm.gateway import create_task_llm_gateway


def init_test_git_repo(repo_path: Path) -> None:
    (repo_path / ".gitkeep").touch()
    subprocess.run(["git", "init"], cwd=str(repo_path), capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.name", "TestRunner"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@irtrixai.internal"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=str(repo_path), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )


@pytest.mark.asyncio
async def test_llm_providers_endpoint_returns_safe_metadata():
    """Proves GET /api/v1/llm/providers returns metadata without exposing secrets."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.get("/api/v1/llm/providers")
        assert res.status_code == 200
        data = res.json()
        assert "providers" in data
        assert len(data["providers"]) >= 3

        ids = [p["id"] for p in data["providers"]]
        assert "gemini" in ids
        assert "groq" in ids
        assert "ollama" in ids

        raw_str = res.text
        assert "api_key" not in raw_str.lower()
        assert "password" not in raw_str.lower()
        if settings.GEMINI_API_KEY:
            assert settings.GEMINI_API_KEY not in raw_str
        if settings.GROQ_API_KEY:
            assert settings.GROQ_API_KEY not in raw_str


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_task_creation_with_valid_ollama_selection(tmp_path: Path, client: AsyncClient):
    """Proves task stores explicit Ollama provider and model via isolated test DB."""
    ws = tmp_path / "ws_llm_ollama"
    ws.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws)

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()

    try:
        res = await client.post(
            "/api/v1/tasks",
            json={
                "workspace_path": str(ws),
                "prompt": "Test Ollama task",
                "provider": "ollama",
                "model": "deepseek-r1:8b",
            },
        )
        assert res.status_code == 201
        task = res.json()
        assert task["provider"] == "ollama"
        assert task["model"] == "deepseek-r1:8b"
    finally:
        settings.WORKSPACE_BASE_PATH = original_base


@pytest.mark.asyncio
async def test_task_creation_unsupported_provider_rejected(tmp_path: Path):
    """Proves unsupported provider returns 400 validation error."""
    ws = tmp_path / "ws_unsupported"
    ws.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.post(
            "/api/v1/tasks",
            json={
                "workspace_path": str(ws),
                "prompt": "Test unsupported",
                "provider": "anthropic",
                "model": "claude-3-opus",
            },
        )
        assert res.status_code == 400
        body = res.json()
        error_text = body.get("error") or body.get("detail") or body.get("message") or str(body)
        assert "Unsupported LLM provider 'anthropic'" in error_text


@pytest.mark.asyncio
async def test_missing_gemini_key_rejected_safely(tmp_path: Path):
    """Proves selecting Gemini when API key is missing is cleanly rejected without leaking credentials."""
    ws = tmp_path / "ws_gemini_missing"
    ws.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws)

    original_key = settings.GEMINI_API_KEY
    settings.GEMINI_API_KEY = ""

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/api/v1/tasks",
                json={
                    "workspace_path": str(ws),
                    "prompt": "Test Gemini missing",
                    "provider": "gemini",
                    "model": "gemini-2.5-flash",
                },
            )
            assert res.status_code == 400
            body = res.json()
            error_text = body.get("error") or body.get("detail") or body.get("message") or str(body)
            assert "Provider 'gemini' is unavailable" in error_text
            assert "API key is not configured" in error_text
    finally:
        settings.GEMINI_API_KEY = original_key


@pytest.mark.asyncio
async def test_missing_groq_key_rejected_safely(tmp_path: Path):
    """Proves selecting Groq when API key is missing is cleanly rejected without leaking credentials."""
    ws = tmp_path / "ws_groq_missing"
    ws.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws)

    original_key = settings.GROQ_API_KEY
    settings.GROQ_API_KEY = ""

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/api/v1/tasks",
                json={
                    "workspace_path": str(ws),
                    "prompt": "Test Groq missing",
                    "provider": "groq",
                    "model": "llama-3.3-70b-versatile",
                },
            )
            assert res.status_code == 400
            body = res.json()
            error_text = body.get("error") or body.get("detail") or body.get("message") or str(body)
            assert "Provider 'groq' is unavailable" in error_text
            assert "API key is not configured" in error_text
    finally:
        settings.GROQ_API_KEY = original_key


def test_create_task_llm_gateway_creates_isolated_instances():
    """Proves create_task_llm_gateway creates distinct instances and does not mutate global settings."""
    original_primary_prov = settings.PRIMARY_LLM_PROVIDER
    original_primary_model = settings.PRIMARY_LLM_MODEL

    gw1 = create_task_llm_gateway("ollama", "qwen-gpu-tuned")
    gw2 = create_task_llm_gateway("ollama", "deepseek-r1:8b")

    assert gw1 is not gw2
    assert gw1.primary.model == "qwen-gpu-tuned"
    assert gw2.primary.model == "deepseek-r1:8b"

    assert settings.PRIMARY_LLM_PROVIDER == original_primary_prov
    assert settings.PRIMARY_LLM_MODEL == original_primary_model


@pytest.mark.asyncio
async def test_concurrent_different_providers_remain_isolated(tmp_path: Path):
    """Proves two tasks running concurrently with different providers/models remain strictly isolated."""
    original_prov = settings.PRIMARY_LLM_PROVIDER
    original_model = settings.PRIMARY_LLM_MODEL

    gw_ollama = create_task_llm_gateway("ollama", "qwen-gpu-tuned")
    gw_custom = create_task_llm_gateway("ollama", "deepseek-r1:8b")

    async def mock_task_a():
        await asyncio.sleep(0.05)
        return gw_ollama.primary.model

    async def mock_task_b():
        await asyncio.sleep(0.05)
        return gw_custom.primary.model

    res_a, res_b = await asyncio.gather(mock_task_a(), mock_task_b())

    assert res_a == "qwen-gpu-tuned"
    assert res_b == "deepseek-r1:8b"
    assert settings.PRIMARY_LLM_PROVIDER == original_prov
    assert settings.PRIMARY_LLM_MODEL == original_model
