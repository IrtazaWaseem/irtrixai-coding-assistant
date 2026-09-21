"""Multi-provider model diagnostic tool for IrtrixAI."""

import asyncio
import os
import sys
import time
from pathlib import Path

from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).parent))

from app.core.config import settings
from app.schemas.agent_contracts import CoderOutput
from app.schemas.llm import LLMConfig
from app.services.llm.providers.gemini import GeminiProvider
from app.services.llm.providers.groq import GroqProvider
from app.services.llm.providers.ollama import OllamaProvider


async def test_gemini():
    print("\n" + "=" * 60)
    print(" 1. TESTING GEMINI")
    print("=" * 60)
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        print("  [!] Skipped: GEMINI_API_KEY is not set.")
        return

    for model in ["gemini-2.5-flash"]:
        t0 = time.perf_counter()
        try:
            config = LLMConfig(provider="gemini", model=model, api_key=api_key)
            provider = GeminiProvider(config=config)
            res = await provider.generate_structured(
                prompt="Fix bug in test_calc.py: assert add(2,2) == 4.",
                response_schema=CoderOutput,
            )
            elapsed = time.perf_counter() - t0
            print(f"  [OK] {model:<26} ({elapsed:.2f}s) -> Output: {res.summary[:40]}...")
        except Exception as e:
            elapsed = time.perf_counter() - t0
            print(f"  [X]  {model:<26} ({elapsed:.2f}s) -> FAILED: {e}")


async def test_groq():
    print("\n" + "=" * 60)
    print(" 2. TESTING GROQ")
    print("=" * 60)
    api_key = settings.GROQ_API_KEY
    if not api_key:
        print("  [!] Skipped: GROQ_API_KEY is not set.")
        return

    # Candidates active on your Groq key
    candidates = [
        "qwen/qwen3.8-27b",
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "groq/compound",
        "allam-2-7b",
    ]

    for model in candidates:
        t0 = time.perf_counter()
        try:
            config = LLMConfig(provider="groq", model=model, api_key=api_key)
            provider = GroqProvider(config=config)
            res = await provider.generate_structured(
                prompt="Fix bug in test_calc.py: assert add(2,2) == 4.",
                response_schema=CoderOutput,
                system_instruction="You are an expert coder. Respond with valid JSON adhering to the schema.",
            )
            elapsed = time.perf_counter() - t0
            print(f"  [OK] {model:<26} ({elapsed:.2f}s) -> Output: {res.summary[:40]}...")
        except Exception as e:
            elapsed = time.perf_counter() - t0
            err_head = str(e).split("\n")[0][:70]
            print(f"  [X]  {model:<26} ({elapsed:.2f}s) -> FAILED: {err_head}")


async def test_ollama():
    print("\n" + "=" * 60)
    print(" 3. TESTING OLLAMA (Local)")
    print("=" * 60)
    base_url = settings.OLLAMA_BASE_URL or "http://localhost:11434"

    import httpx

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base_url}/api/tags")
            if resp.status_code != 200:
                print("  [!] Ollama returned non-200 status.")
                return
            installed = [
                m["name"] for m in resp.json().get("models", []) if "embed" not in m["name"]
            ]
    except Exception:
        print(f"  [X] Ollama is not accessible at {base_url}.")
        return

    print(f"  Testing {len(installed)} installed model(s)...")
    for model in installed:
        t0 = time.perf_counter()
        try:
            config = LLMConfig(
                provider="ollama", model=model, base_url=base_url, timeout_seconds=180.0
            )
            provider = OllamaProvider(config=config)
            res = await provider.generate_structured(
                prompt="Fix bug in test_calc.py: assert add(2,2) == 4.",
                response_schema=CoderOutput,
                system_instruction="You are an expert coder. Generate valid data.",
            )
            elapsed = time.perf_counter() - t0
            print(f"  [OK] {model:<30} ({elapsed:.2f}s) -> Output: {res.summary[:40]}...")
        except Exception as e:
            elapsed = time.perf_counter() - t0
            err_head = str(e).split("\n")[0][:70]
            print(f"  [X]  {model:<30} ({elapsed:.2f}s) -> FAILED: {err_head}")


async def main():
    await test_gemini()
    await test_groq()
    await test_ollama()


if __name__ == "__main__":
    asyncio.run(main())
