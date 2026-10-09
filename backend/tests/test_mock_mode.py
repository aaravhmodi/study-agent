import base64
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from app.agents.course_agent import _KNOWN_LEARN_OFFERINGS, CourseAgent
from app.browser.client import BrowserClientError, MockBrowserClient
from app.browser.demo_learn import DEMO_COURSES, demo_pages
from app.config import Settings, get_settings

NOW = datetime(2026, 10, 9, 10, 0, tzinfo=ZoneInfo("America/Toronto"))


def _demo() -> MockBrowserClient:
    return MockBrowserClient(site=demo_pages(now=NOW))


def test_demo_courses_use_the_offering_ids_the_agent_knows() -> None:
    assert {course.code: course.offering_id for course in DEMO_COURSES} == _KNOWN_LEARN_OFFERINGS


@pytest.mark.asyncio
async def test_demo_site_lists_all_six_courses() -> None:
    result = await CourseAgent(_demo(), get_settings()).discover_courses()

    assert sorted(course.code or "" for course in result.courses) == [
        "SYDE 212",
        "SYDE 252",
        "SYDE 262",
        "SYDE 286",
        "SYDE 292",
        "SYDE 292L",
    ]


@pytest.mark.asyncio
async def test_demo_course_scan_finds_dated_work_lectures_and_news() -> None:
    agent = CourseAgent(_demo(), get_settings())
    course = next(
        c for c in (await agent.discover_courses()).courses if c.code == "SYDE 286"
    )

    scan = await agent.scan_course(course)

    due = {a.title: a.due_at for a in scan.assessments}
    assert set(due) == {"Quiz 2", "Assignment 3: Shear and moment diagrams", "Midterm test"}
    assert due["Quiz 2"] is not None
    assert due["Quiz 2"].date() == (NOW - timedelta(days=2)).date()
    assert {r.title for r in scan.resources} == {
        "Lecture 01: Normal stress and strain",
        "Lecture 07: Shear force and bending moment diagrams",
    }
    assert [a.title for a in scan.announcements] == ["Lecture 07 notes posted"]


@pytest.mark.asyncio
async def test_demo_lecture_downloads_as_text() -> None:
    site = demo_pages(now=NOW)
    url = next(u for u, f in site["downloads"].items() if "Lecture 07" in f["filename"])

    file = await MockBrowserClient(site=site).download_resource(url)

    assert file.content_type.startswith("text/plain")
    assert "dV/dx = -w(x)" in base64.b64decode(file.content_base64).decode("utf-8")


@pytest.mark.asyncio
async def test_unknown_demo_page_is_blank_not_an_error() -> None:
    url = "https://outline.uwaterloo.ca/viewer/?q=SYDE%20286"

    page = await _demo().inspect_page(url)

    assert page.url == url
    assert page.links == []


@pytest.mark.asyncio
async def test_unknown_demo_download_is_a_browser_error() -> None:
    with pytest.raises(BrowserClientError):
        await _demo().download_resource("https://learn.uwaterloo.ca/missing.pdf")


def test_mock_mode_never_writes_to_the_real_database() -> None:
    real = "sqlite:///./data/study_agent.db"

    assert Settings(browser_mode="mock").database_url == "sqlite:///./data/demo.db"
    assert Settings(browser_mode="mock", database_url=real).database_url == (
        "sqlite:///./data/demo.db"
    )
    assert Settings(browser_mode="mock", database_url="sqlite:///other.db").database_url == (
        "sqlite:///other.db"
    )
    assert Settings(browser_mode="local").database_url == real


def test_mock_mode_saves_files_to_a_separate_folder() -> None:
    assert Settings(browser_mode="mock").downloads_dir.name == "demo-downloads"
    assert Settings(browser_mode="local").downloads_dir.name == "downloads"


@pytest.mark.asyncio
async def test_cli_mock_browser_serves_the_demo_site(monkeypatch) -> None:
    from app.cli import commands

    monkeypatch.setattr(commands, "get_settings", lambda: Settings(browser_mode="mock"))

    home = await commands._browser_client().inspect_page("https://learn.uwaterloo.ca/d2l/home")

    assert len(home.links) == 6
