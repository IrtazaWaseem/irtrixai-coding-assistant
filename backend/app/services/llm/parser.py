import json
import re

from pydantic import BaseModel, ValidationError

from app.core.exceptions import LLMResponseException


def parse_structured_output[T: BaseModel](content: str, schema: type[T]) -> T:
    """Parses and validates structured output from raw LLM text against a Pydantic schema.

    Enforces:
    1. Rejection of empty or blank responses.
    2. Stripping reasoning tags (<think>...</think>) from reasoning models (e.g. DeepSeek R1).
    3. Extraction from Markdown code fences (```json ... ``` or ``` ... ```).
    4. Strict JSON parsing and object type validation.
    5. Strict Pydantic schema validation.

    Raises:
        LLMResponseException: If content is missing, invalid JSON, or fails schema validation.
    """
    if not content or not content.strip():
        raise LLMResponseException("LLM returned empty content; expected structured output.")

    # 1. Strip reasoning blocks (<think>...</think>)
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", content).strip()
    if not cleaned:
        raise LLMResponseException(
            "LLM response contained only reasoning tags with no structured payload."
        )

    # 2. Extract from markdown code fence if wrapped
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    # 3. Parse JSON
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as err:
        raise LLMResponseException(
            f"Failed to parse LLM response as valid JSON: {err}",
            details={"raw_content": content[:500]},
        ) from err

    if not isinstance(data, dict):
        raise LLMResponseException(
            f"Expected JSON object for schema '{schema.__name__}', received '{type(data).__name__}'.",
            details={"raw_content": content[:500]},
        )

    # 4. Strict Pydantic validation
    try:
        return schema.model_validate(data)
    except ValidationError as err:
        raise LLMResponseException(
            f"LLM response failed schema validation for '{schema.__name__}': {err}",
            details={
                "validation_errors": err.errors(include_url=False),
                "schema": schema.__name__,
            },
        ) from err
