import importlib

import pytest


def test_backend_package_importable():
    """Proves the backend package 'app' installs and imports cleanly."""
    import app

    assert hasattr(app, "__file__")
    assert app.__file__ is not None


def test_main_fastapi_app_importable():
    """Proves app.main imports and defines the FastAPI application instance."""
    from app.main import app as fastapi_app

    assert fastapi_app is not None
    assert fastapi_app.title == "IrtrixAI Coding Assistant"


def test_postgres_checkpoint_dependency_available():
    """Proves langgraph-checkpoint-postgres and psycopg_pool runtime dependencies are resolvable."""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg_pool import AsyncConnectionPool

    assert AsyncPostgresSaver is not None
    assert AsyncConnectionPool is not None


def test_package_submodules_available():
    """Proves all internal application modules are correctly packaged and discoverable."""
    modules = [
        "app.agent",
        "app.api",
        "app.core",
        "app.db",
        "app.schemas",
        "app.services",
        "app.tools",
    ]
    for mod_name in modules:
        mod = importlib.import_module(mod_name)
        assert mod is not None


def test_unrelated_directories_not_in_app_namespace():
    """Proves tests, scripts, and alembic directories are not packaged into the app namespace."""
    import app

    assert not hasattr(app, "tests")
    assert not hasattr(app, "scripts")
    assert not hasattr(app, "alembic")


@pytest.mark.asyncio
async def test_checkpointer_manager_fail_closed_without_postgres():
    """Proves PostgresCheckpointerManager raises ToolExecutionException when uninitialized."""
    from app.agent.checkpoint import PostgresCheckpointerManager
    from app.core.exceptions import ToolExecutionException

    mgr = PostgresCheckpointerManager()
    with pytest.raises(ToolExecutionException) as exc_info:
        mgr.get_checkpointer()
    assert "not initialized" in str(exc_info.value).lower()
