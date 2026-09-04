from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Core Application Settings
    PROJECT_NAME: str = "IrtrixAI Coding Assistant"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    API_V1_STR: str = "/api/v1"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    BACKEND_CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ]

    # Database Configuration
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "irtrixai_db"
    POSTGRES_USER: str = "irtrixai"
    POSTGRES_PASSWORD: str = "irtrixai_dev_password"
    DATABASE_URL: str = (
        "postgresql+asyncpg://irtrixai:irtrixai_dev_password@localhost:5432/irtrixai_db"
    )

    # LLM Provider Configuration
    PRIMARY_LLM_PROVIDER: str = "gemini"
    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5-coder:7b"

    # Workspace & Tool Limits
    WORKSPACE_BASE_PATH: Path = Path("./workspaces").resolve()
    MAX_WORKSPACE_DEPTH: int = 5
    MAX_READ_FILE_BYTES: int = 1_048_576  # 1MB
    MAX_TOOL_OUTPUT_BYTES: int = 51_200  # 50KB
    MAX_SEARCH_RESULTS: int = 100
    MAX_SEARCH_FILE_SIZE: int = 524_288  # 500KB
    MAX_PATCH_SIZE: int = 262_144  # 256KB
    COMMAND_TIMEOUT_SECONDS: int = 30

    # Day 3 Docker Sandbox Execution Settings
    DOCKER_SANDBOX_IMAGE: str = "irtrixai-sandbox:latest"
    SANDBOX_TIMEOUT_SECONDS: int = 30
    SANDBOX_MEMORY_LIMIT: str = "512m"
    SANDBOX_CPU_LIMIT: str = "1.0"
    SANDBOX_PIDS_LIMIT: int = 64
    SANDBOX_CONTAINER_USER: str = "1000:1000"
    SANDBOX_TMPFS_SIZE: str = "64m"

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
