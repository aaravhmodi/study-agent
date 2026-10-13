import json
from pathlib import Path
from typing import Any

FLOW = Path(__file__).parents[2] / "n8n" / "workflows" / "assistant.json"


def tools() -> dict[str, dict[str, Any]]:
    flow = json.loads(FLOW.read_text(encoding="utf-8"))
    return {
        node["name"]: node["parameters"]
        for node in flow["nodes"]
        if node["type"] == "n8n-nodes-base.httpRequestTool"
    }


def test_the_assistant_can_only_look_things_up_start_a_sync_or_preview_follow_ups() -> None:
    requests = {(tool["method"], tool["url"].split("}}")[-1]) for tool in tools().values()}

    assert requests == {
        ("GET", "/assessments"),
        ("GET", "/practice/plan"),
        ("GET", "/practice/checkup"),
        ("GET", "/jobs"),
        ("POST", "/jobs/sync"),
        ("GET", "/api/leads"),
        ("POST", "/api/followups/run"),
    }


def test_the_model_never_chooses_what_a_request_sends() -> None:
    found = tools()

    # A follow-up run is always the preview: the body is fixed, not written by the model.
    assert json.loads(found["Follow-ups preview"]["jsonBody"]) == {"dry_run": True}
    assert [name for name, tool in found.items() if "sendBody" in tool] == ["Follow-ups preview"]
    assert "$fromAI" not in json.dumps(found)


def test_no_key_or_token_is_written_into_the_workflow() -> None:
    text = FLOW.read_text(encoding="utf-8")

    assert "sk-" not in text
    assert text.count("Bearer") == text.count("Bearer {{ $env.STUDY_AGENT_TOKEN }}")
