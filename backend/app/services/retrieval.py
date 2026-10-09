"""Pick the course passages a question needs, within a token budget.

The tutor used to call file search itself: it often ran several searches, got the
same chunk back two or three times, and was sent every result. Here the persistent
vector store is searched once, duplicates and near-duplicates are dropped, each
file contributes a few passages at most, and passages stop at a token budget.
"""

import re
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.services.answer_format import display_filename

# Rough tokens-per-character for English course text; good enough for a budget.
CHARS_PER_TOKEN = 4
_SHINGLE = 8


class Passage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    file_id: str
    text: str
    score: float

    @property
    def tokens(self) -> int:
        return len(self.text) // CHARS_PER_TOKEN + 1


def tidy(text: str) -> str:
    """Collapse the blank lines and runs of spaces PDF extraction leaves behind."""

    text = re.sub(r"[ \t\f\v]+", " ", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = re.sub(r" ?\n ?", "\n", text)
    return re.sub(r"\n{2,}", "\n", text).strip()


def from_search(results: Iterable[Any]) -> list[Passage]:
    """Turn vector-store search results into passages."""

    passages: list[Passage] = []
    for result in results:
        text = tidy(" ".join(getattr(part, "text", "") for part in result.content))
        if text:
            passages.append(
                Passage(
                    filename=display_filename(str(result.filename)),
                    file_id=str(result.file_id),
                    text=text,
                    score=float(result.score),
                )
            )
    return passages


def select_passages(
    passages: list[Passage],
    *,
    budget_tokens: int,
    max_passages: int,
    per_file: int = 3,
    overlap_limit: float = 0.6,
) -> list[Passage]:
    """Best passages first, skipping repeats, capped per file and by total tokens."""

    chosen: list[Passage] = []
    shingles: list[set[str]] = []
    per_file_count: dict[str, int] = {}
    used = 0
    for passage in sorted(passages, key=lambda item: item.score, reverse=True):
        if len(chosen) >= max_passages:
            break
        if per_file_count.get(passage.file_id, 0) >= per_file:
            continue
        words = _shingles(passage.text)
        if any(_overlap(words, other) > overlap_limit for other in shingles):
            continue
        if used + passage.tokens > budget_tokens:
            # Always send at least one passage, trimmed to the budget.
            if not chosen:
                trimmed = passage.text[: budget_tokens * CHARS_PER_TOKEN]
                chosen.append(passage.model_copy(update={"text": trimmed}))
            continue
        chosen.append(passage)
        shingles.append(words)
        per_file_count[passage.file_id] = per_file_count.get(passage.file_id, 0) + 1
        used += passage.tokens
    return chosen


def format_passages(passages: list[Passage]) -> str:
    """The passages as the model sees them, each headed by the file to cite."""

    if not passages:
        return "Course passages: none matched this question."
    blocks = [f"[{passage.filename}]\n{passage.text}" for passage in passages]
    return "Course passages (cite by file name):\n\n" + "\n\n".join(blocks)


def cited_files(answer: str, passages: list[Passage]) -> list[dict[str, str | None]]:
    """Files the answer cites by name, or every passage file if it names none."""

    files: dict[str, str] = {}
    for passage in passages:
        files.setdefault(passage.filename, passage.file_id)
    lowered = answer.lower()
    named = {
        name: file_id
        for name, file_id in files.items()
        if name.lower() in lowered or name.rsplit(".", 1)[0].lower() in lowered
    }
    return [
        {"filename": name, "file_id": file_id, "kind": "file"}
        for name, file_id in (named or files).items()
    ]


def _shingles(text: str) -> set[str]:
    words = re.findall(r"\w+", text.lower())
    if len(words) <= _SHINGLE:
        return {" ".join(words)}
    return {" ".join(words[i : i + _SHINGLE]) for i in range(len(words) - _SHINGLE + 1)}


def _overlap(first: set[str], second: set[str]) -> float:
    if not first or not second:
        return 0.0
    return len(first & second) / min(len(first), len(second))
