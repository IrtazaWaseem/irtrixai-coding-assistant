from typing import Any


class AppException(Exception):
    """Base application exception for all domain errors."""

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class EntityNotFoundException(AppException):
    def __init__(self, entity_name: str, entity_id: str):
        super().__init__(
            message=f"{entity_name} with id '{entity_id}' not found.",
            status_code=404,
            details={"entity_name": entity_name, "entity_id": entity_id},
        )


class SecurityViolationException(AppException):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            message=message,
            status_code=403,
            details=details or {},
        )


class ExecutionTimeoutException(AppException):
    def __init__(self, timeout_seconds: int, command: str | None = None):
        super().__init__(
            message=f"Command execution timed out after {timeout_seconds} seconds.",
            status_code=504,
            details={"timeout_seconds": timeout_seconds, "command": command},
        )


class ToolExecutionException(AppException):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            message=message,
            status_code=400,
            details=details or {},
        )


class FileSizeLimitExceededException(AppException):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            message=message,
            status_code=413,
            details=details or {},
        )
