from typing import Any


class AppException(Exception):
    """Base exception for all application errors."""

    def __init__(
        self, message: str, status_code: int = 400, details: Any | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class EntityNotFoundException(AppException):
    def __init__(self, entity_name: str, entity_id: str) -> None:
        super().__init__(
            message=f"{entity_name} with id '{entity_id}' not found.",
            status_code=404,
            details={"entity_name": entity_name, "entity_id": entity_id},
        )


class SecurityViolationException(AppException):
    def __init__(self, message: str = "Security constraint violated") -> None:
        super().__init__(
            message=message,
            status_code=403,
            details={"type": "security_violation"},
        )


class ExecutionTimeoutException(AppException):
    def __init__(self, timeout_seconds: int) -> None:
        super().__init__(
            message=f"Command execution timed out after {timeout_seconds} seconds.",
            status_code=408,
            details={"timeout_seconds": timeout_seconds},
        )
