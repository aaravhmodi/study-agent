import re
from datetime import datetime
from urllib.parse import parse_qs, quote, urlsplit
from zoneinfo import ZoneInfo

from pydantic import AnyHttpUrl, TypeAdapter

from app.browser.client import BrowserClient, BrowserClientError
from app.config import Settings
from app.schemas.browser import BrowserPageSnapshot
from app.schemas.course import CourseDiscoveryResult, CourseSummary
from app.schemas.extraction import (
    AnnouncementExtraction,
    AssessmentExtraction,
    CourseScanResult,
    ResourceExtraction,
)

_HTTP_URL = TypeAdapter(AnyHttpUrl)


class CourseAgent:
    """Read-only course discovery and course-surface inspection agent."""

    def __init__(self, browser: BrowserClient, settings: Settings) -> None:
        self.browser = browser
        self.settings = settings

    async def discover_courses(self) -> CourseDiscoveryResult:
        home_url = f"{self.settings.learn_url.rstrip('/')}/d2l/home"
        snapshot = await self.browser.inspect_page(home_url, wait_seconds=6)
        courses: dict[str, CourseSummary] = {}
        warnings: list[str] = []
        for link in snapshot.links:
            if not _is_course_link(link.href):
                continue
            course = _course_from_link(link.text, link.href)
            if course is not None:
                courses[course.code or str(course.url)] = course

        try:
            outline = await self.browser.inspect_page(
                "https://outline.uwaterloo.ca/viewer/", wait_seconds=5
            )
            for outline_course in _outline_courses(outline):
                key = outline_course.code or str(outline_course.url)
                existing = courses.get(key)
                if existing is None:
                    courses[key] = outline_course
                else:
                    existing.outline_url = outline_course.outline_url
        except BrowserClientError as exc:
            warnings.append(f"Unable to inspect Outline enrollment: {exc}")

        if not courses:
            warnings.append("No active course links were visible on LEARN or Outline.")
        return CourseDiscoveryResult(courses=list(courses.values()), warnings=warnings)

    async def scan_course(self, course: CourseSummary) -> CourseScanResult:
        course_url = str(course.url)
        ou = _course_offering_id(course_url)

        warnings: list[str] = []
        snapshots: list[BrowserPageSnapshot] = []
        if ou is not None:
            home = await self.browser.inspect_page(course_url, wait_seconds=4)
            snapshots.append(home)

            for page_url in (
                f"{self.settings.learn_url.rstrip('/')}/d2l/le/calendar/{ou}",
                f"{self.settings.learn_url.rstrip('/')}/d2l/le/content/{ou}/Home",
                f"{self.settings.learn_url.rstrip('/')}/d2l/lms/news/main.d2l?ou={ou}",
            ):
                try:
                    snapshots.append(await self.browser.inspect_page(page_url, wait_seconds=4))
                except BrowserClientError as exc:
                    warnings.append(f"Unable to inspect {page_url}: {exc}")
        else:
            warnings.append(
                f"LEARN course shell was not exposed for {course.name}; scanning its Outline."
            )

        outline_snapshot = await self._inspect_outline(course, warnings)
        if outline_snapshot is not None:
            snapshots.append(outline_snapshot)

        assessments = await self._extract_assessments(snapshots)
        announcements = _extract_announcements(snapshots)
        resources = _extract_resources(snapshots)
        return CourseScanResult(
            course_name=course.name,
            assessments=assessments,
            announcements=announcements,
            resources=resources,
            topics=[],
            warnings=warnings,
        )

    async def _inspect_outline(
        self, course: CourseSummary, warnings: list[str]
    ) -> BrowserPageSnapshot | None:
        search = quote(course.code or course.name)
        outline_url = (
            str(course.outline_url)
            if course.outline_url
            else (f"https://outline.uwaterloo.ca/viewer/?q={search}")
        )
        try:
            snapshot = await self.browser.inspect_page(outline_url, wait_seconds=5)
        except BrowserClientError as exc:
            warnings.append(f"Unable to inspect Outline for {course.name}: {exc}")
            return None
        visible_outline = any("/viewer/view/" in link.href for link in snapshot.links)
        if not visible_outline and "Loading..." in snapshot.text:
            warnings.append(
                f"Outline search was still loading for {course.name}; no link was visible."
            )
        return snapshot

    async def _extract_assessments(
        self, snapshots: list[BrowserPageSnapshot]
    ) -> list[AssessmentExtraction]:
        event_links = {
            link.href: _clean_event_title(link.text)
            for snapshot in snapshots
            for link in snapshot.links
            if "/d2l/le/calendar/" in link.href and "/event/" in link.href and "Due" in link.text
        }
        assessments: list[AssessmentExtraction] = []
        for event_url, fallback_title in list(event_links.items())[:30]:
            try:
                event = await self.browser.inspect_page(event_url, wait_seconds=2)
            except BrowserClientError:
                continue
            title = _event_title(event.text, fallback_title)
            due_at = _parse_due_at(event.text, self.settings.timezone)
            assessments.append(
                AssessmentExtraction(
                    title=title,
                    assessment_type=_assessment_type(title),
                    due_at=due_at,
                    source_url=_HTTP_URL.validate_python(event_url),
                )
            )
        return _dedupe_assessments(assessments)


