from datetime import UTC

import pytest
from app.agents.course_agent import CourseAgent, _assessment_type, _parse_due_at
from app.browser.client import MockBrowserClient
from app.config import get_settings


@pytest.mark.asyncio
async def test_discover_courses_from_semantic_links() -> None:
    browser = MockBrowserClient(
        {
            "url": "https://learn.uwaterloo.ca/d2l/home",
            "title": "Homepage",
            "text": "",
            "links": [
                {
                    "text": "SYDE 286 - Fall 2026",
                    "href": "https://learn.uwaterloo.ca/d2l/lp/ouHome/home.d2l?ou=123",
                },
                {"text": "Calendar", "href": "https://learn.uwaterloo.ca/d2l/le/calendar/6606"},
            ],
        }
    )
    result = await CourseAgent(browser, get_settings()).discover_courses()
    assert len(result.courses) == 1
    assert result.courses[0].code == "SYDE 286"
    assert result.courses[0].term == "Fall 2026"


def test_parse_due_date_converts_waterloo_time_to_utc() -> None:
    result = _parse_due_at("Quiz 2\nOct 23, 2026 9:30 AM", "America/Toronto")
    assert result is not None
    assert result.tzinfo is not None
    assert result.astimezone(UTC).hour == 13


def test_assessment_type_is_conservative() -> None:
    assert _assessment_type("Quiz 2 - Pre-Activity") == "quiz"
    assert _assessment_type("Tension-Shear Activity for Group B") == "other"
