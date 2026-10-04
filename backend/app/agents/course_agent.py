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

            content_url = f"{self.settings.learn_url.rstrip('/')}/d2l/le/content/{ou}/Home"
            for page_url in (
                f"{self.settings.learn_url.rstrip('/')}/d2l/le/calendar/{ou}",
                content_url,
                f"{self.settings.learn_url.rstrip('/')}/d2l/lms/news/main.d2l?ou={ou}",
            ):
                try:
                    snapshots.append(await self.browser.inspect_page(page_url, wait_seconds=4))
                except BrowserClientError as exc:
                    warnings.append(f"Unable to inspect {page_url}: {exc}")
            try:
                snapshots.extend(await self.browser.inspect_content(content_url, wait_seconds=3))
            except BrowserClientError as exc:
                warnings.append(
                    f"Unable to traverse LEARN content modules for {course.name}: {exc}"
                )
        else:
            warnings.append(
                f"LEARN course shell was not exposed for {course.name}; scanning its Outline."
            )

        outline_snapshot = await self._inspect_outline(course, warnings)
        if outline_snapshot is not None:
            snapshots.append(outline_snapshot)

        # Announcement list pages only expose a title and a link. Open the
        # read-only detail pages too: due dates are often announced there
        # before they appear in the LEARN calendar.
        announcement_urls = {
            link.href
            for snapshot in snapshots
            for link in snapshot.links
            if _is_news_detail_url(link.href)
        }
        for announcement_url in list(announcement_urls)[:30]:
            try:
                snapshots.append(await self.browser.inspect_page(announcement_url, wait_seconds=2))
            except BrowserClientError as exc:
                warnings.append(f"Unable to inspect announcement {announcement_url}: {exc}")

        assessments = await self._extract_assessments(snapshots)
        assessments.extend(_extract_announced_assessments(snapshots, self.settings.timezone))
        if outline_snapshot is not None:
            assessments.extend(
                _extract_outline_assessments(outline_snapshot, self.settings.timezone)
            )
            assessments = _dedupe_assessments(assessments)
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


