"""Notes the student adds about a course, such as what the instructor said a midterm covers.

LEARN does not always carry this (it may be said in class or posted somewhere sync
does not read), so the student pastes it once and every question about that course
gets it as context. Notes are local and capped in length to keep each question cheap.
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MAX_NOTE_CHARS = 4000


class CourseNoteError(ValueError):
    """The note is empty or too long."""


def normalize_course(code: str) -> str:
    return re.sub(r"\s+", " ", code).strip().upper()


def load_notes(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def get_note(path: Path, course_code: str | None) -> str | None:
    if not course_code:
        return None
    entry = load_notes(path).get(normalize_course(course_code))
    text = entry.get("text") if isinstance(entry, dict) else None
    return text if isinstance(text, str) and text.strip() else None


def save_note(path: Path, course_code: str, text: str, *, now: datetime | None = None) -> str:
    """Store the note for a course (replacing any earlier one) and return it tidied."""

    tidy = re.sub(r"\n{3,}", "\n\n", text.replace("\r\n", "\n")).strip()
    if not tidy:
        raise CourseNoteError("the note is empty; use --clear to remove it")
    if len(tidy) > MAX_NOTE_CHARS:
        raise CourseNoteError(f"the note is longer than {MAX_NOTE_CHARS} characters")
    notes = load_notes(path)
    notes[normalize_course(course_code)] = {
        "text": tidy,
        "updated": (now or datetime.now(UTC)).isoformat(),
    }
    _write(path, notes)
    return tidy


def clear_note(path: Path, course_code: str) -> bool:
    notes = load_notes(path)
    removed = notes.pop(normalize_course(course_code), None) is not None
    if removed:
        _write(path, notes)
    return removed


def course_in_question(question: str, known_codes: set[str]) -> str | None:
    """A course code the question names ("for SYDE 212 ..."), if it is a known course."""

    for match in re.finditer(r"\b([A-Za-z]{2,5})\s?(\d{3}[A-Za-z]?)\b", question):
        code = f"{match.group(1).upper()} {match.group(2).upper()}"
        if code in known_codes:
            return code
    return None


def _write(path: Path, notes: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(notes, indent=2, ensure_ascii=False), encoding="utf-8")
