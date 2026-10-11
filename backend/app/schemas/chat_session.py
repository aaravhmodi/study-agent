from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.chat import ChatResponse


class TurnImage(BaseModel):
    """A picture that came with a question: a thumbnail to show, and what it said."""

    model_config = ConfigDict(extra="forbid")

    thumbnail: str
    # The picture as read by the model, which is what later questions go on.
    text: str = ""


class ChatTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    course_code: str | None = None
    response: ChatResponse
    asked_at: datetime
    images: list[TurnImage] = Field(default_factory=list)


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