def _extract_outline_assessments(
    snapshot: BrowserPageSnapshot, timezone_name: str
) -> list[AssessmentExtraction]:
    lines = snapshot.text.splitlines()
    headings = [
        index for index, line in enumerate(lines) if line.strip() == "Assessments & Activities"
    ]
    year_match = re.search(r"(?:Fall|Winter|Spring)\s+(\d{4})", snapshot.text)
    default_year = int(year_match.group(1)) if year_match else datetime.now().year
    assessments: list[AssessmentExtraction] = []
    if headings:
        start = headings[-1] + 1
        end = next(
            (
                index
                for index in range(start, len(lines))
                if lines[index].strip() == "Late / Missed Content"
            ),
            len(lines),
        )
        for line in lines[start:end]:
            fields = [field.strip() for field in line.split("\t")]
            if len(fields) < 2 or not fields[0]:
                continue
            raw_title = fields[0]
            raw_details = " ".join(field for field in fields[1:] if field)
            if raw_title.casefold() == "component / activity":
                continue
            if not re.search(
                r"\b(assignment|quiz|test|exam|midterm|final|lab|project|phase|"
                r"participation|report|activity|assessment|grading|review)\b",
                raw_title,
                flags=re.IGNORECASE,
            ):
                # Waterloo sometimes wraps a table row across the next line,
                # e.g. the SYDE 286 midterm location and its 25% weight.
                continuation_weight = re.search(r"(?:^|\s)(\d+(?:\.\d+)?)\s*%?$", raw_details)
                if assessments and continuation_weight:
                    assessments[-1].weight_percent = float(continuation_weight.group(1))
                continue
            title = _clean_outline_title(raw_title)
            weight_match = re.search(r"\b(\d+(?:\.\d+)?)\s*%", raw_details)
            if weight_match:
                weight = float(weight_match.group(1))
            elif len(fields) >= 4 and re.fullmatch(r"\d+(?:\.\d+)?", fields[3]):
                weight = float(fields[3])
            else:
                weight = None
            # Keep rows such as "Midterm exam | TBD | In person | 25%". A
            # missing date is useful information and is intentionally stored
            # as UNKNOWN instead of silently dropping the assessment.
            labeled_dates = list(
                re.finditer(
                    r"(?:^|\s)(?P<label>[A-Za-z][A-Za-z0-9 /_-]{1,60}?):\s*"
                    r"(?=(?:January|February|March|April|May|June|July|August|September|October|November|December|"
                    r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d)",
                    raw_details,
                    flags=re.IGNORECASE,
                )
            )
            if len(labeled_dates) > 1:
                for labeled_date in labeled_dates:
                    label = " ".join(labeled_date.group("label").split())
                    date_details = raw_details[labeled_date.start() :]
                    due_at = _parse_outline_due(date_details, default_year, timezone_name)
                    assessments.append(
                        AssessmentExtraction(
                            title=f"{title} - {label}",
                            assessment_type=_assessment_type(title),
                            due_at=due_at,
                            weight_percent=weight,
                            description=f"Outline date: {raw_details}",
                            source_url=_HTTP_URL.validate_python(snapshot.url),
                        )
                    )
            else:
                due_at = _parse_outline_due(
                    f"{raw_title} {raw_details}", default_year, timezone_name
                )
                assessments.append(
                    AssessmentExtraction(
                        title=title,
                        assessment_type=_assessment_type(title),
                        due_at=due_at,
                        weight_percent=weight,
                        description=f"Outline assessment row: {raw_details or 'Date not provided'}",
                        source_url=_HTTP_URL.validate_python(snapshot.url),
                    )
                )

    # Some Waterloo outlines leave the assessment table dates blank and put the
    # real deadlines in a later deliverables/project schedule.  Only accept an
    # explicit "<item> due: <date>" or "<item> due on <date>" statement so
    # ordinary prose such as "late assignments" cannot become an assessment.
    explicit_due_pattern = re.compile(
        r"^(?P<title>[^:\t]{2,100}?)\s+(?:due|deadline)\s*(?::|on)\s*"
        r"(?P<details>.+)$",
        flags=re.IGNORECASE,
    )
    for line in lines:
        match = explicit_due_pattern.match(" ".join(line.split()))
        if match is None:
            continue
        title = _clean_outline_title(match.group("title"))
        details = match.group("details").strip()
        due_at = _parse_outline_due(details, default_year, timezone_name)
        if due_at is None:
            continue
        assessments.append(
            AssessmentExtraction(
                title=title,
                assessment_type=_assessment_type(title),
                due_at=due_at,
                description=f"Outline explicit deadline: {details}",
                source_url=_HTTP_URL.validate_python(snapshot.url),
            )
        )
    return _dedupe_assessments(assessments)


def _clean_outline_title(title: str) -> str:
    cleaned = re.sub(
        r"\s*:\s*(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\b.*$",
        "",
        title,
        flags=re.IGNORECASE,
    ).strip()
    return cleaned or title.strip()


