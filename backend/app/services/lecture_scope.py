"""Match "Lecture 7" / "week 3" / "chapter 5" in a question to indexed course files."""

import re
from typing import Any

from app.services.answer_format import display_filename

# Each family lists the spellings that refer to the same kind of unit.
_FAMILIES: dict[str, tuple[str, ...]] = {
    "lecture": ("lecture", "lec", "l"),
    "week": ("week", "wk", "w"),
    "chapter": ("chapter", "ch", "chap"),
    "tutorial": ("tutorial", "tut"),
    "module": ("module", "mod", "unit"),
    "lab": ("lab",),
}
_QUESTION_REF = re.compile(
    r"\b(lectures?|lec|weeks?|chapters?|ch|tutorials?|tut|modules?|units?|labs?)"
    r"\.?\s*#?\s*(\d{1,2})\b",
    flags=re.IGNORECASE,
)


def lecture_refs(question: str) -> set[tuple[str, int]]:
    """Return (family, number) pairs such as ("lecture", 7) named in a question."""

    refs: set[tuple[str, int]] = set()
    for word, number in _QUESTION_REF.findall(question):
        word = word.lower()
        family = next(
            name
            for name, spellings in _FAMILIES.items()
            if word in spellings or word.removesuffix("s") in spellings
        )
        refs.add((family, int(number)))
    return refs


def matching_resource_ids(
    question: str, files: dict[str, Any], course_code: str | None
) -> list[str]:
    """Resource ids of indexed files whose names match a lecture the question names."""

    refs = lecture_refs(question)
    if not refs:
        return []
    matches: list[str] = []
    for resource_id, entry in files.items():
        if course_code and str(entry.get("course_code", "")).upper() != course_code:
            continue
        name = _normalize(display_filename(str(entry.get("filename", ""))))
        if any(_names(name, family, number) for family, number in refs):
            matches.append(resource_id)
    return sorted(matches)


def _normalize(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0].lower()
    return re.sub(r"[_\-.]+", " ", stem)


def _names(name: str, family: str, number: int) -> bool:
    spellings = "|".join(_FAMILIES[family])
    pattern = rf"(?<![a-z])(?:{spellings})s?\s*0*{number}(?!\d)"
    return re.search(pattern, name) is not None
