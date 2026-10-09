"""Keep each conversation with the tutor so follow-ups have context and chats can be reopened.

Sessions live in one local JSON file. The newest sessions and turns are kept; older
ones are dropped so the file stays small.
"""

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.schemas.chat import ChatResponse
from app.schemas.chat_session import ChatSession, ChatSessionSummary, ChatTurn

logger = logging.getLogger(__name__)

SESSIONS_FILE = "chat_sessions.json"
MAX_SESSIONS = 100
MAX_TURNS = 60
TITLE_CHARS = 80


class ChatSessionStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def create(
        self, first_question: str, course_code: str | None, *, now: datetime | None = None
    ) -> ChatSession:
        moment = now or datetime.now(UTC)
        title = " ".join(first_question.split())
        session = ChatSession(
            id=uuid.uuid4().hex,
            title=title if len(title) <= TITLE_CHARS else title[: TITLE_CHARS - 1] + "…",
            course_code=course_code,
            created_at=moment,
            updated_at=moment,
        )
        sessions = self._load()
        sessions[session.id] = session
        self._save(sessions)
        return session

    def get(self, session_id: str) -> ChatSession | None:
        return self._load().get(session_id)

    def add_turn(
        self,
        session_id: str,
        question: str,
        course_code: str | None,
        response: ChatResponse,
        *,
        now: datetime | None = None,
    ) -> ChatSession:
        sessions = self._load()
        session = sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        moment = now or datetime.now(UTC)
        turn = ChatTurn(
            question=question, course_code=course_code, response=response, asked_at=moment
        )
        session.turns = [*session.turns, turn][-MAX_TURNS:]
        session.updated_at = moment
        if course_code:
            session.course_code = course_code
        self._save(sessions)
        return session

    def list(self, limit: int = 30) -> list[ChatSessionSummary]:
        newest = sorted(self._load().values(), key=lambda item: item.updated_at, reverse=True)
        return [
            ChatSessionSummary(
                id=session.id,
                title=session.title,
                course_code=session.course_code,
                updated_at=session.updated_at,
                turns=len(session.turns),
            )
            for session in newest[:limit]
        ]

    def delete(self, session_id: str) -> bool:
        sessions = self._load()
        removed = sessions.pop(session_id, None) is not None
        if removed:
            self._save(sessions)
        return removed

    def _load(self) -> dict[str, ChatSession]:
        if not self.path.exists():
            return {}
        try:
            raw: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Chat sessions file unreadable; starting fresh")
            return {}
        sessions: dict[str, ChatSession] = {}
        for value in raw.values() if isinstance(raw, dict) else []:
            try:
                session = ChatSession.model_validate(value)
            except ValidationError:
                continue
            sessions[session.id] = session
        return sessions

    def _save(self, sessions: dict[str, ChatSession]) -> None:
        newest = sorted(sessions.values(), key=lambda item: item.updated_at, reverse=True)
        payload = {item.id: item.model_dump(mode="json") for item in newest[:MAX_SESSIONS]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
