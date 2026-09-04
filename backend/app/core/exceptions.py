from typing import Any


class AppException(Exception):
    """Base application exception with structured error payload."""

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class EntityNotFoundException(AppException):
    def __init__(self, entity_name: str, identifier: str) -> None:
        super().__init__(
            message=f"{entity_name} '{identifier}' not found.",
            status_code=404,
            details={"entity": entity_name, "identifier": identifier},
        )


class SecurityViolationException(AppException):
    def __init__(
        self,
        message: str = "Access denied: security boundary violation.",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, status_code=403, details=details or {})


class ProtectedFileAccessViolationException(SecurityViolationException):
    """Raised when an operation attempts to access or mutate a protected secret file."""

    def __init__(self, path: str, message: str | None = None) -> None:
        msg = message or f"Access denied: path '{path}' is protected."
        super().__init__(message=msg, details={"path": str(path), "protected": True})


class DisallowedCommandException(SecurityViolationException):
    """Raised when a command violates the sandbox executable allowlist or syntax rules."""

    def __init__(
        self,
        message: str = "Command execution rejected by policy.",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, details=details)


class FileSizeLimitExceededException(AppException):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, status_code=413, details=details or {})


class ExecutionTimeoutException(AppException):
    def __init__(
        self,
        timeout_seconds: int,
        command: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        info = details or {}
        info["timeout_seconds"] = timeout_seconds
        if command:
            info["command"] = command
        super().__init__(
            message=f"Command execution timed out after {timeout_seconds}s.",
            status_code=408,
            details=info,
        )


class ContainerTimeoutException(ExecutionTimeoutException):
    """Raised when container execution exceeds configured timeout limit."""

    def __init__(
        self,
        timeout_seconds: int,
        command: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(timeout_seconds=timeout_seconds, command=command, details=details)


class ToolExecutionException(AppException):
    def __init__(
        self,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, status_code=status_code, details=details or {})


class ContainerExecutionException(AppException):
    """Raised when Docker container operations fail."""

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, status_code=status_code, details=details or {})
