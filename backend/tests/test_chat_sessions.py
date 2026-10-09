from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app.schemas.chat import ChatResponse
from app.services.chat_sessions import MAX_SESSIONS, MAX_TURNS, ChatSessionStore

NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)


def _answer(text: str = "Bayes relates P(A|B) and P(B|A).") -> ChatResponse:
    return ChatResponse(answer=text)


def test_a_session_keeps_its_turns_in_order(tmp_path: Path) -> None:
    store = ChatSessionStore(tmp_path / "sessions.json")
    session = store.create("Explain   Bayes theorem", "SYDE 212", now=NOW)

    store.add_turn(session.id, "Explain Bayes theorem", "SYDE 212", _answer(), now=NOW)
    store.add_turn(session.id, "Why divide by P(B)?", "SYDE 212", _answer("To normalize."), now=NOW)

    loaded = store.get(session.id)
    assert loaded is not None
    assert loaded.title == "Explain Bayes theorem"
    assert [turn.question for turn in loaded.turns] == [
        "Explain Bayes theorem",
        "Why divide by P(B)?",
    ]
    assert loaded.turns[1].response.answer == "To normalize."


def test_long_first_questions_make_short_titles(tmp_path: Path) -> None:
    session = ChatSessionStore(tmp_path / "s.json").create("word " * 40, None, now=NOW)

    assert len(session.title) == 80 and session.title.endswith("…")


def test_sessions_are_listed_newest_first(tmp_path: Path) -> None:
    store = ChatSessionStore(tmp_path / "sessions.json")
    old = store.create("Explain shear force", "SYDE 286", now=NOW)
    new = store.create("Explain Bayes", "SYDE 212", now=NOW + timedelta(minutes=1))
    store.add_turn(
        old.id, "Explain shear force", "SYDE 286", _answer(), now=NOW + timedelta(minutes=2)
    )

    summaries = store.list()

    assert [item.id for item in summaries] == [old.id, new.id]
    assert summaries[0].turns == 1 and summaries[1].turns == 0


def test_delete_and_unknown_sessions(tmp_path: Path) -> None:
    store = ChatSessionStore(tmp_path / "sessions.json")
    session = store.create("Explain Bayes", None, now=NOW)

    assert store.delete(session.id) is True
    assert store.get(session.id) is None
    assert store.delete(session.id) is False
    with pytest.raises(KeyError):
        store.add_turn(session.id, "q", None, _answer())


def test_only_the_newest_sessions_and_turns_are_kept(tmp_path: Path) -> None:
    store = ChatSessionStore(tmp_path / "sessions.json")
    first = store.create("first", None, now=NOW)
    for index in range(MAX_TURNS + 3):
        store.add_turn(first.id, f"q{index}", None, _answer(), now=NOW + timedelta(seconds=index))
    for index in range(MAX_SESSIONS):
        store.create(f"later {index}", None, now=NOW + timedelta(hours=1, seconds=index))

    assert store.get(first.id) is None  # pushed out by newer sessions
    assert len(store.list(limit=500)) == MAX_SESSIONS


def test_turns_are_capped_per_session(tmp_path: Path) -> None:
    store = ChatSessionStore(tmp_path / "sessions.json")
    session = store.create("first", None, now=NOW)
    for index in range(MAX_TURNS + 3):
        store.add_turn(session.id, f"q{index}", None, _answer(), now=NOW)

    loaded = store.get(session.id)
    assert loaded is not None and len(loaded.turns) == MAX_TURNS
    assert loaded.turns[0].question == "q3"


def test_a_corrupt_file_reads_as_no_sessions(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    path.write_text("{not json", encoding="utf-8")

    assert ChatSessionStore(path).list() == []
