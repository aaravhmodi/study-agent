"""Follow-ups continue the earlier response and send only what is new."""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from app import main
from app.config import Settings
from app.schemas.chat import ChatResponse
from app.schemas.chat_session import ChatTurn
from app.services.chat_thread import (
    CHAIN_INPUT_LIMIT,
    MAX_THREADS,
    Thread,
    ThreadStore,
    passage_key,
    unseen,
)
from app.services.rag import RagService
from app.services.retrieval import Passage
from fastapi.testclient import TestClient
from openai import NotFoundError

from tests.fake_openai import LECTURE_7, FakeVectorStores, search_result

COURSE = "SYDE 286"
SHEAR = "Shear force V is the internal transverse force."


class Responses:
    """Answers with a new response id each time, and can lose the earlier response."""

    def __init__(self, input_tokens: int = 9_000, earlier_is_gone: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.input_tokens = input_tokens
        self.earlier_is_gone = earlier_is_gone

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if self.earlier_is_gone and "previous_response_id" in kwargs:
            request = httpx.Request("POST", "https://api.openai.com/v1/responses")
            raise NotFoundError(
                "Previous response not found",
                response=httpx.Response(404, request=request),
                body=None,
            )
        return SimpleNamespace(
            id=f"resp_{len(self.calls)}",
            output_text=f"An answer from {LECTURE_7}.",
            model_dump=lambda: {"output": []},
            usage=SimpleNamespace(
                input_tokens=self.input_tokens,
                output_tokens=400,
                input_tokens_details=SimpleNamespace(cached_tokens=0),
            ),
        )


def service(
    tmp_path: Path, responses: Responses, results: Any = None, **settings: Any
) -> RagService:
    tutor = RagService(
        Settings(_env_file=None, openai_api_key="test-key", **settings),
        client=SimpleNamespace(responses=responses, vector_stores=FakeVectorStores(results)),  # type: ignore[arg-type]
    )
    tutor.manifest_path = tmp_path / "manifest.json"
    tutor.manifest_path.write_text(
        json.dumps({"vector_store_id": "vs-test", "files": {"r1": {"course_code": COURSE}}}),
        encoding="utf-8",
    )
    return tutor


def turn(question: str, answer: str = "V is the internal force.") -> ChatTurn:
    return ChatTurn(
        question=question,
        course_code=COURSE,
        response=ChatResponse(answer=answer),
        asked_at=datetime.now(UTC),
    )


def long_passages(count: int) -> list[Any]:
    """Enough distinct course text to fill a good share of a summary's passages."""
    return [
        search_result(
            f"Lecture_{n:02d}.pdf", " ".join(f"idea{n} point{i} about beams" for i in range(60))
        )
        for n in range(1, count + 1)
    ]


def test_a_first_question_starts_a_thread(tmp_path: Path) -> None:
    responses = Responses()
    tutor = service(tmp_path, responses)

    tutor.ask("Explain shear force.", COURSE)

    (call,) = responses.calls
    assert "previous_response_id" not in call
    assert "Course: SYDE 286" in call["input"] and SHEAR in call["input"]
    assert tutor.thread is not None
    assert (tutor.thread.response_id, tutor.thread.input_tokens) == ("resp_1", 9_000)
    assert [passage.filename for passage in tutor.thread.passages] == [
        LECTURE_7,
        "Tutorial_04_Beams.pdf",
    ]


def test_a_follow_up_continues_it_and_sends_only_the_question(tmp_path: Path) -> None:
    responses = Responses()
    tutor = service(tmp_path, responses)
    tutor.ask("Explain shear force.", COURSE)
    first = tutor.thread

    tutor.ask(
        "Why is it negative there?", COURSE, history=[turn("Explain shear force.")], thread=first
    )

    follow_up = responses.calls[1]
    assert follow_up["previous_response_id"] == "resp_1"
    sent = follow_up["input"]
    assert "New question: Why is it negative there?" in sent
    # Nothing the conversation already has is sent again: not the course, not the
    # earlier exchange, not the passages it was shown.
    assert "Course:" not in sent and "Earlier in this conversation" not in sent
    assert SHEAR not in sent and "No new course passages" in sent
    # The search still looked, with the question it follows.
    searches = tutor.client.vector_stores.calls  # type: ignore[attr-defined]
    assert searches[-1]["query"] == "Explain shear force.\nWhy is it negative there?"
    assert tutor.thread is not None and tutor.thread.response_id == "resp_2"
    assert len(tutor.thread.passages) == 2
    # The answer still gets its full length.
    assert follow_up["max_output_tokens"] == responses.calls[0]["max_output_tokens"]


def test_a_follow_up_on_something_new_sends_only_the_new_passages(tmp_path: Path) -> None:
    responses = Responses()
    tutor = service(tmp_path, responses)
    tutor.ask("Explain shear force.", COURSE)
    first = tutor.thread
    torsion = "Torsion twists a shaft about its axis; tau = T r / J."
    tutor.client.vector_stores.results = [  # type: ignore[attr-defined]
        search_result(LECTURE_7, SHEAR),
        search_result("Lecture_17_Torsion.pdf", torsion),
    ]

    answer = tutor.ask("And torsion?", COURSE, history=[turn("Explain shear force.")], thread=first)

    sent = responses.calls[1]["input"]
    assert "More course passages" in sent and torsion in sent and SHEAR not in sent
    assert tutor.thread is not None
    assert [passage.filename for passage in tutor.thread.passages] == [
        LECTURE_7,
        "Tutorial_04_Beams.pdf",
        "Lecture_17_Torsion.pdf",
    ]
    # A file shown earlier in the conversation can still be cited.
    assert LECTURE_7 in {citation.filename for citation in answer.citations}


def test_without_a_thread_a_follow_up_is_built_from_the_conversation(tmp_path: Path) -> None:
    responses = Responses()
    tutor = service(tmp_path, responses)

    tutor.ask("Why?", COURSE, history=[turn("Explain shear force.")])

    (call,) = responses.calls
    assert "previous_response_id" not in call
    assert "Earlier in this conversation" in call["input"] and SHEAR in call["input"]
    # And that starts a thread for the next one.
    assert tutor.thread is not None and tutor.thread.response_id == "resp_1"


def test_a_conversation_grown_too_long_starts_over(tmp_path: Path) -> None:
    responses = Responses()
    tutor = service(tmp_path, responses)
    long_thread = Thread(response_id="resp_old", input_tokens=CHAIN_INPUT_LIMIT + 1)

    tutor.ask("Why?", COURSE, history=[turn("Explain shear force.")], thread=long_thread)

    assert "previous_response_id" not in responses.calls[0]
    assert "Earlier in this conversation" in responses.calls[0]["input"]


def test_when_the_earlier_response_is_gone_the_answer_is_built_from_scratch(
    tmp_path: Path,
) -> None:
    responses = Responses(earlier_is_gone=True)
    tutor = service(tmp_path, responses)
    lost = Thread(response_id="resp_expired", input_tokens=9_000)

    answer = tutor.ask("Why?", COURSE, history=[turn("Explain shear force.")], thread=lost)

    tried, rebuilt = responses.calls
    assert tried["previous_response_id"] == "resp_expired"
    assert (
        "previous_response_id" not in rebuilt and "Earlier in this conversation" in rebuilt["input"]
    )
    assert answer.answer.startswith("An answer") and tutor.thread is not None
    assert tutor.thread.response_id == "resp_2"


def test_the_web_is_searched_when_the_course_files_match_little(tmp_path: Path) -> None:
    web = [{"type": "web_search", "search_context_size": "low"}]

    thin = Responses()
    service(tmp_path, thin).ask("Explain shear force.", COURSE)
    assert thin.calls[0]["tools"] == web

    covered = Responses()
    service(tmp_path, covered, long_passages(6)).ask("Explain beams.", COURSE)
    assert covered.calls[0]["tools"] == []


def test_the_web_is_searched_when_asked_for_or_always_and_never_when_off(tmp_path: Path) -> None:
    web = [{"type": "web_search", "search_context_size": "low"}]

    asked = Responses()
    service(tmp_path, asked, long_passages(6)).ask("Search the web for beam failures.", COURSE)
    assert asked.calls[0]["tools"] == web

    always = Responses()
    service(tmp_path, always, long_passages(6), rag_web_search_always=True).ask("Beams?", COURSE)
    assert always.calls[0]["tools"] == web

    off = Responses()
    service(tmp_path, off, rag_web_search=False).ask("Search the web for beam failures.", COURSE)
    assert off.calls[0]["tools"] == []


def test_the_same_text_from_the_same_file_is_not_sent_twice() -> None:
    shown = Passage(filename="L7.pdf", file_id="f1", text="Shear  force V.\n", score=0.9)
    again = Passage(filename="L7.pdf", file_id="f1", text="Shear force V.", score=0.4)
    other = Passage(filename="L8.pdf", file_id="f2", text="Shear force V.", score=0.4)

    assert passage_key(shown) == passage_key(again) != passage_key(other)
    assert unseen([again, other, other], Thread(response_id="r", passages=[shown])) == [other]


def test_threads_are_kept_per_conversation_and_the_oldest_dropped(tmp_path: Path) -> None:
    store = ThreadStore(tmp_path / "threads.json")
    assert store.get("a") is None

    for number in range(MAX_THREADS + 1):
        store.put(f"chat-{number}", Thread(response_id=f"resp_{number}"))

    assert store.get("chat-0") is None
    newest = store.get(f"chat-{MAX_THREADS}")
    assert newest is not None and newest.response_id == f"resp_{MAX_THREADS}"
    store.put(f"chat-{MAX_THREADS}", None)
    assert store.get(f"chat-{MAX_THREADS}") is None


def test_the_chat_keeps_each_conversations_thread_and_forgets_it_when_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Thread | None] = []

    class Tutor:
        def __init__(self, settings: Any) -> None:
            self.thread: Thread | None = None

        def ask(self, question: str, course_code: str | None = None, **kwargs: Any) -> ChatResponse:
            seen.append(kwargs["thread"])
            self.thread = Thread(response_id=f"resp_{len(seen)}")
            return ChatResponse(answer="An answer.")

    monkeypatch.setattr(main, "RagService", Tutor)
    monkeypatch.setattr(main, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(main, "_sessions_path", lambda: tmp_path / "sessions.json")
    client = TestClient(main.app)

    session_id = client.post("/chat", json={"question": "Explain shear"}).json()["session_id"]
    client.post("/chat", json={"question": "Why?", "session_id": session_id})
    client.post("/chat", json={"question": "And then?", "session_id": session_id})

    # The first question has no thread; each follow-up gets the one the last answer left.
    assert [thread.response_id if thread else None for thread in seen] == [None, "resp_1", "resp_2"]
    assert ThreadStore(tmp_path / "chat_threads.json").get(session_id) is not None
    client.delete(f"/chat/sessions/{session_id}")
    assert ThreadStore(tmp_path / "chat_threads.json").get(session_id) is None
