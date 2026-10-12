from datetime import UTC
from zoneinfo import ZoneInfo

import pytest
from app.agents.course_agent import (
    CourseAgent,
    _apply_known_learn_offerings,
    _assessment_type,
    _course_from_link,
    _extract_outline_assessments,
    _extract_resources,
    _outline_courses,
    _parse_due_at,
)
from app.browser.client import MockBrowserClient
from app.config import get_settings
from app.schemas.browser import BrowserPageSnapshot, PageLink
from app.schemas.course import CourseSummary


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
    assert {course.code for course in result.courses} == {
        "SYDE 212",
        "SYDE 252",
        "SYDE 262",
        "SYDE 286",
        "SYDE 292",
        "SYDE 292L",
    }


def test_community_hub_is_not_treated_as_a_course() -> None:
    result = _course_from_link(
        "Engineering Co-op Community",
        "https://learn.uwaterloo.ca/d2l/lp/ouHome/home.d2l?ou=999",
    )
    assert result is None


def test_course_code_can_be_found_in_a_descriptive_link_label() -> None:
    result = _course_from_link(
        "Open course: SYDE 212 - Probability, Statistics, and Data Science",
        "https://learn.uwaterloo.ca/d2l/lp/ouHome/home.d2l?ou=212000",
    )
    assert result is not None
    assert result.code == "SYDE 212"


def test_known_offering_fallback_replaces_outline_url() -> None:
    course = _course_from_link(
        "SYDE 292L - Fall 2026",
        "https://outline.uwaterloo.ca/viewer/view/example",
    )
    assert course is not None
    _apply_known_learn_offerings({course.code or "": course})
    assert "ou=1296009" in str(course.url)


def test_known_offering_fallback_adds_missing_course() -> None:
    courses: dict[str, CourseSummary] = {}
    _apply_known_learn_offerings(courses)
    assert "SYDE 292" in courses
    assert "ou=1292783" in str(courses["SYDE 292"].url)
    assert "SYDE 212" in courses
    assert "ou=1299242" in str(courses["SYDE 212"].url)


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


def test_outline_assessment_dates_and_weights_are_extracted() -> None:
    snapshot = BrowserPageSnapshot(
        url="https://outline.uwaterloo.ca/viewer/view/example",
        title="Fall 2026: Example",
        text=(
            "Assessments & Activities\n"
            "Component / Activity\tDate or Due Date\tLocation\tWeight (%)\n"
            "Quiz 1\tFriday, October 23, 2026\tIn person\t20\n"
            "Late / Missed Content\n"
        ),
    )
    assessments = _extract_outline_assessments(snapshot, "America/Toronto")
    assert len(assessments) == 1
    assert assessments[0].title == "Quiz 1"
    assert assessments[0].due_at is not None
    assert assessments[0].due_at.astimezone(ZoneInfo("America/Toronto")).day == 23
    assert assessments[0].weight_percent == 20


def test_outline_explicit_deliverable_deadlines_are_extracted() -> None:
    snapshot = BrowserPageSnapshot(
        url="https://outline.uwaterloo.ca/viewer/view/syde252",
        title="Fall 2026: SYDE 252",
        text=(
            "Deliverables schedule\n"
            "Assignments due\n"
            "at 11:59 PM\n"
            "Phase 1 due: October 30, 11:59 PM\n"
            "Phase 2 due: November 23, 11:59 PM\n"
            "Late / Missed Content\n"
        ),
    )
    assessments = _extract_outline_assessments(snapshot, "America/Toronto")
    assert [assessment.title for assessment in assessments] == ["Phase 1", "Phase 2"]
    assert all(assessment.assessment_type == "project" for assessment in assessments)
    assert assessments[0].due_at is not None
    assert assessments[0].due_at.astimezone(ZoneInfo("America/Toronto")).day == 30


