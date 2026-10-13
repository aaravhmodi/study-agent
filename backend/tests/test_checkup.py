from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.schemas.chat import QuizFigure
from app.services.checkup import (
    Checkup,
    CheckupStore,
    courses_to_test,
    knowledge_by_course,
    marked,
    prepare,
    question_request,
    shares,
)
from app.services.practice_log import PracticeLog
from app.services.study_plan import Work

NOW = datetime(2026, 10, 13, 11, 0, tzinfo=UTC)
COURSES = ["SYDE 212", "SYDE 252", "SYDE 262", "SYDE 286", "SYDE 292"]


def work(course: str, title: str, kind: str, days: float) -> Work:
    return Work(course=course, title=title, kind=kind, due_at=NOW + timedelta(days=days))


def quiz(question: str, topic: str = "Torsion") -> QuizFigure:
    return QuizFigure(question=question, choices=["A", "B", "C", "D"], correct=1, topic=topic)


def writer(calls: list[tuple[str, int]] | None = None):  # type: ignore[no-untyped-def]
    def write(course: str, item: Work | None, count: int, weak: list[str], seen: list[str]):  # type: ignore[no-untyped-def]
        if calls is not None:
            calls.append((course, count))
        return [quiz(f"{course} new question {n}") for n in range(1, count + 1)]

    return write


def test_the_courses_with_tests_coming_are_checked_nearest_first() -> None:
    upcoming = [
        work("SYDE 292", "Midterm", "test", 10.6),
        work("SYDE 286", "Midterm Test", "test", 8.6),
        work("SYDE 286", "Quiz 2", "quiz", 10),
        work("SYDE 252", "Assignment 3", "assignment", 3),  # not a test of knowledge
        work("SYDE 212", "Final exam", "exam", 62),  # too far off to check on yet
    ]

    chosen = courses_to_test(upcoming, COURSES, NOW)

    assert [(course, item.title if item else None) for course, item in chosen[:2]] == [
        ("SYDE 286", "Midterm Test"),
        ("SYDE 292", "Midterm"),
    ]
    # The third place goes round the other courses, a different one each day.
    third = {courses_to_test(upcoming, COURSES, NOW + timedelta(days=d))[2][0] for d in range(3)}
    assert third == {"SYDE 212", "SYDE 252", "SYDE 262"}


def test_questions_are_shared_out_evenly_with_the_nearest_test_getting_the_extra() -> None:
    assert shares(6, 3) == [2, 2, 2]
    assert shares(7, 3) == [3, 2, 2]
    assert shares(6, 1) == [6]
    assert shares(6, 0) == []


def test_each_course_gets_a_missed_question_back_and_the_rest_new(tmp_path: Path) -> None:
    log = PracticeLog(tmp_path / "practice.json")
    missed = quiz("What does J measure?")
    log.record("SYDE 286", missed, False, now=NOW - timedelta(days=1))
    calls: list[tuple[str, int]] = []
    targets = [("SYDE 286", work("SYDE 286", "Midterm Test", "test", 8.6)), ("SYDE 292", None)]

    checkup = prepare("2026-10-13", NOW, targets, log, writer(calls), total=6)

    assert [(q.course, q.quiz.question) for q in checkup.questions] == [
        ("SYDE 286", "What does J measure?"),
        ("SYDE 286", "SYDE 286 new question 1"),
        ("SYDE 286", "SYDE 286 new question 2"),
        ("SYDE 292", "SYDE 292 new question 1"),
        ("SYDE 292", "SYDE 292 new question 2"),
        ("SYDE 292", "SYDE 292 new question 3"),
    ]
    # Only the new ones are asked of the tutor.
    assert calls == [("SYDE 286", 2), ("SYDE 292", 3)]


