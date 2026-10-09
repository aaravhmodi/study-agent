from pathlib import Path

import pytest
from app.services.course_notes import (
    MAX_NOTE_CHARS,
    CourseNoteError,
    clear_note,
    course_in_question,
    get_note,
    save_note,
)

MIDTERM = "Midterm: Oct 20.\r\nChapters 1-4, Major Topic 1, R coding (2 questions).\n\n\n\n40 MC."


def test_notes_are_saved_per_course_and_tidied(tmp_path: Path) -> None:
    path = tmp_path / "notes.json"

    saved = save_note(path, " syde  212 ", MIDTERM)

    assert (
        saved == "Midterm: Oct 20.\nChapters 1-4, Major Topic 1, R coding (2 questions).\n\n40 MC."
    )
    assert get_note(path, "SYDE 212") == saved
    assert get_note(path, "SYDE 286") is None
    assert get_note(path, None) is None


def test_saving_again_replaces_and_clear_removes(tmp_path: Path) -> None:
    path = tmp_path / "notes.json"
    save_note(path, "SYDE 212", MIDTERM)
    save_note(path, "SYDE 212", "Final covers everything.")

    assert get_note(path, "SYDE 212") == "Final covers everything."
    assert clear_note(path, "syde 212") is True
    assert get_note(path, "SYDE 212") is None
    assert clear_note(path, "SYDE 212") is False


@pytest.mark.parametrize(
    ("text", "reason"), [("  \n ", "empty"), ("x" * (MAX_NOTE_CHARS + 1), "longer")]
)
def test_empty_or_long_notes_are_rejected(tmp_path: Path, text: str, reason: str) -> None:
    with pytest.raises(CourseNoteError, match=reason):
        save_note(tmp_path / "notes.json", "SYDE 212", text)


def test_a_corrupt_notes_file_reads_as_empty(tmp_path: Path) -> None:
    path = tmp_path / "notes.json"
    path.write_text("{oops", encoding="utf-8")

    assert get_note(path, "SYDE 212") is None
    save_note(path, "SYDE 212", "ok")
    assert get_note(path, "SYDE 212") == "ok"


def test_course_named_in_a_question_is_found() -> None:
    known = {"SYDE 212", "SYDE 292L"}

    assert course_in_question("What's on the syde212 midterm?", known) == "SYDE 212"
    assert course_in_question("Explain the SYDE 292L lab", known) == "SYDE 292L"
    assert course_in_question("Explain MATH 115 limits", known) is None
    assert course_in_question("Explain Bayes", known) is None
