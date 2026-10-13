"""What a conversation has already sent to the model, so a follow-up sends only what is new.

Input is most of what the tutor costs, and most questions are follow-ups. Each used to be
built from scratch: the course passages searched and sent again, and a shortened copy of
the last few exchanges, none of it text the model had been sent before, so none of it at
the cached rate. A follow-up now continues the earlier response instead
(``previous_response_id``): everything already sent is read from the prompt cache at a
tenth of the price, and only the new question and passages the conversation has not yet
seen are sent fresh. Answers are as long as before; nothing is cut.

This module keeps, for each conversation, the response to continue from and the passages
it has been shown (to skip them, and to resolve citations of them later).
"""

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.services.retrieval import Passage

logger = logging.getLogger(__name__)

THREADS_FILE = "chat_threads.json"
MAX_THREADS = 100
# Past this much input, continuing costs more than starting over. A continued request
# reads its earlier text at 0.1x and writes about 3,000 new tokens at 1.25x; one built
# from scratch reads the instructions and writes about 6,000. They meet near 45,000.
CHAIN_INPUT_LIMIT = 40_000


class Thread(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The model's last response in the conversation, which the next one continues.
    response_id: str
    # Every passage the conversation has been sent, in order.
    passages: list[Passage] = Field(default_factory=list)
    # How much input the last request was, earlier turns included.
    input_tokens: int = 0

    @property
    def can_continue(self) -> bool:
        return bool(self.response_id) and self.input_tokens <= CHAIN_INPUT_LIMIT


def passage_key(passage: Passage) -> str:
    """The same text from the same file is the same passage, however it was found."""
    text = " ".join(passage.text.split())
    return hashlib.sha256(f"{passage.filename}\n{text}".encode()).hexdigest()[:20]


def unseen(passages: list[Passage], thread: Thread) -> list[Passage]:
    """The passages the conversation has not been sent yet."""
    known = {passage_key(passage) for passage in thread.passages}
    fresh = []
    for passage in passages:
        key = passage_key(passage)
        if key not in known:
            known.add(key)
            fresh.append(passage)
    return fresh


class ThreadStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def get(self, session_id: str) -> Thread | None:
        return self._load().get(session_id)

    def put(self, session_id: str, thread: Thread | None) -> None:
        """Keep the conversation's thread; None forgets it (the next turn starts over)."""
        threads = self._load()
        threads.pop(session_id, None)
        if thread is not None:
            threads[session_id] = thread  # newest last
        kept = dict(list(threads.items())[-MAX_THREADS:])
        payload = {key: value.model_dump(mode="json") for key, value in kept.items()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        scratch = self.path.with_suffix(".tmp")
        scratch.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        scratch.replace(self.path)

    def _load(self) -> dict[str, Thread]:
        if not self.path.exists():
            return {}
        try:
            raw: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Chat threads unreadable; follow-ups start over")
            return {}
        threads: dict[str, Thread] = {}
        for key, value in raw.items() if isinstance(raw, dict) else []:
            try:
                threads[key] = Thread.model_validate(value)
            except ValidationError:
                continue
        return threads
