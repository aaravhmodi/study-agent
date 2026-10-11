"""What the student has practised and how it went, so missed questions come back.

The two study techniques with the strongest evidence are practice testing and spacing;
together they are called successive relearning: answer a question until you get it
right, then again after a gap, with the gap growing each time. So every practice
question answered on the page is kept here with its attempts. One answered wrong is
due again at once. One answered right waits a day, then two, four and seven.

The log is one local JSON file. Scores are counted by each question's latest attempt,
which is what the student knows now rather than what they once got wrong.
"""

import hashlib
import json
import logging
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.schemas.chat import QuizFigure

logger = logging.getLogger(__name__)

PRACTICE_FILE = "practice.json"
# Days until a question is due again, by how many times running it was answered right.
INTERVAL_DAYS = (0, 1, 2, 4, 7)
MAX_ITEMS = 3000
MAX_ATTEMPTS = 20
NO_TOPIC = "Other"
# Answers arrive together when a set is checked quickly; each must read the log the
# one before it wrote.
_WRITING = threading.Lock()


class Attempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at: datetime
    correct: bool


class PracticeItem(BaseModel):
    """One practice question and every time it was answered."""

    model_config = ConfigDict(extra="forbid")

    id: str
    # The course it was asked under; empty when no course was chosen.
    course: str = ""
    quiz: QuizFigure
    attempts: list[Attempt] = Field(default_factory=list)
    # How many times running it has been answered right (capped): its place in the spacing.
    streak: int = 0
    due_at: datetime

    @property
    def topic(self) -> str:
        return self.quiz.topic or NO_TOPIC

    @property
    def right(self) -> bool:
        return bool(self.attempts) and self.attempts[-1].correct


class TopicScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    questions: int
    right: int


class CourseScore(BaseModel):
    """How one course's practice stands now."""

    model_config = ConfigDict(extra="forbid")

    course: str
    questions: int
    # Questions whose latest answer was right.
    right: int
    # Questions due for another go now.
    due: int
    # Weakest first: the topics to work on.
    topics: list[TopicScore] = Field(default_factory=list)


def question_id(course: str, quiz: QuizFigure) -> str:
    """The same question asked again under the same course is the same item."""

    text = " ".join(quiz.question.split()).lower()
    options = "|".join(" ".join(option.split()).lower() for option in quiz.choices)
    key = f"{course.strip().upper()}\n{text}\n{options}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


class PracticeLog:
    def __init__(self, path: Path) -> None:
        self.path = path

    def record(
        self, course: str | None, quiz: QuizFigure, correct: bool, *, now: datetime | None = None
    ) -> PracticeItem:
        """Add an attempt at a question and set when it is due again."""

        moment = now or datetime.now(UTC)
        code = (course or "").strip().upper()
        identity = question_id(code, quiz)
        with _WRITING:
            items = self._load()
            item = items.get(identity) or PracticeItem(
                id=identity, course=code, quiz=quiz, due_at=moment
            )
            item.quiz = quiz
            item.attempts = [*item.attempts, Attempt(at=moment, correct=correct)][-MAX_ATTEMPTS:]
            item.streak = min(item.streak + 1, len(INTERVAL_DAYS) - 1) if correct else 0
            item.due_at = moment + timedelta(days=INTERVAL_DAYS[item.streak])
            items[identity] = item
            self._save(items)
        return item

    def due(
        self, course: str | None = None, *, now: datetime | None = None, limit: int = 20
    ) -> list[PracticeItem]:
        """Questions to answer again now: those last answered wrong first, then the most
        overdue."""

        moment = now or datetime.now(UTC)
        code = (course or "").strip().upper()
        waiting = [
            item
            for item in self._load().values()
            if item.due_at <= moment and (not code or item.course == code)
        ]
        waiting.sort(key=lambda item: (item.right, item.due_at))
        return waiting[:limit]

    def scores(self, *, now: datetime | None = None) -> list[CourseScore]:
        """Each course's standing, the course with the most due first."""

        moment = now or datetime.now(UTC)
        by_course: dict[str, list[PracticeItem]] = {}
        for item in self._load().values():
            by_course.setdefault(item.course, []).append(item)
        scores = []
        for course, items in by_course.items():
            by_topic: dict[str, list[PracticeItem]] = {}
            for item in items:
                by_topic.setdefault(item.topic, []).append(item)
            topics = [
                TopicScore(topic=topic, questions=len(group), right=sum(i.right for i in group))
                for topic, group in by_topic.items()
            ]
            # Weakest first; among equals, the topic with more evidence.
            topics.sort(key=lambda t: (t.right / t.questions, -t.questions, t.topic.lower()))
            scores.append(
                CourseScore(
                    course=course,
                    questions=len(items),
                    right=sum(item.right for item in items),
                    due=sum(item.due_at <= moment for item in items),
                    topics=topics,
                )
            )
        scores.sort(key=lambda score: (-score.due, score.course))
        return scores

    def _load(self) -> dict[str, PracticeItem]:
        if not self.path.exists():
            return {}
        try:
            raw: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Practice log unreadable; starting fresh")
            return {}
        items: dict[str, PracticeItem] = {}
        for value in raw.values() if isinstance(raw, dict) else []:
            try:
                item = PracticeItem.model_validate(value)
            except ValidationError:
                continue
            items[item.id] = item
        return items

    def _save(self, items: dict[str, PracticeItem]) -> None:
        # The questions answered longest ago are the first to go when the log is full.
        newest = sorted(items.values(), key=lambda item: item.attempts[-1].at, reverse=True)
        payload = {item.id: item.model_dump(mode="json") for item in newest[:MAX_ITEMS]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Written whole to a second file first, so a crash cannot leave half a log.
        scratch = self.path.with_suffix(".tmp")
        scratch.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        scratch.replace(self.path)