def test_when_new_questions_cant_be_written_the_due_ones_fill_in(tmp_path: Path) -> None:
    log = PracticeLog(tmp_path / "practice.json")
    for n in range(3):
        log.record("SYDE 286", quiz(f"Old question {n}"), False, now=NOW - timedelta(days=1))

    def broken(course: str, item: Work | None, count: int, weak: list[str], seen: list[str]):  # type: ignore[no-untyped-def]
        raise RuntimeError("No vector store found.")

    checkup = prepare("2026-10-13", NOW, [("SYDE 286", None)], log, broken, total=3)

    assert sorted(q.quiz.question for q in checkup.questions) == [
        "Old question 0",
        "Old question 1",
        "Old question 2",
    ]


def test_the_first_answer_after_it_was_set_is_the_check_ups(tmp_path: Path) -> None:
    log = PracticeLog(tmp_path / "practice.json")
    checkup = prepare("2026-10-13", NOW, [("SYDE 286", None)], log, writer(), total=3)
    first, second, _third = (q.quiz for q in checkup.questions)

    assert (marked(checkup, log).answered, marked(checkup, log).right) == (0, 0)

    log.record("SYDE 286", first, True, now=NOW + timedelta(minutes=5))
    log.record("SYDE 286", second, False, now=NOW + timedelta(minutes=6))
    # Trying a missed one again is practice; the check-up keeps the first answer.
    log.record("SYDE 286", second, True, now=NOW + timedelta(minutes=9))

    result = marked(checkup, log)
    assert [(q.answered, q.right) for q in result.questions] == [
        (True, True),
        (True, False),
        (False, False),
    ]
    assert (result.answered, result.right) == (2, 1)


def test_knowledge_is_the_latest_answer_to_each_question_this_week(tmp_path: Path) -> None:
    log = PracticeLog(tmp_path / "practice.json")
    log.record("SYDE 286", quiz("a", "Torsion"), False, now=NOW - timedelta(days=2))
    log.record("SYDE 286", quiz("b", "Torsion"), False, now=NOW - timedelta(days=2))
    log.record("SYDE 286", quiz("c", "Shear"), False, now=NOW - timedelta(days=2))
    log.record("SYDE 286", quiz("c", "Shear"), True, now=NOW - timedelta(days=1))
    log.record("SYDE 286", quiz("d", "Strain"), True, now=NOW - timedelta(days=1))
    log.record("SYDE 286", quiz("old", "Stress"), False, now=NOW - timedelta(days=9))

    knowledge = knowledge_by_course(log.items(), NOW)["SYDE 286"]

    # Four questions this week, two right at the last try; last week's doesn't count.
    assert (knowledge.asked, knowledge.right, knowledge.weak_topics) == (4, 2, ["Torsion"])


def test_the_tutor_is_asked_for_quick_questions_on_what_the_test_covers() -> None:
    request = question_request(
        "SYDE 286",
        work("SYDE 286", "Midterm Test", "test", 8.6),
        2,
        ["Torsion", "Shear"],
        ["What does  J measure?"],
    )

    assert request.splitlines() == [
        "Daily check-up for SYDE 286: write 2 multiple-choice questions, each with four "
        "options, on what Midterm Test covers.",
        "Each tests one idea, can be answered in about a minute without a calculator, and "
        "is on a different topic from the others.",
        "Lean towards the topics I have been getting wrong: Torsion; Shear.",
        "Do not repeat these, which I have already been asked:",
        "- What does J measure?",
        "Give only the quiz blocks: no introduction, no teaching and no summary.",
    ]
    assert "the most recent lectures and notes" in question_request("SYDE 212", None, 1, [], [])


def test_a_days_check_up_is_kept_without_its_marks(tmp_path: Path) -> None:
    store = CheckupStore(tmp_path / "checkups.json")
    checkup = Checkup(day="2026-10-13", prepared_at=NOW, questions=[])
    log = PracticeLog(tmp_path / "practice.json")
    full = prepare("2026-10-13", NOW, [("SYDE 286", None)], log, writer(), total=2)

    store.save(full)

    assert store.get("2026-10-12") is None
    kept = store.get("2026-10-13")
    assert kept is not None and [q.quiz.question for q in kept.questions] == [
        "SYDE 286 new question 1",
        "SYDE 286 new question 2",
    ]
    assert '"answered"' not in (tmp_path / "checkups.json").read_text()
    assert checkup.answered == 0
