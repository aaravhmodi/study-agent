"""Reuse answers to questions already asked, so a repeat costs no tokens.

An entry is keyed by the normalized question, the course and everything that
shapes an answer (model, prompt, retrieval settings, the indexed files), so any
of those changing is a miss. Entries expire after a while and the file keeps
only the most recent ones.
"""

import hashlib
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.schemas.chat import ChatResponse

logger = logging.getLogger(__name__)

MAX_ENTRIES = 300
MAX_AGE = timedelta(days=14)


def normalize_question(question: str) -> str:
    """Case, spacing and trailing punctuation do not make a different question."""

    return re.sub(r"\s+", " ", question).strip().rstrip("?.! ").lower()


def cache_key(question: str, course_code: str | None, *, settings: dict[str, Any]) -> str:
    payload = json.dumps(
        {"question": normalize_question(question), "course": course_code, **settings},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def index_fingerprint(files: dict[str, Any]) -> str:
    """Changes whenever a file is added, removed or re-indexed."""

    items = sorted(
        (key, str(entry.get("content_hash", "")), str(entry.get("chunking", "")))
        for key, entry in files.items()
    )
    return hashlib.sha256(json.dumps(items).encode("utf-8")).hexdigest()[:16]


class AnswerCache:
    def __init__(self, path: Path) -> None:
        self.path = path

    def get(self, key: str, *, now: datetime | None = None) -> ChatResponse | None:
        entry = self._load().get(key)
        if not entry:
            return None
        saved = datetime.fromisoformat(entry["saved"])
        if (now or datetime.now(UTC)) - saved > MAX_AGE:
            return None
        try:
            return ChatResponse.model_validate(entry["response"])
        except ValidationError:
            return None

    def put(self, key: str, response: ChatResponse, *, now: datetime | None = None) -> None:
        entries = self._load()
        entries[key] = {
            "saved": (now or datetime.now(UTC)).isoformat(),
            "response": response.model_dump(mode="json"),
        }
        newest = sorted(entries.items(), key=lambda item: item[1]["saved"], reverse=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(dict(newest[:MAX_ENTRIES])), encoding="utf-8")

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Answer cache unreadable; starting a new one")
            return {}
        return data if isinstance(data, dict) else {}
