import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.agent.checkpoint import checkpointer_manager
from app.api.v1.api import api_router
from app.core.config import settings
from app.core.exceptions import AppException

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("irtrixai")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager initializing and tearing down persistent infrastructure."""
    logger.info("Application starting up: %s", settings.PROJECT_NAME)
    try:
        await checkpointer_manager.initialize()
    except Exception as err:
        logger.warning(
            "PostgreSQL checkpointer initialization deferred/unavailable at startup: %s",
            err,
        )

    yield

    logger.info("Application shutting down: closing checkpointer resources.")
    await checkpointer_manager.close()


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Handles domain AppExceptions by formatting consistent JSON responses."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.message,
            "details": exc.details,
        },
    )


app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/health", tags=["system"])
async def health_check() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "irtrixai-backend",
        "project": settings.PROJECT_NAME,
        "environment": settings.ENVIRONMENT,
        "checkpointer_ready": checkpointer_manager.is_initialized,
    }
