import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app.services.course_notes import (
    MAX_CONTEXT_CHARS,
    MAX_NOTE_CHARS,
    CourseNoteError,
    add_note,
    clear_notes,
    course_in_question,
    delete_note,
    list_notes,
    tutor_notes,
)

NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)


def test_a_course_keeps_several_notes_newest_first(tmp_path: Path) -> None:
    path = tmp_path / "notes.json"
    add_note(
        path, " syde  212 ", "Midterm: chapters 1-4.\r\n\n\n\n40 MC.", about="Midterm", now=NOW
    )
    add_note(
        path,
        "SYDE 212",
        "Report needs 3 figures.",
        about="Final Report",
        now=NOW + timedelta(days=1),
    )

    notes = list_notes(path, "SYDE 212")

    assert [note.about for note in notes] == ["Final Report", "Midterm"]
    assert notes[1].text == "Midterm: chapters 1-4.\n\n40 MC."
    assert list_notes(path, "SYDE 286") == [] and list_notes(path, None) == []


def test_notes_are_given_to_the_tutor_with_what_they_are_about(tmp_path: Path) -> None:
    path = tmp_path / "notes.json"
    add_note(path, "SYDE 212", "Midterm: chapters 1-4.", about="Midterm", now=NOW)
    add_note(path, "SYDE 212", "Office hours moved to Friday.", now=NOW + timedelta(days=1))

    assert tutor_notes(path, "SYDE 212") == (
        "- Oct 10: Office hours moved to Friday.\n- Oct 09, about Midterm: Midterm: chapters 1-4."
    )
    assert tutor_notes(path, "SYDE 286") is None


def test_tutor_context_keeps_the_newest_notes_within_the_cap(tmp_path: Path) -> None:
    path = tmp_path / "notes.json"
    for day in range(5):
        add_note(path, "SYDE 212", f"note {day} " + "x" * 1500, now=NOW + timedelta(days=day))

    context = tutor_notes(path, "SYDE 212") or ""

    assert len(context) <= MAX_CONTEXT_CHARS
    assert "note 4" in context and "note 0" not in context


def test_notes_can_be_deleted_one_at_a_time_or_all(tmp_path: Path) -> None:
    path = tmp_path / "notes.json"
    first = add_note(path, "SYDE 212", "one", now=NOW)
    add_note(path, "SYDE 212", "two", now=NOW)

    assert delete_note(path, "syde 212", first.id) is True
    assert delete_note(path, "SYDE 212", first.id) is False
    assert [note.text for note in list_notes(path, "SYDE 212")] == ["two"]
    assert clear_notes(path, "SYDE 212") == 1
    assert list_notes(path, "SYDE 212") == []


def test_a_note_saved_by_the_first_version_is_kept(tmp_path: Path) -> None:
    path = tmp_path / "notes.json"
    path.write_text(
        json.dumps({"SYDE 212": {"text": "Midterm Oct 20.", "updated": NOW.isoformat()}}),
        encoding="utf-8",
    )

    (old,) = list_notes(path, "SYDE 212")
    add_note(path, "SYDE 212", "New note.", now=NOW + timedelta(days=1))

    assert old.text == "Midterm Oct 20."
    assert [note.text for note in list_notes(path, "SYDE 212")] == ["New note.", "Midterm Oct 20."]


@pytest.mark.parametrize(
    ("text", "reason"), [("  \n ", "empty"), ("x" * (MAX_NOTE_CHARS + 1), "longer")]
)
def test_empty_or_long_notes_are_rejected(tmp_path: Path, text: str, reason: str) -> None:
    with pytest.raises(CourseNoteError, match=reason):
        add_note(tmp_path / "notes.json", "SYDE 212", text)


def test_a_corrupt_notes_file_reads_as_empty(tmp_path: Path) -> None:
    path = tmp_path / "notes.json"
    path.write_text("{oops", encoding="utf-8")

    assert tutor_notes(path, "SYDE 212") is None
    add_note(path, "SYDE 212", "ok")
    assert [note.text for note in list_notes(path, "SYDE 212")] == ["ok"]


def test_course_named_in_a_question_is_found() -> None:
    known = {"SYDE 212", "SYDE 292L"}

    assert course_in_question("What's on the syde212 midterm?", known) == "SYDE 212"
    assert course_in_question("Explain the SYDE 292L lab", known) == "SYDE 292L"
    assert course_in_question("Explain MATH 115 limits", known) is None
    assert course_in_question("Explain Bayes", known) is None


def test_notes_from_the_same_clock_tick_list_newest_added_first(tmp_path: Path) -> None:
    path = tmp_path / "notes.json"
    for text in ("one", "two", "three"):
        add_note(path, "SYDE 212", text, now=NOW)

    assert [note.text for note in list_notes(path, "SYDE 212")] == ["three", "two", "one"]