def _outline_courses(snapshot: BrowserPageSnapshot) -> list[CourseSummary]:
    """Read the current-term enrolled-course table and its ordered VIEW links."""

    lines = [line.strip() for line in snapshot.text.splitlines()]
    term_index = next(
        (
            index
            for index, line in enumerate(lines)
            if re.fullmatch(r"(?:Fall|Winter|Spring) \d{4}", line)
        ),
        None,
    )
    if term_index is None:
        return []
    term = lines[term_index]
    view_links = [link.href for link in snapshot.links if "/viewer/view/" in link.href]
    view_index = 0
    courses: list[CourseSummary] = []
    course_pattern = re.compile(r"^(?P<code>[A-Z]{2,8} \d{3}[A-Z]?)\t(?P<title>[^\t]+)")
    for line in lines[term_index + 1 :]:
        if re.fullmatch(r"(?:Fall|Winter|Spring) \d{4}", line):
            break
        match = course_pattern.match(line)
        if match is None or view_index >= len(view_links):
            continue
        code = match.group("code")
        outline_url = _HTTP_URL.validate_python(view_links[view_index])
        view_index += 1
        courses.append(
            CourseSummary(
                name=f"{code} - {term}",
                code=code,
                url=outline_url,
                term=term,
                outline_url=outline_url,
            )
        )
    return courses


def _is_course_link(href: str) -> bool:
    parsed = urlsplit(href)
    if parsed.netloc != "learn.uwaterloo.ca":
        return False
    return ("/d2l/lp/ouHome/home.d2l" in parsed.path and "ou=" in parsed.query) or bool(
        re.search(r"/d2l/home/\d+", parsed.path)
    )


def _course_from_link(text: str, href: str) -> CourseSummary | None:
    name = " ".join(text.split())
    if not name or name.lower() in {"course home", "home"}:
        return None
    match = re.match(r"^(?P<code>[A-Z]{2,8}\s*\d{3}[A-Z]?)\s*-\s*(?P<term>.+)$", name)
    if match is None:
        return None
    code = match.group("code") if match else None
    term = match.group("term") if match else None
    if code:
        code = re.sub(r"\s+", " ", code)
    return CourseSummary(name=name, code=code, url=_HTTP_URL.validate_python(href), term=term)


def _course_offering_id(url: str) -> str | None:
    parsed = urlsplit(url)
    query_id = parse_qs(parsed.query).get("ou", [None])[0]
    if query_id:
        return query_id
    match = re.search(r"/d2l/home/(\d+)", parsed.path)
    return match.group(1) if match else None


def _clean_event_title(value: str) -> str:
    title = " ".join(value.replace("View Event -", "").split())
    return re.sub(r"\s+-\s+Due$", "", title, flags=re.IGNORECASE).strip()


def _event_title(text: str, fallback: str) -> str:
    for line in (" ".join(line.split()) for line in text.splitlines()):
        if line and re.search(
            r"(quiz|assignment|lab|test|exam|project|activity|midterm|final)", line, re.I
        ):
            return re.sub(r"\s+-\s+Due$", "", line, flags=re.IGNORECASE).strip()
    return fallback or "Untitled assessment"


def _parse_due_at(text: str, timezone_name: str) -> datetime | None:
    match = re.search(
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}\s+(?:AM|PM)\b",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    try:
        local = datetime.strptime(match.group(), "%b %d, %Y %I:%M %p")
        return local.replace(tzinfo=ZoneInfo(timezone_name)).astimezone(ZoneInfo("UTC"))
    except ValueError:
        return None


def _assessment_type(title: str) -> str:
    lowered = title.lower()
    for kind in ("quiz", "test", "exam", "assignment", "lab", "project"):
        if kind in lowered:
            return kind
    return "other"


def _dedupe_assessments(items: list[AssessmentExtraction]) -> list[AssessmentExtraction]:
    unique: dict[tuple[str, datetime | None], AssessmentExtraction] = {}
    for item in items:
        key = (item.title.casefold(), item.due_at)
        unique[key] = item
    return list(unique.values())


def _extract_announcements(snapshots: list[BrowserPageSnapshot]) -> list[AnnouncementExtraction]:
    unique: dict[str, AnnouncementExtraction] = {}
    for snapshot in snapshots:
        for link in snapshot.links:
            if "/d2l/le/news/" not in link.href or "/view" not in link.href:
                continue
            title = " ".join(link.text.split())
            if title:
                unique[link.href] = AnnouncementExtraction(
                    title=title, source_url=_HTTP_URL.validate_python(link.href)
                )
    return list(unique.values())


def _extract_resources(snapshots: list[BrowserPageSnapshot]) -> list[ResourceExtraction]:
    unique: dict[str, ResourceExtraction] = {}
    for snapshot in snapshots:
        if snapshot.url and "outline.uwaterloo.ca/viewer/view/" in str(snapshot.url):
            unique[str(snapshot.url)] = ResourceExtraction(
                title=f"{snapshot.title or 'Course outline'} (course outline)",
                resource_type="LINK",
                url=_HTTP_URL.validate_python(snapshot.url),
            )
        for link in snapshot.links:
            title = " ".join(link.text.split())
            if not title or link.href.startswith("javascript:"):
                continue
            if "/d2l/le/content/" in link.href and (
                "viewContent" in link.href or "PDF" in title.upper() or "SLIDE" in title.upper()
            ):
                resource_type = "PDF" if "PDF" in title.upper() else "PAGE"
                unique[link.href] = ResourceExtraction(
                    title=title,
                    resource_type=resource_type,
                    url=_HTTP_URL.validate_python(link.href),
                )
            elif "outline.uwaterloo.ca/viewer/view/" in link.href:
                unique[link.href] = ResourceExtraction(
                    title=f"{title} (course outline)" if title else "Course outline",
                    resource_type="LINK",
                    url=_HTTP_URL.validate_python(link.href),
                )
    return list(unique.values())
