from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.schemas.chat import ChatResponse
from app.services.answer_cache import (
    MAX_ENTRIES,
    AnswerCache,
    cache_key,
    index_fingerprint,
    normalize_question,
)

NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)
SETTINGS = {"model": "gpt-6-luna", "prompt": "abc", "index": "f1"}


def _response(text: str = "Shear force is V.") -> ChatResponse:
    return ChatResponse(answer=text, citations=[{"filename": "Lecture-1.txt"}])


def test_equivalent_questions_share_a_key() -> None:
    assert normalize_question("  Explain   Shear force?? ") == "explain shear force"
    assert cache_key("Explain shear force.", "SYDE 286", settings=SETTINGS) == cache_key(
        "explain shear force", "SYDE 286", settings=SETTINGS
    )


def test_course_model_prompt_and_index_change_the_key() -> None:
    base = cache_key("Explain shear force.", "SYDE 286", settings=SETTINGS)

    assert base != cache_key("Explain shear force.", "SYDE 212", settings=SETTINGS)
    for name in SETTINGS:
        assert base != cache_key(
            "Explain shear force.", "SYDE 286", settings={**SETTINGS, name: "changed"}
        )


def test_index_fingerprint_follows_file_contents() -> None:
    files = {"r1": {"content_hash": "a"}, "r2": {"content_hash": "b"}}

    assert index_fingerprint(files) == index_fingerprint(dict(reversed(files.items())))
    assert index_fingerprint(files) != index_fingerprint({**files, "r2": {"content_hash": "c"}})
    assert index_fingerprint(files) != index_fingerprint({"r1": {"content_hash": "a"}})


def test_saved_answers_come_back_until_they_expire(tmp_path: Path) -> None:
    cache = AnswerCache(tmp_path / "cache.json")
    cache.put("k", _response(), now=NOW)

    assert cache.get("k", now=NOW + timedelta(days=13)) == _response()
    assert cache.get("k", now=NOW + timedelta(days=15)) is None
    assert cache.get("missing", now=NOW) is None


def test_only_the_newest_entries_are_kept(tmp_path: Path) -> None:
    cache = AnswerCache(tmp_path / "cache.json")
    for index in range(MAX_ENTRIES + 5):
        cache.put(f"k{index}", _response(), now=NOW + timedelta(seconds=index))

    assert cache.get("k0", now=NOW) is None
    assert cache.get(f"k{MAX_ENTRIES + 4}", now=NOW) is not None


def test_a_corrupt_cache_file_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    path.write_text("{not json", encoding="utf-8")
    cache = AnswerCache(path)

    assert cache.get("k") is None
    cache.put("k", _response(), now=NOW)
    assert cache.get("k", now=NOW) is not None
