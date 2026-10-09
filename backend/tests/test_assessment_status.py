from datetime import UTC, datetime, timedelta

from app.main import _assessment_status

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
