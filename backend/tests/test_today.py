from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app import main, today
from app.config import Settings
from app.db.database import Base
from app.models import Assessment, Course
from app.schemas.chat import QuizFigure
from app.services.checkup import CheckupStore
from app.services.practice_log import PracticeLog
from app.services.study_plan import Work
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions: sessionmaker[Session] = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(UTC)
    with sessions() as session:
        course = Course(name="SYDE 286 - Fall 2026", code="SYDE 286", url="https://learn/286")
        session.add(course)
        session.flush()

        def assessment(title: str, kind: str, days: float, status: str = "UPCOMING") -> Assessment:
            return Assessment(
                course_id=course.id,
                title=title,
                assessment_type=kind,
                due_at=now + timedelta(days=days),
                status=status,
                first_seen_at=now,
                last_seen_at=now,
            )

        session.add_all(
            [
                assessment("Midterm Test", "test", 8.5),
                assessment("Assignment 1", "assignment", 2.5, status="COMPLETED"),
                assessment("Final Project Report", "exam", 9.5),
                assessment("Quiz 1", "quiz", -3),
            ]
        )
        session.commit()

    written: list[tuple[str, int]] = []

    def writer(settings: Settings):  # type: ignore[no-untyped-def]
        def write(course: str, work: Work | None, count: int, weak: list[str], seen: list[str]):  # type: ignore[no-untyped-def]
            written.append((course, count))
            return [
                QuizFigure(question=f"{course} question {n}", choices=["A", "B"], correct=0)
                for n in range(count)
            ]

        return write

    log = PracticeLog(tmp_path / "practice.json")
    monkeypatch.setattr(today, "SessionLocal", sessions)
    monkeypatch.setattr(today, "ensure_schema", lambda: None)
    monkeypatch.setattr(today, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(today, "_log", lambda settings: log)
    monkeypatch.setattr(today, "_store", lambda settings: CheckupStore(tmp_path / "checkups.json"))
    monkeypatch.setattr(today, "tutor_writer", writer)
    monkeypatch.setattr(main, "_practice_log", lambda: log)
    monkeypatch.setattr(main, "get_settings", lambda: Settings(_env_file=None))
    test_client = TestClient(main.app)
    test_client.written = written  # type: ignore[attr-defined]
    return test_client


def test_the_plan_covers_work_to_come_that_isnt_done(client: TestClient) -> None:
    plan = client.get("/practice/plan").json()

    # Not the assignment marked done or the quiz already past; the "exam" that is a
    # report is planned as a project, not something practice results change.
    assert [(b["title"], b["kind"], b["minutes"]) for b in plan["blocks"]] == [
        ("Midterm Test", "test", 60),
        ("Final Project Report", "project", 50),
    ]
    assert plan["limit_minutes"] == 180 and plan["minutes"] == 110


def test_todays_check_up_is_prepared_once_and_marked_as_it_is_answered(
    client: TestClient,
) -> None:
    assert client.get("/practice/checkup").json()["prepared"] is False

    made = client.post("/practice/checkup").json()
    assert made["prepared"] is True and len(made["questions"]) == 6
    assert (made["answered"], made["right"]) == (0, 0)
    # Preparing again the same day costs nothing and changes nothing.
    again = client.post("/practice/checkup").json()
    assert [q["id"] for q in again["questions"]] == [q["id"] for q in made["questions"]]
    assert client.written == [("SYDE 286", 6)]  # type: ignore[attr-defined]

    for question, correct in zip(
        made["questions"][:5], [True, False, False, False, False], strict=True
    ):
        answer = {"course_code": question["course"], "quiz": question["quiz"], "correct": correct}
        assert client.post("/practice/answers", json=answer).status_code == 200

    marked = client.get("/practice/checkup").json()
    assert (marked["answered"], marked["right"]) == (5, 1)
    assert [q["answered"] for q in marked["questions"]] == [True] * 5 + [False]

    # One of five right: the midterm gets more of today.
    midterm = client.get("/practice/plan").json()["blocks"][0]
    assert midterm["minutes"] == 80
    assert midterm["reason"].endswith("1 of 5 right in practice this week, so more time.")
    # The four missed are due again at once.
    assert client.get("/practice/plan").json()["review_due"] == 4
