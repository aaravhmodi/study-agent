from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app import main
from app.config import Settings
from app.schemas.chat import QuizFigure
from app.services.practice import parse_quiz
from app.services.practice_log import (
    INTERVAL_DAYS,
    NO_TOPIC,
    PracticeLog,
    question_id,
)
from fastapi.testclient import TestClient

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
DAY = timedelta(days=1)


def _quiz(question: str, topic: str = "Bayes' theorem") -> QuizFigure:
    return QuizFigure(question=question, answer="0.6", number=0.6, topic=topic)


def test_a_topic_line_names_what_a_question_tests() -> None:
    quiz = parse_quiz(
        "Topic: **Bayes' theorem**\nQ: Given a late flight, how likely is it Caribou?\n"
        "A) 0.35\nB) 0.49\nAnswer: B\nWhy: 0.143 / 0.29."
    )

    assert quiz.topic == "Bayes' theorem"
    # The topic is not part of the question the student reads.
    assert quiz.question == "Given a late flight, how likely is it Caribou?"
    assert parse_quiz("Q: 1 + 1?\nAnswer: 2").topic == ""


def test_a_missed_question_is_due_at_once_and_a_right_one_waits_longer_each_time(
    tmp_path: Path,
) -> None:
    log = PracticeLog(tmp_path / "practice.json")
    quiz = _quiz("P(A|B)?")

    missed = log.record("syde 212", quiz, correct=False, now=NOW)
    assert (missed.course, missed.streak, missed.due_at) == ("SYDE 212", 0, NOW)

    gaps = []
    moment = NOW
    for _ in range(len(INTERVAL_DAYS) + 1):
        item = log.record("SYDE 212", quiz, correct=True, now=moment)
        gaps.append((item.due_at - moment).days)
        moment = item.due_at
    # A day, then two, four, and a week; it stays at a week from there.
    assert gaps == [1, 2, 4, 7, 7, 7]

    # Getting it wrong again starts the spacing over.
    again = log.record("SYDE 212", quiz, correct=False, now=moment)
    assert (again.streak, again.due_at) == (0, moment)
    assert len(again.attempts) == len(gaps) + 2


def test_the_same_question_is_one_item_however_it_is_spaced_or_cased(tmp_path: Path) -> None:
    log = PracticeLog(tmp_path / "practice.json")
    log.record("SYDE 212", _quiz("What is  P(A|B)?"), correct=False, now=NOW)
    log.record("syde 212", _quiz("what is p(a|b)?"), correct=True, now=NOW)

    (score,) = log.scores(now=NOW)
    assert (score.questions, score.right) == (1, 1)
    # The same words under another course are that course's own question.
    assert question_id("SYDE 212", _quiz("x")) != question_id("SYDE 286", _quiz("x"))


def test_due_questions_come_wrong_first_then_longest_overdue(tmp_path: Path) -> None:
    log = PracticeLog(tmp_path / "practice.json")
    log.record("SYDE 212", _quiz("right long ago"), correct=True, now=NOW - 5 * DAY)
    log.record("SYDE 212", _quiz("right yesterday"), correct=True, now=NOW - DAY)
    log.record("SYDE 212", _quiz("wrong just now"), correct=False, now=NOW)
    log.record("SYDE 212", _quiz("right just now"), correct=True, now=NOW)
    log.record("SYDE 286", _quiz("another course"), correct=False, now=NOW)

    due = [item.quiz.question for item in log.due("SYDE 212", now=NOW)]
    assert due == ["wrong just now", "right long ago", "right yesterday"]
    assert len(log.due(now=NOW)) == 4
    assert [item.quiz.question for item in log.due("SYDE 212", now=NOW, limit=1)] == [
        "wrong just now"
    ]


def test_scores_count_what_is_known_now_and_put_the_weakest_topic_first(tmp_path: Path) -> None:
    log = PracticeLog(tmp_path / "practice.json")
    # Wrong at first, right since: known now.
    log.record("SYDE 212", _quiz("b1", "Bayes"), correct=False, now=NOW - DAY)
    log.record("SYDE 212", _quiz("b1", "Bayes"), correct=True, now=NOW)
    log.record("SYDE 212", _quiz("b2", "Bayes"), correct=True, now=NOW)
    log.record("SYDE 212", _quiz("c1", "Counting"), correct=False, now=NOW)
    log.record("SYDE 212", _quiz("c2", "Counting"), correct=False, now=NOW)
    log.record("SYDE 212", _quiz("c3", "Counting"), correct=True, now=NOW)
    log.record("SYDE 212", _quiz("u1", ""), correct=True, now=NOW)
    log.record("SYDE 286", _quiz("s1", "Stress"), correct=False, now=NOW)
    log.record("SYDE 286", _quiz("s2", "Stress"), correct=False, now=NOW)
    log.record("SYDE 286", _quiz("s3", "Stress"), correct=False, now=NOW)

    stress, stats = log.scores(now=NOW)

    # The course with the most to do now is first.
    assert (stress.course, stress.questions, stress.right, stress.due) == ("SYDE 286", 3, 0, 3)
    assert (stats.course, stats.questions, stats.right, stats.due) == ("SYDE 212", 6, 4, 2)
    assert [(t.topic, t.questions, t.right) for t in stats.topics] == [
        ("Counting", 3, 1),
        ("Bayes", 2, 2),
        (NO_TOPIC, 1, 1),
    ]


def test_a_damaged_log_reads_as_empty_and_is_replaced_whole(tmp_path: Path) -> None:
    path = tmp_path / "practice.json"
    path.write_text("{not json", encoding="utf-8")
    log = PracticeLog(path)

    assert log.scores(now=NOW) == [] and log.due(now=NOW) == []
    log.record(None, _quiz("no course chosen"), correct=True, now=NOW)

    (score,) = PracticeLog(path).scores(now=NOW)
    assert (score.course, score.questions) == ("", 1)
    assert not path.with_suffix(".tmp").exists()


def test_the_page_reports_answers_and_asks_what_is_due(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(main, "_practice_log", lambda: PracticeLog(tmp_path / "practice.json"))
    client = TestClient(main.app)
    quiz = _quiz("P(A|B)?").model_dump()

    kept = client.post(
        "/practice/answers", json={"course_code": "SYDE 212", "quiz": quiz, "correct": False}
    )
    assert kept.status_code == 200
    assert (kept.json()["attempts"], kept.json()["right"]) == (1, False)

    (due,) = client.get("/practice/due", params={"course": "SYDE 212"}).json()
    assert due["quiz"]["question"] == "P(A|B)?" and due["id"] == kept.json()["id"]
    assert client.get("/practice/due", params={"course": "SYDE 286"}).json() == []

    (score,) = client.get("/practice").json()
    assert (score["course"], score["questions"], score["right"], score["due"]) == (
        "SYDE 212",
        1,
        0,
        1,
    )
    assert score["topics"] == [{"topic": "Bayes' theorem", "questions": 1, "right": 0}]

    # What is not a question is refused, not stored.
    refused = client.post("/practice/answers", json={"quiz": {"kind": "quiz"}, "correct": True})
    assert refused.status_code == 422
