from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.chat import ChatResponse


class ChatTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    course_code: str | None = None
    response: ChatResponse
    asked_at: datetime


class ChatSession(BaseModel):
    """One conversation: a first question and its follow-ups."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    course_code: str | None = None
    created_at: datetime
    updated_at: datetime
    turns: list[ChatTurn] = Field(default_factory=list)


class ChatSessionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    course_code: str | None = None
    updated_at: datetime
    turns: int
