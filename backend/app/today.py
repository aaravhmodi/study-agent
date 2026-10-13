"""Today's check-up and study plan, for the page's Today screen and the morning push.

GET  /practice/checkup   today's questions and which are answered
POST /practice/checkup   prepare today's check-up if it isn't there yet (n8n, each morning)
GET  /practice/plan      how long to spend on what today
"""

import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.config import Settings, get_settings
from app.db.database import SessionLocal, ensure_schema
from app.models import Assessment, Course
from app.schemas.chat import QuizFigure
from app.services.checkup import (
    CHECKUPS_FILE,
    CheckupQuestion,
    CheckupStore,
    Writer,
    courses_to_test,
    knowledge_by_course,
    marked,
    prepare,
    question_request,
)
from app.services.practice_log import PRACTICE_FILE, PracticeLog
from app.services.rag import RagService
from app.services.study_plan import StudyPlan, Work, make_plan

# Some outlines file a final report or project under exams; it is work to hand in, not
# something to be tested on.
_HANDED_IN = re.compile(r"report|project|presentation", re.IGNORECASE)


class CheckupView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: str
    # False until today's questions have been prepared.
    prepared: bool = False
    questions: list[CheckupQuestion] = Field(default_factory=list)
    answered: int = 0
    right: int = 0


def _today(settings: Settings) -> str:
    return datetime.now(ZoneInfo(settings.timezone)).date().isoformat()


def _log(settings: Settings) -> PracticeLog:
    return PracticeLog(settings.data_dir / PRACTICE_FILE)


def _store(settings: Settings) -> CheckupStore:
    return CheckupStore(settings.data_dir / CHECKUPS_FILE)


def upcoming_work(now: datetime) -> tuple[list[Work], list[str]]:
    """Graded work still to come and not marked done, and the courses being taken."""

    ensure_schema()
    with SessionLocal() as session:
        courses = session.scalars(select(Course).where(Course.active.is_(True))).all()
        rows = session.execute(
            select(Assessment, Course)
            .join(Course, Assessment.course_id == Course.id)
            .where(Course.active.is_(True), Assessment.due_at.is_not(None))
        ).all()
        work = []
        for assessment, course in rows:
            due_at = assessment.due_at
            if due_at is None or assessment.status == "COMPLETED":
                continue
            due_at = due_at if due_at.tzinfo else due_at.replace(tzinfo=UTC)
            if due_at <= now:
                continue
            kind = assessment.assessment_type
            if kind == "exam" and _HANDED_IN.search(assessment.title):
                kind = "project"
            work.append(
                Work(
                    course=(course.code or course.name).upper(),
                    title=assessment.title,
                    kind=kind,
                    due_at=due_at,
                )
            )
        return work, sorted((course.code or course.name).upper() for course in courses)


def tutor_writer(settings: Settings) -> Writer:
    """New questions from the tutor, written from the course's own files."""

    # A check-up is about the course; a web search per question would only add cost.
    tutor = RagService(settings.model_copy(update={"rag_web_search": False}))

    def write(
        course: str, work: Work | None, count: int, weak: list[str], seen: list[str]
    ) -> list[QuizFigure]:
        request = question_request(course, work, count, weak, seen)
        answer = tutor.ask(request, course, fresh=True, depth="quick")
        return [
            figure
            for figure in answer.figures
            if isinstance(figure, QuizFigure) and (figure.choices or figure.number is not None)
        ]

    return write


def _view(settings: Settings) -> CheckupView:
    day = _today(settings)
    checkup = _store(settings).get(day)
    if checkup is None:
        return CheckupView(day=day)
    done = marked(checkup, _log(settings))
    return CheckupView(
        day=day, prepared=True, questions=done.questions, answered=done.answered, right=done.right
    )


def todays_checkup() -> CheckupView:
    return _view(get_settings())


def prepare_checkup() -> CheckupView:
    """Prepare today's check-up. Asking again the same day returns the one already made."""

    settings = get_settings()
    day = _today(settings)
    store = _store(settings)
    if store.get(day) is None:
        now = datetime.now(UTC)
        work, courses = upcoming_work(now)
        try:
            write = tutor_writer(settings)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        checkup = prepare(
            day,
            now,
            courses_to_test(work, courses, now),
            _log(settings),
            write,
            settings.checkup_questions,
        )
        if not checkup.questions:
            raise HTTPException(
                status_code=503,
                detail="No check-up questions could be written. Sync and index the courses first.",
            )
        store.save(checkup)
    return _view(settings)


def todays_plan() -> StudyPlan:
    """How long to spend on what today, from the deadlines and the last week's answers."""

    settings = get_settings()
    now = datetime.now(UTC)
    work, _courses = upcoming_work(now)
    log = _log(settings)
    items = log.items()
    return make_plan(
        work,
        knowledge_by_course(items, now),
        sum(item.due_at <= now for item in items),
        now,
        settings.study_minutes_per_day,
    )


def register(app: FastAPI) -> None:
    """Add the Today routes to the app."""

    app.add_api_route("/practice/checkup", todays_checkup, methods=["GET"])
    app.add_api_route("/practice/checkup", prepare_checkup, methods=["POST"])
    app.add_api_route("/practice/plan", todays_plan, methods=["GET"])
