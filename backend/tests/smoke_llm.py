import asyncio
import sys

from app.core.config import settings
from app.schemas.agent_contracts import PlannerOutput
from app.services.llm.gateway import LLMGateway


async def main() -> None:
    print("==================================================")
    print(" IrtrixAI LLM Gateway Live Diagnostic Smoke Test ")
    print("==================================================")
    gateway = LLMGateway()
    info = gateway.get_model_info()
    print(f"Primary Provider : {info.provider}")
    print(f"Primary Model    : {info.model}")
    print(f"Display Name     : {info.display_name}")
    print(f"Fallback Config  : {settings.FALLBACK_LLM_PROVIDER or 'None'}")
    print("--------------------------------------------------")

    print("\n1. Testing Text Generation...")
    try:
        res = await gateway.generate("Reply with: 'Gateway Online'")
        print(f"Content: {res.content.strip()}")
        print(f"Fulfilled by: {gateway.last_used_provider} ({gateway.last_used_model})")
    except Exception as e:  # noqa: BLE001
        print(f"Failed: {e}")
        sys.exit(1)

    print("\n2. Testing Structured Generation (PlannerOutput)...")
    try:
        plan = await gateway.generate_structured(
            "Plan adding a healthcheck route to FastAPI", PlannerOutput
        )
        print(f"Plan Summary: {plan.summary}")
        print(f"Plan Steps  : {plan.steps}")
    except Exception as e:  # noqa: BLE001
        print(f"Failed: {e}")
        sys.exit(1)

    print("\nAll live diagnostic checks passed!")


if __name__ == "__main__":
    asyncio.run(main())
