from irtrixai_cli.events import parse_sse_snapshot


def test_parse_empty_sse():
    assert parse_sse_snapshot("") == []
    assert parse_sse_snapshot("   \n\n ") == []


def test_parse_standard_sse_snapshot():
    raw = (
        "event: workspace_inspected\n"
        'data: {"id": "evt_1", "timestamp": "2026-09-19T06:00:00", "type": "workspace_inspected", '
        '"title": "Workspace Inspected", "description": "Detected python stack", "metadata": {"files": 2}}\n\n'
        "event: task_started\n"
        'data: {"id": "evt_2", "timestamp": "2026-09-19T06:00:01", "type": "task_started", '
        '"title": "Agent Task Started", "description": "Planner initialized"}\n\n'
    )
    events = parse_sse_snapshot(raw)
    assert len(events) == 2
    assert events[0].type == "workspace_inspected"
    assert events[0].title == "Workspace Inspected"
    assert events[0].metadata["files"] == 2
    assert events[1].type == "task_started"
    assert events[1].id == "evt_2"


def test_parse_sse_with_malformed_json():
    raw = "event: custom_event\ndata: this is not json\n\n"
    events = parse_sse_snapshot(raw)
    assert len(events) == 1
    assert events[0].type == "custom_event"
    assert events[0].description == "this is not json"
    assert events[0].metadata.get("malformed_json") is True
