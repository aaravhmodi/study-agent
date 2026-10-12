from zoneinfo import ZoneInfo

from app.schemas.extraction import AssessmentExtraction
from app.services.exam_schedule import (
    SCHEDULE_URL,
    FinalExam,
    apply_final_exam,
    parse_schedule,
)

TZ = "America/Toronto"
# Rows as the signed-in schedule page shows them (cells tab-separated, codes end in a
# no-break space).
PAGE = (
    "The fall 2026 Final Examination Schedule will be available on October 2, 2026.\n"
    "Exam\tSections\tDay\tDate\tStart\tFinish\tLocations\n"
    "ACTSC 611\xa0\t001\t\xa0\t\xa0\t\xa0\t\xa0\tSee instructor for exam details\n"
    "SYDE 212\xa0\t001\tMonday\tDecember 14, 2026\t12:30 PM\t3:00 PM\tTBA\n"
    "SYDE 252\xa0\t001\tWednesday\tDecember 16, 2026\t9:00 AM\t11:30 AM\tTBA\n"
    "SYDE 286\xa0\t001\tThursday\tDecember 10, 2026\t12:30 PM\t2:30 PM\tPAC 1-6\n"
    "SYDE 292\xa0\t001\tFriday\tDecember 18, 2026\t9:00 AM\t11:30 AM\tTBA\n"
    "SYDE 292\xa0\t002\tFriday\tDecember 18, 2026\t7:30 PM\t10:00 PM\tTBA\n"
)


def _local(exam: FinalExam) -> str:
    return exam.starts_at.astimezone(ZoneInfo(TZ)).strftime("%b %d %H:%M")


def test_each_courses_final_is_read_from_the_schedule() -> None:
    exams = parse_schedule(PAGE, TZ)

    assert {code: _local(exam) for code, exam in exams.items()} == {
        "SYDE 212": "Dec 14 12:30",
        "SYDE 252": "Dec 16 09:00",
        "SYDE 286": "Dec 10 12:30",
        "SYDE 292": "Dec 18 09:00",  # the first section listed
    }
    assert exams["SYDE 286"].location == "PAC 1-6"
    assert "ACTSC 611" not in exams  # "See instructor": no date to give


def test_the_outlines_undated_final_gets_the_date() -> None:
    exam = parse_schedule(PAGE, TZ)["SYDE 252"]
    outline = [
        AssessmentExtraction(title="Final exam", assessment_type="exam"),
        AssessmentExtraction(title="Midterm exam", assessment_type="exam"),
        AssessmentExtraction(title="Final Project Report - Group B", assessment_type="project"),
    ]

    result = apply_final_exam(outline, exam, TZ)

    assert [item.title for item in result] == [
        "Final exam",
        "Midterm exam",
        "Final Project Report - Group B",
    ]
    final = result[0]
    assert final.due_at == exam.starts_at
    assert str(final.source_url) == SCHEDULE_URL
    assert final.description == (
        "Final exam schedule: Wednesday, December 16, 9:00 AM to 11:30 AM, room TBA (sections 001)"
    )
    # Neither the midterm nor a final project is the final exam.
    assert result[1].due_at is None and result[2].due_at is None


def test_a_final_called_just_final_is_dated_and_one_is_added_when_missing() -> None:
    exam = parse_schedule(PAGE, TZ)["SYDE 292"]

    named_final = apply_final_exam(
        [AssessmentExtraction(title="Final", assessment_type="other")], exam, TZ
    )
    assert len(named_final) == 1 and named_final[0].due_at == exam.starts_at

    added = apply_final_exam([], exam, TZ)
    assert [(item.title, item.assessment_type) for item in added] == [("Final exam", "exam")]


def test_no_exam_listed_changes_nothing() -> None:
    outline = [AssessmentExtraction(title="Final exam", assessment_type="exam")]

    assert apply_final_exam(outline, None, TZ)[0].due_at is None
