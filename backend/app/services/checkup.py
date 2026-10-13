"""A short test each day of what the student knows, so the day's plan fits the gap.

The check-up covers the courses with a test coming, nearest first. Each course gets a
question the student missed before (so it comes back) and new ones on what the test
covers, written by the tutor from the course files. Answers go to the practice log like
any other practice question, which is what the plan reads; this module only chooses the
questions and remembers which were today's.
"""

import json
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.schemas.chat import QuizFigure
from app.services.practice_log import PracticeItem, PracticeLog, question_id
from app.services.study_plan import TESTED, Knowledge, Work

logger = logging.getLogger(__name__)

CHECKUPS_FILE = "checkups.json"
KEEP_DAYS = 30
# A test this far off is worth checking up on.
LOOK_AHEAD = timedelta(days=21)
MOST_COURSES = 3
RECENT = timedelta(days=7)

# Writes new questions: (course, the work they prepare for, how many, the topics to lean
# on, questions not to repeat) -> the questions.
Writer = Callable[[str, Work | None, int, list[str], list[str]], list[QuizFigure]]


class CheckupQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    course: str
    quiz: QuizFigure
    # Filled in from the practice log when the check-up is read.
    answered: bool = False
    right: bool = False


class Checkup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The day it is for, in the student's time zone: "2026-10-13".
    day: str
    prepared_at: datetime
    questions: list[CheckupQuestion] = Field(default_factory=list)

    @property
    def answered(self) -> int:
        return sum(question.answered for question in self.questions)

    @property
    def right(self) -> int:
        return sum(question.right for question in self.questions)


class CheckupStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def get(self, day: str) -> Checkup | None:
        return self._load().get(day)

    def save(self, checkup: Checkup) -> None:
        checkups = self._load()
        checkups[checkup.day] = checkup
        kept = dict(sorted(checkups.items())[-KEEP_DAYS:])
        # Whether each was answered comes from the practice log, so it isn't kept here.
        unmarked = {"questions": {"__all__": {"answered", "right"}}}
        payload = {
            day: item.model_dump(mode="json", exclude=unmarked) for day, item in kept.items()
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        scratch = self.path.with_suffix(".tmp")
        scratch.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        scratch.replace(self.path)

    def _load(self) -> dict[str, Checkup]:
        if not self.path.exists():
            return {}
        try:
            raw: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Check-ups unreadable; starting fresh")
            return {}
        checkups: dict[str, Checkup] = {}
        for day, value in raw.items() if isinstance(raw, dict) else []:
            try:
                checkups[day] = Checkup.model_validate(value)
            except ValidationError:
                continue
        return checkups


def courses_to_test(
    work: list[Work], courses: list[str], now: datetime
) -> list[tuple[str, Work | None]]:
    """Up to three courses to check up on: the ones with a test coming, nearest first.

    With fewer tests than that coming, the remaining places go to the other courses in
    turn by the day, so every course is checked now and then.
    """

    chosen: list[tuple[str, Work | None]] = []
    upcoming = sorted(
        (item for item in work if item.kind in TESTED and now < item.due_at <= now + LOOK_AHEAD),
        key=lambda item: item.due_at,
    )
    for item in upcoming:
        if item.course not in {course for course, _ in chosen}:
            chosen.append((item.course, item))
    rest = sorted(course for course in courses if course not in {c for c, _ in chosen})
    if rest:
        start = now.toordinal() % len(rest)
        chosen += [(course, None) for course in rest[start:] + rest[:start]]
    return chosen[:MOST_COURSES]


def shares(total: int, courses: int) -> list[int]:
    """Questions per course: as even as it goes, the nearest test getting any extra."""
    if courses <= 0:
        return []
    each, extra = divmod(total, courses)
    return [each + (1 if index < extra else 0) for index in range(courses)]


def knowledge_by_course(items: list[PracticeItem], now: datetime) -> dict[str, Knowledge]:
    """What each course's answers of the last week show, by each question's latest answer."""
    recent: dict[str, list[PracticeItem]] = {}
    for item in items:
        if item.attempts and now - item.attempts[-1].at <= RECENT:
            recent.setdefault(item.course, []).append(item)
    knowledge = {}
    for course, answered in recent.items():
        missed: dict[str, int] = {}
        for item in answered:
            if not item.right:
                missed[item.topic] = missed.get(item.topic, 0) + 1
        knowledge[course] = Knowledge(
            asked=len(answered),
            right=sum(item.right for item in answered),
            weak_topics=sorted(missed, key=lambda topic: (-missed[topic], topic.lower())),
        )
    return knowledge


def question_request(
    course: str, work: Work | None, count: int, weak: list[str], seen: list[str]
) -> str:
    """What the tutor is asked for: a few quick questions on what the next test covers."""

    covers = (
        f"what {work.title} covers" if work is not None else "the most recent lectures and notes"
    )
    lines = [
        f"Daily check-up for {course}: write {count} multiple-choice "
        f"question{'' if count == 1 else 's'}, each with four options, on {covers}.",
        "Each tests one idea, can be answered in about a minute without a calculator, and "
        "is on a different topic from the others.",
    ]
    if weak:
        lines.append(f"Lean towards the topics I have been getting wrong: {'; '.join(weak)}.")
    if seen:
        lines.append("Do not repeat these, which I have already been asked:")
        lines += [f"- {' '.join(question.split())[:160]}" for question in seen]
    lines.append("Give only the quiz blocks: no introduction, no teaching and no summary.")
    return "\n".join(lines)


def prepare(
    day: str,
    now: datetime,
    targets: list[tuple[str, Work | None]],
    log: PracticeLog,
    write: Writer,
    total: int,
) -> Checkup:
    """Choose today's questions: one that is due again per course, the rest new."""

    items = log.items()
    knowledge = knowledge_by_course(items, now)
    questions: list[CheckupQuestion] = []
    for (course, work), share in zip(targets, shares(total, len(targets)), strict=True):
        if share <= 0:
            continue
        code = course.strip().upper()
        due = [item.quiz for item in log.due(code, now=now, limit=share)]
        again = due[:1] if share > 1 else []
        seen = [item.quiz.question for item in items if item.course == code][-12:]
        weak = knowledge[code].weak_topics[:3] if code in knowledge else []
        try:
            fresh = write(code, work, share - len(again), weak, seen)
        except RuntimeError as exc:
            # No key, no index for the course, or the model is down: fall back on review.
            logger.warning("Could not write check-up questions for %s (%s)", code, exc)
            fresh = []
        chosen = [*again, *fresh[: share - len(again)]]
        chosen += [quiz for quiz in due[1:] if quiz not in chosen][: share - len(chosen)]
        identities = {question.id for question in questions}
        for quiz in chosen:
            identity = question_id(code, quiz)
            if identity not in identities:
                identities.add(identity)
                questions.append(CheckupQuestion(id=identity, course=code, quiz=quiz))
    return Checkup(day=day, prepared_at=now, questions=questions)


def marked(checkup: Checkup, log: PracticeLog) -> Checkup:
    """The check-up with each question's answer since it was prepared, if any."""

    answers = {item.id: item for item in log.items()}
    questions = []
    for question in checkup.questions:
        item = answers.get(question.id)
        attempts = item.attempts if item else []
        # The first answer after it was set is the check-up's; later tries are practice.
        first = next((a for a in attempts if a.at >= checkup.prepared_at), None)
        questions.append(
            question.model_copy(
                update={"answered": first is not None, "right": bool(first and first.correct)}
            )
        )
    return checkup.model_copy(update={"questions": questions})
