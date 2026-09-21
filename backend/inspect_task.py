import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.agent.graph import build_agent_graph
from app.agent.checkpoint import checkpointer_manager

async def inspect():
    await checkpointer_manager.initialize()
    try:
        graph = build_agent_graph(checkpointer=checkpointer_manager.get_checkpointer())
        config = {"configurable": {"thread_id": "thread-ba33398b-eb73-4bd4-85be-b83f356fc1a3"}}
        state = await graph.aget_state(config)
        
        print("=" * 60)
        print("CHECKPOINT DUMP FOR ba33398b")
        print("=" * 60)
        if not state or not state.values:
            print("No state values found in checkpoint.")
            return

        print("APPROVAL:       ", repr(state.values.get("approval")), type(state.values.get("approval")))
        print("ERROR:          ", repr(state.values.get("error")))
        print("APPLIED_DIFF:   ", repr(state.values.get("applied_diff"))[:120] if state.values.get("applied_diff") else None)
        print("TEST_RESULT:    ", repr(state.values.get("test_result")))
        print("REVIEW_SUMMARY: ", repr(state.values.get("review_summary")))
        print("REVIEW_STATUS:  ", repr(state.values.get("review_status")))
        print("FINAL_RESULT:   ", repr(state.values.get("final_result")))
    finally:
        await checkpointer_manager.close()

if __name__ == "__main__":
    asyncio.run(inspect())