# The SYDE 252 deliverables schedule as Outline shows it: one cell per line, the five
# assignments as "#1".."#5" under an "Assignments due / at 11:59 PM" column.
SYDE_252_SCHEDULE = (
    "Deliverables schedule\nWeek\nWeek of\nAssignments due\nat 11:59 PM\nProject\n"
    "1\n09-07\n2\n09-14\n3\n09-21\nTeam composition due: September 21, 11:59 PM\n"
    "Project Kick off: September 23\n4\n09-28\n#1\nOctober 2, 2026\nat 11:59 PM\n"
    "5\n10-05\n#2\nOctober 9, 2026\nat 11:59 PM\n6\n10-12\nREADING WEEK\n"
    "7\n10-19\nMIDTERM WEEK\n8\n10-26\nPhase 1 due: October 30, 11:59 PM\n"
    "9\n11-02\n10\n11-09\n11\n11-16\n#3\nNovember 16, 2026\nat 11:59 PM\n"
    "12\n11-23\nPhase 2 due: November 23, 11:59 PM\n13\n11-30\n#4\nNovember 30, 2026\n"
    "at 11:59 PM\n14\n12-07\n#5\nDecember 7, 2026\nPhase 3 due: December 8, 11:59 PM\n"
    "at 11:59 PM\nTentative lecture and reading schedule\n"
)


def test_outline_numbered_assignments_in_a_deliverables_schedule_are_extracted() -> None:
    # These were missed, so Assignment 2 (due October 9) never reached the reminders.
    snapshot = BrowserPageSnapshot(
        url="https://outline.uwaterloo.ca/viewer/view/nrzht7",
        title="Fall 2026: SYDE 252",
        text=SYDE_252_SCHEDULE,
    )
    assessments = _extract_outline_assessments(snapshot, "America/Toronto")
    toronto = ZoneInfo("America/Toronto")
    due = {
        a.title: a.due_at.astimezone(toronto).strftime("%b %d %H:%M")
        for a in assessments
        if a.due_at is not None
    }

    assert due == {
        "Team composition": "Sep 21 23:59",
        "Assignment 1": "Oct 02 23:59",
        "Assignment 2": "Oct 09 23:59",
        "Phase 1": "Oct 30 23:59",
        "Assignment 3": "Nov 16 23:59",
        "Phase 2": "Nov 23 23:59",
        "Assignment 4": "Nov 30 23:59",
        "Assignment 5": "Dec 07 23:59",
        "Phase 3": "Dec 08 23:59",
    }
    assignment = next(a for a in assessments if a.title == "Assignment 2")
    assert assignment.assessment_type == "assignment"


def test_numbered_items_are_read_from_a_tab_separated_schedule_too() -> None:
    snapshot = BrowserPageSnapshot(
        url="https://outline.uwaterloo.ca/viewer/view/abc123",
        title="Winter 2027: SYDE 999",
        text=(
            "Week\tQuizzes due at 10:00 AM\tNotes\n"
            "3\t#1\tJanuary 23, 2027\t\n"
            "5\t#2\tFebruary 6, 2027 at 10:00 AM\tbring a calculator\n"
            "6\t#3\tTBD\t\n"
        ),
    )
    toronto = ZoneInfo("America/Toronto")
    due = {
        a.title: a.due_at.astimezone(toronto).strftime("%b %d %H:%M")
        for a in _extract_outline_assessments(snapshot, "America/Toronto")
        if a.due_at is not None
    }

    assert due == {"Quiz 1": "Jan 23 10:00", "Quiz 2": "Feb 06 10:00"}


def test_numbers_outside_a_due_column_are_not_assignments() -> None:
    snapshot = BrowserPageSnapshot(
        url="https://outline.uwaterloo.ca/viewer/view/abc123",
        title="Fall 2026: SYDE 999",
        text="Lecture schedule\n#1\nOctober 2, 2026\nTopic: Fourier series\n",
    )
    assert _extract_outline_assessments(snapshot, "America/Toronto") == []


def test_outline_keeps_unknown_midterm_and_final_rows() -> None:
    snapshot = BrowserPageSnapshot(
        url="https://outline.uwaterloo.ca/viewer/view/syde252",
        title="Fall 2026: SYDE 252",
        text=(
            "Assessments & Activities\n"
            "Component / Activity\tDate or Due Date\tLocation\tWeight (%)\n"
            "Midterm exam\t\tIn person\t25%\n"
            "Final exam\tTBD\tIn Person\t35%\n"
            "Late / Missed Content\n"
        ),
    )
    assessments = _extract_outline_assessments(snapshot, "America/Toronto")
    assert {assessment.title for assessment in assessments} == {"Midterm exam", "Final exam"}
    assert all(assessment.due_at is None for assessment in assessments)


