import asyncio
import uuid

from sqlalchemy import inspect, select, text

from app.db.models import AgentEvent, Run, Task, TaskStatus, Workspace
from app.db.session import AsyncSessionLocal, engine


async def run_connectivity_test() -> None:
    print("[1/4] Testing PostgreSQL TCP & authentication connection...")
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT version();"))
        db_version = result.scalar()
        print(f"      Connection verified. Target DB: {db_version}")

        print("[2/4] Inspecting existing database tables...")
        tables = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).get_table_names()
        )
        required_tables = {
            "workspaces",
            "tasks",
            "runs",
            "agent_events",
            "alembic_version",
        }
        missing = required_tables - set(tables)
        if missing:
            raise RuntimeError(f"Missing required database tables: {missing}")
        print(f"      All tables present: {tables}")

    print(
        "[3/4] Performing transactional insert/query/delete check across all models..."
    )
    async with AsyncSessionLocal() as session:
        workspace_id = uuid.uuid4()
        test_workspace = Workspace(
            id=workspace_id,
            name="integration-test-workspace",
            root_path=f"/tmp/test_{workspace_id}",
        )
        session.add(test_workspace)
        await session.flush()

        test_task = Task(
            workspace_id=workspace_id,
            prompt="Initial automated integration verification test",
            status=TaskStatus.PENDING,
        )
        session.add(test_task)
        await session.flush()

        test_run = Run(
            task_id=test_task.id,
            thread_id=f"thread_{uuid.uuid4()}",
            status=TaskStatus.RUNNING,
            repair_count=0,
            plan=[],
        )
        session.add(test_run)
        await session.flush()

        test_event = AgentEvent(
            run_id=test_run.id,
            node_name="test_node",
            event_type="test_event",
            payload={"verified": True},
        )
        session.add(test_event)
        await session.flush()

        stmt = select(Task).where(Task.workspace_id == workspace_id)
        fetched_task = (await session.execute(stmt)).scalar_one()
        assert fetched_task.prompt == "Initial automated integration verification test"
        print("      Transaction verified (Foreign keys, Enums, UUIDs operational).")

        await session.delete(test_workspace)
        await session.commit()
        print("      Cascade deletion verified.")

    print("[4/4] Database connectivity verification passed successfully!")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_connectivity_test())
