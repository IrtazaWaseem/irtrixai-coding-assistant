from typing import Any

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """Standardized deterministic tool invocation response."""

    success: bool
    tool_name: str
    output: Any = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def ok(
        cls,
        tool_name: str,
        output: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ToolResult":
        return cls(
            success=True,
            tool_name=tool_name,
            output=output,
            metadata=metadata or {},
        )

    @classmethod
    def fail(
        cls,
        tool_name: str,
        error: str,
        metadata: dict[str, Any] | None = None,
    ) -> "ToolResult":
        return cls(
            success=False,
            tool_name=tool_name,
            error=error,
            metadata=metadata or {},
        )
