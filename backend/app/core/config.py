from pathlib import Path
from typing import TYPE_CHECKING

from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from app.schemas.llm import LLMConfig


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

    # LLM Providers & Gateway Configuration (Day 4)
    PRIMARY_LLM_PROVIDER: str = "ollama"
    PRIMARY_LLM_MODEL: str = "qwen-gpu-tuned"
    FALLBACK_LLM_PROVIDER: str | None = None
    FALLBACK_LLM_MODEL: str | None = None

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"

    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen-gpu-tuned"

    LLM_REQUEST_TIMEOUT_SECONDS: int = 60
    LLM_MAX_RETRIES: int = 3
    LLM_THINKING_LEVEL: str = "low"

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

    def get_provider_default_model(self, provider: str) -> str:
        """Resolves the default model identifier for a given provider."""
        prov = provider.strip().lower()
        if prov == "ollama":
            return self.OLLAMA_MODEL
        if prov == "groq":
            return self.GROQ_MODEL
        if prov == "gemini":
            return self.GEMINI_MODEL
        return ""

    def get_provider_credentials(self, provider: str) -> tuple[str | None, str | None]:
        """Resolves (api_key, base_url) for the specified provider."""
        prov = provider.strip().lower()
        if prov == "ollama":
            return None, self.OLLAMA_BASE_URL
        if prov == "groq":
            return self.GROQ_API_KEY or None, None
        if prov == "gemini":
            return self.GEMINI_API_KEY or None, None
        return None, None

    def get_primary_llm_config(self) -> "LLMConfig":
        """Builds authoritative LLMConfig for the primary provider."""
        from app.schemas.llm import LLMConfig

        prov = self.PRIMARY_LLM_PROVIDER.strip().lower()
        model = (
            self.PRIMARY_LLM_MODEL.strip()
            if self.PRIMARY_LLM_MODEL
            else self.get_provider_default_model(prov)
        )
        api_key, base_url = self.get_provider_credentials(prov)

        return LLMConfig(
            provider=prov,
            model=model,
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=self.LLM_REQUEST_TIMEOUT_SECONDS,
            max_retries=self.LLM_MAX_RETRIES,
            thinking_level=self.LLM_THINKING_LEVEL,
        )

    def get_fallback_llm_config(self) -> "LLMConfig | None":
        """Builds authoritative LLMConfig for the optional fallback provider."""
        from app.schemas.llm import LLMConfig

        if not self.FALLBACK_LLM_PROVIDER or not self.FALLBACK_LLM_PROVIDER.strip():
            return None

        prov = self.FALLBACK_LLM_PROVIDER.strip().lower()
        model = (
            self.FALLBACK_LLM_MODEL.strip()
            if self.FALLBACK_LLM_MODEL
            else self.get_provider_default_model(prov)
        )
        api_key, base_url = self.get_provider_credentials(prov)

        return LLMConfig(
            provider=prov,
            model=model,
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=self.LLM_REQUEST_TIMEOUT_SECONDS,
            max_retries=self.LLM_MAX_RETRIES,
            thinking_level=self.LLM_THINKING_LEVEL,
        )


settings = Settings()
