import json
from typing import Any

from irtrixai_cli.models import CLIEvent


def parse_sse_snapshot(raw_body: str) -> list[CLIEvent]:
    """
    Deterministic one-shot parser for the persisted SSE snapshot returned by
    GET /api/v1/tasks/{task_id}/events.

    Parses 'event:' and 'data:' lines separated by blank lines.
    Terminates immediately when the response payload is consumed.
    """
    if not raw_body or not raw_body.strip():
        return []

    events: list[CLIEvent] = []
    # Standard SSE event blocks are separated by double newlines
    blocks = raw_body.replace("\r\n", "\n").split("\n\n")

    for idx, block in enumerate(blocks):
        block = block.strip()
        if not block:
            continue

        event_name = "message"
        data_lines: list[str] = []
        block_id = f"evt_{idx + 1}"

        for line in block.split("\n"):
            line = line.strip()
            if not line or line.startswith(":"):
                continue  # SSE comments
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("id:"):
                block_id = line[3:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())

        data_str = "\n".join(data_lines).strip()
        if not data_str:
            continue

        try:
            payload: dict[str, Any] = json.loads(data_str)
            event_obj = CLIEvent.from_dict(payload, fallback_id=block_id)
            if not event_obj.type or event_obj.type == "event":
                event_obj.type = event_name
            events.append(event_obj)
        except json.JSONDecodeError:
            # Resilient fallback for non-JSON lines without dropping events
            events.append(
                CLIEvent(
                    id=block_id,
                    timestamp="",
                    type=event_name,
                    title=event_name,
                    description=data_str,
                    metadata={"malformed_json": True},
                )
            )

    return events
