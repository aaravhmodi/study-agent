from datetime import UTC, datetime, timedelta

from app.main import _assessment_status, _local

PAST = datetime.now(UTC) - timedelta(days=3)
FUTURE = datetime.now(UTC) + timedelta(days=3)


def test_past_due_work_is_overdue_until_marked_completed() -> None:
    assert _assessment_status(PAST, "UPCOMING") == "OVERDUE"
    assert _assessment_status(PAST, "COMPLETED") == "COMPLETED"


def test_future_and_undated_work_keep_their_status() -> None:
    assert _assessment_status(FUTURE, "UPCOMING") == "UPCOMING"
    assert _assessment_status(FUTURE, "COMPLETED") == "COMPLETED"
    assert _assessment_status(None, "UNKNOWN") == "UNKNOWN"
    # Naive datetimes from SQLite are treated as UTC.
    assert _assessment_status(PAST.replace(tzinfo=None), "UPCOMING") == "OVERDUE"


def test_a_due_time_is_given_as_the_clock_in_toronto_shows_it() -> None:
    # 11:59 PM in Toronto is the next day in UTC, four hours ahead in summer and five in winter.
    summer = datetime(2026, 10, 10, 3, 59, tzinfo=UTC)
    winter = datetime(2026, 11, 17, 4, 59, tzinfo=UTC)

    assert _local(summer, "America/Toronto") == "Fri 9 Oct 2026, 11:59 PM"
    assert _local(winter, "America/Toronto") == "Mon 16 Nov 2026, 11:59 PM"
    assert _local(winter.replace(tzinfo=None), "America/Toronto") == "Mon 16 Nov 2026, 11:59 PM"
    assert _local(datetime(2026, 12, 10, 17, 30, tzinfo=UTC), "America/Toronto") == (
        "Thu 10 Dec 2026, 12:30 PM"
    )
    assert _local(None, "America/Toronto") is None