def test_outline_attaches_weight_from_wrapped_continuation_row() -> None:
    snapshot = BrowserPageSnapshot(
        url="https://outline.uwaterloo.ca/viewer/view/syde286",
        title="Fall 2026: SYDE 286",
        text=(
            "Assessments & Activities\n"
            "Component / Activity\tDate or Due Date\tLocation\tWeight (%)\n"
            "Midterm Test\tWednesday, October 21\n"
            "5:30 PM - 7:00 PM\n"
            "E5-6006 and E5-6008\tin person\t25\n"
            "Late / Missed Content\n"
        ),
    )
    assessments = _extract_outline_assessments(snapshot, "America/Toronto")
    assert len(assessments) == 1
    assert assessments[0].title == "Midterm Test"
    assert assessments[0].weight_percent == 25
    assert assessments[0].due_at is not None


def test_outline_accepts_abbreviated_month_with_period_and_splits_labeled_dates() -> None:
    snapshot = BrowserPageSnapshot(
        url="https://outline.uwaterloo.ca/viewer/view/syde212",
        title="Fall 2026: SYDE 212",
        text=(
            "Assessments & Activities\n"
            "Component / Activity\tDate or Due Date\tLocation\tWeight (%)\n"
            "Midterm\tOct. 23rd\tIn person\t40%\n"
            "Cumulative assessment\tProposal: October 9th, 11:59pm "
            "Final Report: December 8th, 2026, 11:59pm\tCrowdmark\t10%\n"
            "Late / Missed Content\n"
        ),
    )
    assessments = _extract_outline_assessments(snapshot, "America/Toronto")
    assert any(item.title == "Midterm" and item.due_at is not None for item in assessments)
    labeled = {item.title for item in assessments if item.title.startswith("Cumulative assessment")}
    assert labeled == {"Cumulative assessment - Proposal", "Cumulative assessment - Final Report"}


def test_dedupe_prefers_dated_item_over_unknown_outline_row() -> None:
    snapshot = BrowserPageSnapshot(
        url="https://outline.uwaterloo.ca/viewer/view/syde252",
        title="Fall 2026: SYDE 252",
        text=(
            "Assessments & Activities\n"
            "Component / Activity\tDate or Due Date\tLocation\tWeight (%)\n"
            "Project Phase 1\t\tLearn Dropbox\t10%\n"
            "Late / Missed Content\n"
            "Phase 1 due: October 30, 11:59 PM\n"
        ),
    )
    assessments = _extract_outline_assessments(snapshot, "America/Toronto")
    phase_one = [item for item in assessments if "Phase 1" in item.title]
    assert len(phase_one) == 1
    assert phase_one[0].due_at is not None


def test_announced_assessment_is_extracted_from_news_detail() -> None:
    from app.agents.course_agent import _extract_announced_assessments

    snapshot = BrowserPageSnapshot(
        url="https://learn.uwaterloo.ca/d2l/le/news/123/456/view",
        title="Quiz 2 information",
        text="Quiz 2 is due Friday, October 23, 2026 at 11:59 PM.",
    )
    assessments = _extract_announced_assessments([snapshot], "America/Toronto")
    assert len(assessments) == 1
    assert assessments[0].title == "Quiz 2"


def test_an_announcements_posted_by_line_is_not_a_deadline() -> None:
    from app.agents.course_agent import _extract_announced_assessments

    # LEARN puts "<name> posted on <date>" at the top of every announcement. With a
    # coursework word in the title, that line used to become a deadline called
    # "Reem Roufail posted", due the day it was posted.
    snapshot = BrowserPageSnapshot(
        url="https://learn.uwaterloo.ca/d2l/le/news/1292394/1146084/view",
        title="Quiz 2 reminder",
        text=(
            "Reem Roufail posted on Oct 9, 2026 3:45 PM\n"
            "Edited on Oct 10, 2026 9:02 AM\n"
            "Quiz 2 is due Friday, October 23, 2026 at 11:59 PM.\n"
            "Assignment 3 is posted on LEARN and due October 30, 2026 at 11:59 PM.\n"
            "Published: Oct 9, 2026\n"
        ),
    )
    assessments = _extract_announced_assessments([snapshot], "America/Toronto")
    assert [item.title for item in assessments] == ["Quiz 2", "Assignment 3"]