def _parse_outline_due(text: str, default_year: int, timezone_name: str) -> datetime | None:
    match = re.search(
        r"(?P<month>January|February|March|April|May|June|July|August|September|October|"
        r"November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+"
        r"(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:,|\s)*"
        r"(?:(?P<year>\d{4})(?:,|\s)*)?"
        r"(?P<time>\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))?",
        text,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    year = int(match.group("year") or default_year)
    time_text = match.group("time")
    month_text = match.group("month").rstrip(".")
    try:
        if time_text:
            normalized_time = time_text.replace(" ", "").upper()
            parsed = datetime.strptime(
                f"{month_text} {match.group('day')} {year} {normalized_time}",
                "%B %d %Y %I:%M%p",
            )
        else:
            parsed = datetime.strptime(
                f"{month_text} {match.group('day')} {year}", "%B %d %Y"
            ).replace(hour=23, minute=59)
        return parsed.replace(tzinfo=ZoneInfo(timezone_name)).astimezone(ZoneInfo("UTC"))
    except ValueError:
        try:
            parsed = datetime.strptime(
                f"{month_text} {match.group('day')} {year}", "%b %d %Y"
            ).replace(hour=23, minute=59)
            return parsed.replace(tzinfo=ZoneInfo(timezone_name)).astimezone(ZoneInfo("UTC"))
        except ValueError:
            return None


def _assessment_type(title: str) -> str:
    lowered = title.lower()
    for kind in (
        "quiz",
        "test",
        "exam",
        "midterm",
        "assignment",
        "lab",
        "project",
        "phase",
        "final",
    ):
        if kind in lowered:
            return (
                "test"
                if kind == "midterm"
                else "project"
                if kind == "phase"
                else "exam"
                if kind == "final"
                else kind
            )
    return "other"


def _dedupe_assessments(items: list[AssessmentExtraction]) -> list[AssessmentExtraction]:
    unique: list[AssessmentExtraction] = []
    for item in items:
        matching_indexes = [
            index
            for index, existing in enumerate(unique)
            if _assessment_titles_match(existing.title, item.title)
        ]
        if not matching_indexes:
            unique.append(item)
            continue
        matching_index = matching_indexes[0]
        existing = unique[matching_index]
        if existing.due_at is None and item.due_at is not None:
            unique[matching_index] = item
        elif existing.due_at == item.due_at:
            if existing.description is None and item.description:
                existing.description = item.description
            if existing.weight_percent is None and item.weight_percent is not None:
                existing.weight_percent = item.weight_percent
        elif item.due_at is not None and existing.due_at is not None:
            unique.append(item)
    return unique


def _assessment_titles_match(left: str, right: str) -> bool:
    left_tokens = _assessment_title_tokens(left)
    right_tokens = _assessment_title_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    if left_tokens == right_tokens:
        return True
    common = left_tokens & right_tokens
    if len(common) >= 2 and (
        left_tokens.issubset(right_tokens) or right_tokens.issubset(left_tokens)
    ):
        return True
    # "Midterm" and "Midterm exam" are the same outline item, while a
    # generic "Final" must not swallow "Final Project" or "Final Report".
    return common == {"midterm"}


def _assessment_title_tokens(title: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9]+", title.casefold()))
    return tokens - {"the", "a", "an", "exam", "assessment", "activity"}


def _is_news_detail_url(href: str) -> bool:
    return "/d2l/le/news/" in href and "/view" in href


def _extract_announced_assessments(
    snapshots: list[BrowserPageSnapshot], timezone_name: str
) -> list[AssessmentExtraction]:
    """Extract dated assessment statements from read-only LEARN announcements."""

    assessments: list[AssessmentExtraction] = []
    current_year = datetime.now().year
    for snapshot in snapshots:
        if not _is_news_detail_url(snapshot.url):
            continue
        announcement_title = _news_title(snapshot)
        lines = [" ".join(line.split()) for line in snapshot.text.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            if not re.search(
                r"\b(assignment|quiz|test|exam|midterm|final|lab|project|report|activity|assessment)\b",
                f"{announcement_title} {line}",
                flags=re.IGNORECASE,
            ):
                continue
            due_at = _parse_outline_due(line, current_year, timezone_name)
            if due_at is None and index + 1 < len(lines):
                due_at = _parse_outline_due(lines[index + 1], current_year, timezone_name)
            if due_at is None or not re.search(
                r"\b(due|deadline|scheduled|held|takes place|on)\b",
                line,
                flags=re.IGNORECASE,
            ):
                continue
            title = _clean_announced_title(line, announcement_title)
            assessments.append(
                AssessmentExtraction(
                    title=title,
                    assessment_type=_assessment_type(title),
                    due_at=due_at,
                    description=f"Announced in LEARN: {line}",
                    source_url=_HTTP_URL.validate_python(snapshot.url),
                )
            )
    return _dedupe_assessments(assessments)


def _news_title(snapshot: BrowserPageSnapshot) -> str:
    title = " ".join((snapshot.title or "").split())
    if title and title.casefold() not in {"news", "announcement", "waterloo learn"}:
        return title
    for line in (" ".join(line.split()) for line in snapshot.text.splitlines()):
        if line and not re.search(r"^(news|announcement|published|close)$", line, re.I):
            return line[:255]
    return "LEARN announcement"


def _clean_announced_title(line: str, fallback: str) -> str:
    title = re.sub(
        r"\s+(?:is\s+)?(?:due|deadline|scheduled|held|takes place|on)\b.*$",
        "",
        line,
        flags=re.I,
    ).strip(" -:;")
    title = re.sub(
        r"(?:January|February|March|April|May|June|July|August|September|October|November|December|"
        r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2}.*$",
        "",
        title,
        flags=re.I,
    ).strip(" -:;")
    return (title or fallback or "Announced assessment")[:255]


def _extract_announcements(snapshots: list[BrowserPageSnapshot]) -> list[AnnouncementExtraction]:
    unique: dict[str, AnnouncementExtraction] = {}
    details = {
        snapshot.url: snapshot for snapshot in snapshots if _is_news_detail_url(snapshot.url)
    }
    for snapshot in snapshots:
        for link in snapshot.links:
            if not _is_news_detail_url(link.href):
                continue
            title = " ".join(link.text.split())
            if title:
                detail = details.get(link.href)
                unique[link.href] = AnnouncementExtraction(
                    title=title[:255],
                    body=(detail.text[:8000] if detail and detail.text else None),
                    source_url=_HTTP_URL.validate_python(link.href),
                )
    for url, detail in details.items():
        if url in unique:
            continue
        unique[url] = AnnouncementExtraction(
            title=_news_title(detail)[:255],
            body=detail.text[:8000] if detail.text else None,
            source_url=_HTTP_URL.validate_python(url),
        )
    return list(unique.values())


def _extract_resources(snapshots: list[BrowserPageSnapshot]) -> list[ResourceExtraction]:
    unique: dict[str, ResourceExtraction] = {}
    known_titles = {
        link.href: _clean_resource_title(" ".join(link.text.split()))
        for snapshot in snapshots
        for link in snapshot.links
        if link.href and link.text.strip()
    }
    for snapshot in snapshots:
        snapshot_url = str(snapshot.url)
        if "outline.uwaterloo.ca/viewer/view/" in snapshot_url:
            unique[str(snapshot.url)] = ResourceExtraction(
                title=f"{snapshot.title or 'Course outline'} (course outline)",
                resource_type="LINK",
                url=_HTTP_URL.validate_python(snapshot.url),
                description=_resource_notes(snapshot.text),
            )
        elif "/d2l/le/content/" in snapshot_url and "viewContent" in snapshot_url:
            unique[snapshot_url] = ResourceExtraction(
                title=known_titles.get(
                    snapshot_url, _clean_resource_title(snapshot.title or "Content item")
                ),
                resource_type=_resource_type(snapshot.title or "", snapshot_url),
                url=_HTTP_URL.validate_python(snapshot_url),
                description=_resource_notes(snapshot.text),
            )
        for link in snapshot.links:
            title = " ".join(link.text.split())
            if not title or link.href.startswith("javascript:"):
                continue
            is_content_resource = (
                "/d2l/le/content/" in link.href
                and (
                    "viewContent" in link.href
                    or any(
                        token in title.upper()
                        for token in ("PDF", "DOCUMENT", "WORD", "SLIDE", "POWERPOINT")
                    )
                )
            ) or "/d2l/common/viewFile" in link.href
            if is_content_resource:
                resource_type = _resource_type(title, link.href)
                unique[link.href] = ResourceExtraction(
                    title=_clean_resource_title(title),
                    resource_type=resource_type,
                    url=_HTTP_URL.validate_python(link.href),
                    description=_resource_notes(snapshot.text),
                )
                if not unique[link.href].description:
                    unique[link.href].description = _resource_notes(snapshot.text)
    return list(unique.values())


def _resource_notes(text: str) -> str | None:
    """Keep useful read-only instructions without storing an entire page dump."""
    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    relevant = [
        line
        for line in lines
        if re.search(r"\b(dropbox|submit|submission|deliverable|upload|turnitin)\b", line, re.I)
    ]
    if not relevant:
        return None
    return "\n".join(relevant)[:4000]


def _resource_type(title: str, href: str) -> str:
    lowered = f"{title} {href}".lower()
    if "pdf" in lowered or lowered.endswith(".pdf"):
        return "PDF"
    if any(token in lowered for token in ("doc", "word", "document")):
        return "DOCUMENT"
    if any(token in lowered for token in ("ppt", "powerpoint", "slide", "presentation")):
        return "SLIDES"
    if any(token in lowered for token in ("xls", "spreadsheet")):
        return "DOCUMENT"
    if "viewcontent" in lowered:
        return "PAGE"
    return "OTHER"


def _clean_resource_title(title: str) -> str:
    cleaned = re.sub(
        r"^['\"]|['\"]\s*-\s*(?:PDF document|Word document|PowerPoint presentation|"
        r"Microsoft Word document|Microsoft PowerPoint presentation|CAP File|"
        r"External Learning Tool)$",
        "",
        title,
        flags=re.IGNORECASE,
    )
    return cleaned.strip() or title
