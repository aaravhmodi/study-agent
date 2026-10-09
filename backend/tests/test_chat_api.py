from pathlib import Path
from typing import Any

import pytest
from app import main
from app.schemas.chat import ChatResponse
from fastapi.testclient import TestClient


class FakeRag:
    """Records what the tutor was asked and with which earlier turns."""

    calls: list[dict[str, Any]] = []

    def __init__(self, settings: Any) -> None:
        pass

    def ask(self, question: str, course_code: str | None, **kwargs: Any) -> ChatResponse:
        history = kwargs.get("history") or []
        FakeRag.calls.append({"question": question, "history": [t.question for t in history]})
        if question == "fail":
            raise RuntimeError("No indexed materials found for SYDE 999.")
        return ChatResponse(answer=f"Answer to {question}")


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    FakeRag.calls = []
    monkeypatch.setattr(main, "_sessions_path", lambda: tmp_path / "sessions.json")
    monkeypatch.setattr(main, "RagService", FakeRag)
    return TestClient(main.app)


def test_a_conversation_keeps_its_turns_for_follow_ups(client: TestClient) -> None:
    first = client.post("/chat", json={"question": "Explain Bayes", "course_code": "SYDE 212"})
    session_id = first.json()["session_id"]
    follow = client.post("/chat", json={"question": "Why divide?", "session_id": session_id})

    assert follow.status_code == 200 and follow.json()["session_id"] == session_id
    assert FakeRag.calls[1] == {"question": "Why divide?", "history": ["Explain Bayes"]}
    session = client.get(f"/chat/sessions/{session_id}").json()
    assert session["title"] == "Explain Bayes" and session["course_code"] == "SYDE 212"
    assert [turn["question"] for turn in session["turns"]] == ["Explain Bayes", "Why divide?"]
    assert session["turns"][1]["response"]["answer"] == "Answer to Why divide?"


def test_sessions_are_listed_and_can_be_deleted(client: TestClient) -> None:
    first = client.post("/chat", json={"question": "Explain Bayes"}).json()["session_id"]
    second = client.post("/chat", json={"question": "Explain shear"}).json()["session_id"]

    listed = client.get("/chat/sessions").json()
    assert [item["id"] for item in listed] == [second, first]
    assert listed[0]["turns"] == 1

    assert client.delete(f"/chat/sessions/{first}").json() == {"deleted": True}
    assert client.get(f"/chat/sessions/{first}").status_code == 404
    assert client.delete(f"/chat/sessions/{first}").status_code == 404


def test_unknown_session_and_failed_answers_do_not_create_sessions(client: TestClient) -> None:
    missing = client.post("/chat", json={"question": "Why?", "session_id": "0" * 32})
    failed = client.post("/chat", json={"question": "fail"})

    assert missing.status_code == 404
    assert failed.status_code == 503
    assert client.get("/chat/sessions").json() == []


def test_session_ids_must_look_like_ids(client: TestClient) -> None:
    response = client.post("/chat", json={"question": "Why?", "session_id": "../etc"})

    assert response.status_code == 422