def test_a_deadline_is_not_dated_from_the_posted_by_line_below_it() -> None:
    from app.agents.course_agent import _extract_announced_assessments

    snapshot = BrowserPageSnapshot(
        url="https://learn.uwaterloo.ca/d2l/le/news/1296009/1144040/view",
        title="Lab update",
        text="The lab report is due on\nOrion Bruckman posted on Oct 1, 2026 5:13 PM\n",
    )
    assert _extract_announced_assessments([snapshot], "America/Toronto") == []


def test_content_documents_are_classified_as_resources() -> None:
    snapshot = BrowserPageSnapshot(
        url="https://learn.uwaterloo.ca/d2l/le/content/123/Home",
        links=[
            PageLink(
                text="Lecture Notes - Word document",
                href="https://learn.uwaterloo.ca/d2l/le/content/123/viewContent/456/View",
            ),
            PageLink(
                text="Lecture Slides - PowerPoint presentation",
                href="https://learn.uwaterloo.ca/d2l/le/content/123/viewContent/789/View",
            ),
        ],
    )
    resources = _extract_resources([snapshot])
    assert [resource.resource_type for resource in resources] == ["DOCUMENT", "SLIDES"]


def test_content_page_text_is_preserved_for_rag() -> None:
    snapshot = BrowserPageSnapshot(
        url="https://learn.uwaterloo.ca/d2l/le/content/1318237/viewContent/6728917/View",
        text=(
            "Expand side panel\nLinear Systems and Signals\n"
            "The transfer function is H(s) = Y(s) / X(s)."
        ),
        links=[
            PageLink(
                text="Expand side panelCollapse side panel",
                href="https://learn.uwaterloo.ca/d2l/le/content/1318237/viewContent/6728917/View",
            )
        ],
    )
    resources = _extract_resources([snapshot])
    assert resources[0].content_text is not None
    assert "transfer function" in resources[0].content_text


def test_syde286_lecture_one_shear_stress_resource_uses_content_api() -> None:
    snapshot = BrowserPageSnapshot(
        url=("https://learn.uwaterloo.ca/d2l/api/le/1.82/1292394/content/topics/6590136/file"),
        title="Lecture 1-Intro & Stress",
        text="Lecture 1 introduces normal stress and shear stress.",
        links=[
            PageLink(
                text="Lecture 1-Intro & Stress",
                href=(
                    "https://learn.uwaterloo.ca/d2l/api/le/1.82/1292394/content/topics/6590136/file"
                ),
            )
        ],
    )

    resources = _extract_resources([snapshot])

    assert len(resources) == 1
    assert resources[0].title == "Lecture 1-Intro & Stress"
    assert resources[0].resource_type == "DOCUMENT"
    assert "/content/topics/6590136/file" in str(resources[0].url)
    assert resources[0].content_text is not None
    assert "shear stress" in resources[0].content_text.lower()


def test_recording_resources_are_marked_as_video() -> None:
    snapshot = BrowserPageSnapshot(
        url="https://learn.uwaterloo.ca/d2l/le/content/1292783/Home",
        links=[
            PageLink(
                text="Fundamental Circuit Analysis Recording - Video",
                href="https://learn.uwaterloo.ca/d2l/le/content/1292783/viewContent/6711698/View",
            )
        ],
    )

    resources = _extract_resources([snapshot])

    assert resources[0].resource_type == "VIDEO"


SIGN_IN_PAGE = {
    "url": "https://adfs.uwaterloo.ca/adfs/ls/",
    "title": "Sign In",
    "text": "Sign in with username@uwaterloo.ca\nNext",
}


@pytest.mark.asyncio
async def test_a_course_that_opens_the_sign_in_page_is_not_scanned() -> None:
    from app.browser.client import SignedOutError

    # LEARN had signed the browser out; every course page was UWaterloo's sign-in page,
    # and the sync "completed" having read nothing.
    course = CourseSummary(
        name="SYDE 286 - Fall 2026",
        code="SYDE 286",
        url="https://learn.uwaterloo.ca/d2l/lp/ouHome/home.d2l?ou=1292394",
    )
    agent = CourseAgent(MockBrowserClient(SIGN_IN_PAGE), get_settings())

    with pytest.raises(SignedOutError, match="not authenticated"):
        await agent.scan_course(course)
