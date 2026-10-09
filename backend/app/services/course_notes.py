"""Notes the student adds about a course, such as what the professor said about a midterm.

LEARN does not always carry this (it may be said in class or posted somewhere sync
does not read), so the student writes it down once, optionally about a particular
assessment, and every question about that course gets it as context. Notes are local,
and the context sent with a question is capped to keep each question cheap.
"""

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

MAX_NOTE_CHARS = 4000
MAX_NOTES_PER_COURSE = 50
# Characters of notes sent with one question; the newest notes are kept first.
MAX_CONTEXT_CHARS = 4000
NOTES_FILE = "course_notes.json"


class CourseNoteError(ValueError):
    """The note is empty or too long."""


class CourseNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    text: str
    # The assessment the note is about ("Midterm"), if any.
    about: str | None = None
    added: datetime


def normalize_course(code: str) -> str:
    return re.sub(r"\s+", " ", code).strip().upper()


def list_notes(path: Path, course_code: str | None) -> list[CourseNote]:
    """A course's notes, newest first."""

    if not course_code:
        return []
    notes = _course_notes(_load(path), normalize_course(course_code))
    # Stored in the order added, so a later note wins a tie on the clock.
    ranked = sorted(enumerate(notes), key=lambda pair: (pair[1].added, pair[0]), reverse=True)
    return [note for _, note in ranked]


def add_note(
    path: Path,
    course_code: str,
    text: str,
    *,
    about: str | None = None,
    now: datetime | None = None,
) -> CourseNote:
    tidy = re.sub(r"\n{3,}", "\n\n", text.replace("\r\n", "\n")).strip()
    if not tidy:
        raise CourseNoteError("the note is empty")
    if len(tidy) > MAX_NOTE_CHARS:
        raise CourseNoteError(f"the note is longer than {MAX_NOTE_CHARS} characters")
    data = _load(path)
    course = normalize_course(course_code)
    notes = _course_notes(data, course)
    if len(notes) >= MAX_NOTES_PER_COURSE:
        raise CourseNoteError(f"{course} already has {MAX_NOTES_PER_COURSE} notes; delete some")
    note = CourseNote(
        id=uuid.uuid4().hex[:12],
        text=tidy,
        about=(about or "").strip()[:200] or None,
        added=now or datetime.now(UTC),
    )
    _store(path, data, course, [*notes, note])
    return note


def delete_note(path: Path, course_code: str, note_id: str) -> bool:
    data = _load(path)
    course = normalize_course(course_code)
    notes = _course_notes(data, course)
    kept = [note for note in notes if note.id != note_id]
    if len(kept) == len(notes):
        return False
    _store(path, data, course, kept)
    return True


def clear_notes(path: Path, course_code: str) -> int:
    data = _load(path)
    course = normalize_course(course_code)
    removed = len(_course_notes(data, course))
    if removed:
        _store(path, data, course, [])
    return removed


def tutor_notes(path: Path, course_code: str | None) -> str | None:
    """A course's notes as context for the tutor, newest first, within the size cap."""

    lines: list[str] = []
    used = 0
    for note in list_notes(path, course_code):
        heading = f"- {note.added:%b %d}" + (f", about {note.about}" if note.about else "")
        entry = f"{heading}: {note.text}"
        if used + len(entry) > MAX_CONTEXT_CHARS:
            break
        lines.append(entry)
        used += len(entry)
    return "\n".join(lines) or None


def course_in_question(question: str, known_codes: set[str]) -> str | None:
    """A course code the question names ("for SYDE 212 ..."), if it is a known course."""

    for match in re.finditer(r"\b([A-Za-z]{2,5})\s?(\d{3}[A-Za-z]?)\b", question):
        code = f"{match.group(1).upper()} {match.group(2).upper()}"
        if code in known_codes:
            return code
    return None


def _course_notes(data: dict[str, Any], course: str) -> list[CourseNote]:
    entry = data.get(course)
    if not isinstance(entry, dict):
        return []
    if "notes" not in entry and isinstance(entry.get("text"), str):
        # The first version kept one note per course: read it as that course's first note.
        added = entry.get("updated") or datetime.now(UTC).isoformat()
        return [CourseNote.model_validate({"id": "first", "text": entry["text"], "added": added})]
    notes: list[CourseNote] = []
    for raw in entry.get("notes") or []:
        try:
            notes.append(CourseNote.model_validate(raw))
        except ValidationError:
            continue
    return notes


def _store(path: Path, data: dict[str, Any], course: str, notes: list[CourseNote]) -> None:
    if notes:
        data[course] = {"notes": [note.model_dump(mode="json") for note in notes]}
    else:
        data.pop(course, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
