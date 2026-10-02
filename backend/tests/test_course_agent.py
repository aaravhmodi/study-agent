from datetime import UTC

import pytest
from app.agents.course_agent import (
    CourseAgent,
    _assessment_type,
    _outline_courses,
    _parse_due_at,
)
from app.browser.client import MockBrowserClient
from app.config import get_settings
from app.schemas.browser import BrowserPageSnapshot, PageLink


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


def test_outline_enrollment_adds_current_term_courses() -> None:
    snapshot = BrowserPageSnapshot(
        url="https://outline.uwaterloo.ca/viewer/",
        title="Outline",
        text=(
            "My Enrolled Courses\nFall 2026\nCourse\tTitle\tSections\t\n"
            "SYDE 212\tProbability, Statistics, and Data Science\t001\t\nVIEW\n"
            "SYDE 252\tLinear Systems and Signals\t001, 101\t\nVIEW\n"
            "Spring 2026\nCourse\tTitle\tSections\t\nPD 11\tTechnical Writing\t081\t\nVIEW"
        ),
        links=[
            PageLink(text="VIEW", href="https://outline.uwaterloo.ca/viewer/view/212"),
            PageLink(text="VIEW", href="https://outline.uwaterloo.ca/viewer/view/252"),
            PageLink(text="VIEW", href="https://outline.uwaterloo.ca/viewer/view/pd11"),
        ],
    )
    courses = _outline_courses(snapshot)
    assert [course.code for course in courses] == ["SYDE 212", "SYDE 252"]
