from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.chat import QuizFigure


class PracticeAnswer(BaseModel):
    """One practice question the student has just answered on the page."""

    model_config = ConfigDict(extra="forbid")

    course_code: str | None = Field(default=None, max_length=100)
    quiz: QuizFigure
    correct: bool


class PracticeQuestion(BaseModel):
    """A question due for another go."""

    model_config = ConfigDict(extra="forbid")

    id: str
    course: str
    quiz: QuizFigure
    attempts: int
    # Whether the latest answer was right.
    right: bool
    due_at: datetime
