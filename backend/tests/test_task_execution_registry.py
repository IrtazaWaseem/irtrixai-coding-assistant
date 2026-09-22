import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.services.task_service import TaskExecutionRegistry, TaskService


@pytest.mark.asyncio
async def test_registry_register_and_is_running():
    registry = TaskExecutionRegistry()
    assert await registry.is_running("task-1") is False

    async def dummy():
        await asyncio.sleep(0.5)

    task = asyncio.create_task(dummy())
    await registry.register("task-1", task)
    assert await registry.is_running("task-1") is True

    await task


@pytest.mark.asyncio
async def test_registry_cancel_running_task():
    registry = TaskExecutionRegistry()

    async def long_running():
        await asyncio.sleep(10)

    task = asyncio.create_task(long_running())
    await registry.register("task-2", task)

    cancelled = await registry.cancel("task-2")
    assert cancelled is True

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_registry_cancel_unknown_task_returns_false():
    registry = TaskExecutionRegistry()
    assert await registry.cancel("nonexistent-task") is False


@pytest.mark.asyncio
async def test_registry_cancel_finished_task_returns_false():
    registry = TaskExecutionRegistry()

    async def fast():
        return 42

    task = asyncio.create_task(fast())
    await task
    await registry.register("task-3", task)
    assert await registry.cancel("task-3") is False


@pytest.mark.asyncio
async def test_registry_unregister_only_matching_handle():
    registry = TaskExecutionRegistry()

    async def t1():
        await asyncio.sleep(0.1)

    async def t2():
        await asyncio.sleep(0.5)

    task1 = asyncio.create_task(t1())
    task2 = asyncio.create_task(t2())

    await registry.register("task-4", task1)
    await registry.register("task-4", task2)

    # Attempt to unregister with old task1 handle: task2 must survive
    await registry.unregister("task-4", task1)
    assert await registry.is_running("task-4") is True

    await registry.unregister("task-4", task2)
    assert await registry.is_running("task-4") is False
    task2.cancel()


@pytest.mark.asyncio
async def test_run_graph_cancellable_normal_completion():
    fake_graph = AsyncMock()
    fake_graph.ainvoke = AsyncMock(return_value={"status": "completed"})

    res = await TaskService.run_graph_cancellable("task-5", fake_graph, {}, {})
    assert res == {"status": "completed"}
    assert (
        await TaskService.run_graph_cancellable.__globals__["task_execution_registry"].is_running(
            "task-5"
        )
        is False
    )


@pytest.mark.asyncio
async def test_run_graph_cancellable_cancellation_propagation():
    fake_graph = AsyncMock()

    async def endless_ainvoke(*args: Any, **kwargs: Any):
        await asyncio.sleep(60)

    fake_graph.ainvoke = AsyncMock(side_effect=endless_ainvoke)
    registry = TaskService.run_graph_cancellable.__globals__["task_execution_registry"]

    outer_task = asyncio.create_task(
        TaskService.run_graph_cancellable("task-6", fake_graph, {}, {})
    )

    for _ in range(50):
        if await registry.is_running("task-6"):
            break
        await asyncio.sleep(0.01)

    assert await registry.is_running("task-6") is True

    cancelled = await registry.cancel("task-6")
    assert cancelled is True

    with pytest.raises(asyncio.CancelledError):
        await outer_task

    assert await registry.is_running("task-6") is False
