from datetime import UTC, datetime, timedelta

from app.services.study_plan import Knowledge, Work, make_plan

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def work(course: str, title: str, kind: str, days: float) -> Work:
    return Work(course=course, title=title, kind=kind, due_at=NOW + timedelta(days=days))


def minutes(plan_work: list[Work], knowledge: dict[str, Knowledge] | None = None) -> dict[str, int]:
    plan = make_plan(plan_work, knowledge or {}, 0, NOW, limit_minutes=600)
    return {block.title: block.minutes for block in plan.blocks}


def test_a_test_is_prepared_for_over_the_ten_days_before_it() -> None:
    midterm = work("SYDE 286", "Midterm Test", "test", 8.5)

    plan = make_plan([midterm], {}, 0, NOW, limit_minutes=600)

    # Ten hours over ten days is an hour a day.
    (block,) = plan.blocks
    assert (block.minutes, block.days_left) == (60, 9)
    assert block.reason == (
        "Midterm Test is in 9 days. No practice results yet, so the usual time; "
        "a check-up adjusts it."
    )
    # Further off than that, it isn't on today's plan yet.
    assert minutes([work("SYDE 292", "Midterm", "test", 11)]) == {}


def test_what_practice_shows_changes_how_long_a_test_gets() -> None:
    midterm = [work("SYDE 286", "Midterm Test", "test", 8.5)]
    strong = {"SYDE 286": Knowledge(asked=10, right=9)}
    weak = {"SYDE 286": Knowledge(asked=10, right=2, weak_topics=["Torsion", "Shear", "Strain"])}

    assert minutes(midterm, strong) == {"Midterm Test": 35}
    assert minutes(midterm, weak) == {"Midterm Test": 80}

    block = make_plan(midterm, weak, 0, NOW, limit_minutes=600).blocks[0]
    assert block.reason == (
        "Midterm Test is in 9 days. 2 of 10 right in practice this week, so more time."
    )
    assert block.topics == ["Torsion", "Shear", "Strain"]


def test_two_answers_are_too_few_to_change_anything() -> None:
    midterm = [work("SYDE 286", "Midterm Test", "test", 8.5)]

    assert minutes(midterm, {"SYDE 286": Knowledge(asked=2, right=0)}) == {"Midterm Test": 60}


def test_an_assignment_gets_its_time_whatever_practice_says() -> None:
    assignment = [work("SYDE 252", "Assignment 3", "assignment", 3.2)]

    plan = make_plan(assignment, {"SYDE 252": Knowledge(asked=10, right=0)}, 0, NOW, 600)

    # Four hours over five days.
    assert [(b.minutes, b.reason) for b in plan.blocks] == [(50, "Assignment 3 is due in 4 days.")]


def test_the_last_two_days_get_more() -> None:
    assert minutes([work("SYDE 262", "Quiz 2", "quiz", 2.5)]) == {"Quiz 2": 40}
    assert minutes([work("SYDE 262", "Quiz 2", "quiz", 1.5)]) == {"Quiz 2": 60}
    tomorrow = make_plan([work("SYDE 262", "Quiz 2", "quiz", 0.5)], {}, 0, NOW, 600).blocks[0]
    assert tomorrow.minutes == 60 and tomorrow.reason.startswith("Quiz 2 is tomorrow.")


def test_past_work_is_left_out_and_the_soonest_comes_first() -> None:
    plan = make_plan(
        [
            work("SYDE 292", "Midterm", "test", 9.5),
            work("SYDE 252", "Assignment 2", "assignment", -3),
            work("SYDE 262", "Quiz 2", "quiz", 2.5),
        ],
        {},
        0,
        NOW,
        600,
    )

    assert [block.title for block in plan.blocks] == ["Quiz 2", "Midterm"]


def test_a_day_over_the_limit_is_scaled_down_together() -> None:
    busy = [
        work("SYDE 286", "Midterm Test", "test", 1.5),
        work("SYDE 292", "Midterm", "test", 1.5),
        work("SYDE 252", "Phase 1", "project", 1.5),
    ]

    plan = make_plan(busy, {}, 12, NOW, limit_minutes=180)

    # 90 + 90 + 70 for the work and 20 to review 12 questions is 270 minutes.
    assert plan.wanted_minutes == 270 and plan.limit_minutes == 180
    assert [block.minutes for block in plan.blocks] == [60, 60, 45]
    assert (plan.review_due, plan.review_minutes, plan.minutes) == (12, 15, 180)


def test_due_practice_questions_are_on_the_plan_even_on_a_free_day() -> None:
    plan = make_plan([], {}, 3, NOW, limit_minutes=180)

    assert (plan.blocks, plan.review_minutes, plan.minutes) == ([], 5, 5)
    assert make_plan([], {}, 0, NOW, limit_minutes=180).minutes == 0
