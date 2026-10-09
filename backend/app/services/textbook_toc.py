"""Read a textbook's table of contents so questions about "chapter 3" find chapter 3.

Semantic search cannot tell what "chapter 3" means, but the book's contents page
can: it names each chapter, its sections and its pages. This parses that page from
the extracted text once, at index time.
"""

import re
import unicodedata

from pydantic import BaseModel, ConfigDict

# "3 Descriptive Statistics 21" or "3.3.2 Measures of Central Tendency . . . . 34"
_ENTRY = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,2})\s+(.+?)\s*(?:\.\s*)*\s(\d{1,4})$")
_STARTS_WITH_NUMBER = re.compile(r"^\d{1,2}(?:\.\d{1,2}){0,2}\s+\S")
# Lines to ignore inside the contents: page labels, running headers, roman page numbers.
_NOISE = re.compile(r"^\[(?:Page|Front matter)[^\]]*\]$|contents|^[ivxlc]+$", re.IGNORECASE)
_SCAN_CHARS = 80_000
_GIVE_UP_AFTER = 25


class TocEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: str
    title: str
    page: int


class Chapter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: int
    title: str
    first_page: int
    last_page: int | None = None
    sections: list[str]


def parse_contents(text: str) -> list[TocEntry]:
    """Entries of the first contents page found near the start of a document."""

    head = text[:_SCAN_CHARS]
    start = re.search(r"^\s*(?:table of )?contents\s*$", head, re.IGNORECASE | re.MULTILINE)
    if not start:
        return []
    entries: list[TocEntry] = []
    misses = 0
    pending = ""
    for raw in head[start.end() :].splitlines():
        line = raw.strip()
        if not line or _NOISE.search(line):
            continue
        if pending:
            # A title wrapped onto this line ("... Distribu-" / "tion 97").
            line = pending.removesuffix("-") + ("" if pending.endswith("-") else " ") + line
            pending = ""
        match = _ENTRY.match(line)
        if match:
            # NFKC turns PDF ligatures ("Conﬁdence") into plain letters.
            title = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", match.group(2))).strip(" .")
            entries.append(TocEntry(number=match.group(1), title=title, page=int(match.group(3))))
            misses = 0
        elif _STARTS_WITH_NUMBER.match(line) and len(line) < 160:
            pending = line
        else:
            misses += 1
            if entries and misses > _GIVE_UP_AFTER:
                break
    return entries


def chapters(entries: list[TocEntry]) -> list[Chapter]:
    """Chapters with their top-level sections and page ranges."""

    tops = [entry for entry in entries if "." not in entry.number]
    result: list[Chapter] = []
    for index, top in enumerate(tops):
        following = tops[index + 1] if index + 1 < len(tops) else None
        sections = [
            f"{entry.number} {entry.title}"
            for entry in entries
            if entry.number.count(".") == 1 and entry.number.split(".")[0] == top.number
        ]
        result.append(
            Chapter(
                number=int(top.number),
                title=top.title,
                first_page=top.page,
                last_page=following.page - 1 if following else None,
                sections=sections,
            )
        )
    # A real table of contents has several chapters in order.
    numbers = [chapter.number for chapter in result]
    if len(result) < 3 or numbers != sorted(set(numbers)):
        return []
    return result


def describe(chapter: Chapter) -> str:
    """One line for the tutor: title, pages and sections."""

    pages = (
        f"pp. {chapter.first_page}-{chapter.last_page}"
        if chapter.last_page
        else f"from p. {chapter.first_page}"
    )
    sections = "; ".join(chapter.sections)
    return f"Chapter {chapter.number}: {chapter.title} ({pages})" + (
        f": {sections}" if sections else ""
    )
