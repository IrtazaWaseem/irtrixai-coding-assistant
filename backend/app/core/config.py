from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Core
    PROJECT_NAME: str = "IrtrixAI Coding Assistant"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    API_V1_STR: str = "/api/v1"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    BACKEND_CORS_ORIGINS: list[str | AnyHttpUrl] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    # Persistence
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "irtrixai_db"
    POSTGRES_USER: str = "irtrixai"
    POSTGRES_PASSWORD: str = "irtrixai_dev_password"
    DATABASE_URL: str = (
        "postgresql+asyncpg://irtrixai:irtrixai_dev_password@localhost:5432/irtrixai_db"
    )

    # LLM Providers
    PRIMARY_LLM_PROVIDER: str = "gemini"
    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5-coder:7b"

    # Workspace & Sandboxing
    WORKSPACE_BASE_PATH: str = "/tmp/irtrixai_workspaces"
    DOCKER_SANDBOX_IMAGE: str = "irtrixai-sandbox:latest"
    COMMAND_TIMEOUT_SECONDS: int = 30
    MAX_OUTPUT_BYTES: int = 50000

    # Tool Engine Execution Limits
    MAX_READ_FILE_BYTES: int = 1_000_000  # 1 MB max file read
    MAX_TOOL_OUTPUT_BYTES: int = 50_000  # 50 KB max tool return output
    MAX_SEARCH_RESULTS: int = 100  # Max regex code matches
    MAX_SEARCH_FILE_SIZE: int = 500_000  # 500 KB max search file size
    MAX_PATCH_SIZE: int = 200_000  # 200 KB max patch size


settings = Settings()
