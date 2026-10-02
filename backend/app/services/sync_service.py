import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.course_agent import CourseAgent
from app.browser.client import BrowserClient, BrowserUseClient
from app.config import Settings
from app.db.database import SessionLocal
from app.models import Announcement, Assessment, Course, Resource, SyncRun
from app.schemas.course import CourseSummary
from app.schemas.extraction import CourseScanResult
from app.schemas.sync import SyncSummary

logger = logging.getLogger(__name__)


class SyncService:
    def __init__(
        self,
        settings: Settings,
        browser: BrowserClient | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings
        self.browser = browser or BrowserUseClient(settings)
        self.progress = progress or (lambda message: logger.info(message))

    async def run(self) -> SyncSummary:
        started_at = datetime.now(UTC)
        sync_run = SyncRun(started_at=started_at, status="RUNNING")
        with SessionLocal() as session:
            session.add(sync_run)
            session.commit()
            try:
                connection = await self.browser.test_connection()
                if not connection.learn_reachable:
                    raise RuntimeError(
                        "The browser is connected, but Waterloo LEARN is not authenticated "
                        "or reachable."
                    )

                agent = CourseAgent(self.browser, self.settings)
                discovery = await agent.discover_courses()
                self.progress(f"Found {len(discovery.courses)} active courses")
                summary = SyncSummary(
                    courses_found=len(discovery.courses),
                    assessments_found=0,
                    resources_found=0,
                    changes_found=0,
                )
                discovered_urls = {str(course.url) for course in discovery.courses}
                for existing_course in session.scalars(select(Course)).all():
                    existing_course.active = existing_course.url in discovered_urls
                failures: list[str] = []
                for course_summary in discovery.courses:
                    course = _upsert_course(session, course_summary)
                    self.progress(f"Scanning {course.name}...")
                    try:
                        scan = await agent.scan_course(course_summary)
                        counts = _persist_scan(session, course, scan)
                        summary.assessments_found += counts[0]
                        summary.resources_found += counts[1]
                        self.progress(
                            f"{course.name}: {counts[0]} assessments, {counts[1]} resources, "
                            f"{len(scan.announcements)} announcements"
                        )
                    except Exception as exc:
                        failures.append(f"{course.name}: {exc}")
                        logger.exception("Course scan failed for %s", course.name)
                        self.progress(f"WARNING {course.name}: scan failed; continuing")
                sync_run.courses_found = summary.courses_found
                sync_run.assessments_found = summary.assessments_found
                sync_run.resources_found = summary.resources_found
                sync_run.changes_found = summary.changes_found
                sync_run.status = "PARTIAL" if failures else "COMPLETED"
                sync_run.error = "; ".join(failures) if failures else None
                sync_run.finished_at = datetime.now(UTC)
                session.commit()
                return summary
            except Exception as exc:
                sync_run.status = "FAILED"
                sync_run.error = str(exc)
                sync_run.finished_at = datetime.now(UTC)
                session.commit()
                raise


def _upsert_course(session: Session, summary: CourseSummary) -> Course:
    url = str(summary.url)
    course = cast(Course | None, session.scalar(select(Course).where(Course.url == url)))
    if course is None:
        course = Course(url=url, name=summary.name)
        session.add(course)
    course.name = summary.name
    course.code = summary.code
    course.term = summary.term
    course.active = True
    course.external_id = _external_id(url)
    session.flush()
    return course


def _external_id(url: str) -> str | None:
    query_id = parse_qs(urlsplit(url).query).get("ou", [None])[0]
    if query_id:
        return query_id
    match = re.search(r"/d2l/home/(\d+)", urlsplit(url).path)
    return match.group(1) if match else None


def _persist_scan(session: Session, course: Course, scan: CourseScanResult) -> tuple[int, int]:
    now = datetime.now(UTC)
    for assessment in scan.assessments:
        existing_assessment = cast(
            Assessment | None,
            session.scalar(
                select(Assessment).where(
                    Assessment.course_id == course.id,
                    Assessment.title == assessment.title,
                    Assessment.due_at == assessment.due_at,
                )
            ),
        )
        if existing_assessment is None:
            existing_assessment = Assessment(
                course_id=course.id,
                title=assessment.title,
                first_seen_at=now,
                last_seen_at=now,
            )
            session.add(existing_assessment)
        existing_assessment.assessment_type = assessment.assessment_type
        existing_assessment.due_at = assessment.due_at
        existing_assessment.weight_percent = assessment.weight_percent
        existing_assessment.description = assessment.description
        existing_assessment.source_url = (
            str(assessment.source_url) if assessment.source_url else None
        )
        existing_assessment.last_seen_at = now
        existing_assessment.status = (
            "OVERDUE" if assessment.due_at and assessment.due_at < now else "UPCOMING"
        )

    for announcement in scan.announcements:
        existing_announcement = cast(
            Announcement | None,
            session.scalar(
                select(Announcement).where(
                    Announcement.course_id == course.id,
                    Announcement.title == announcement.title,
                    Announcement.source_url == str(announcement.source_url or ""),
                )
            ),
        )
        if existing_announcement is None:
            existing_announcement = Announcement(
                course_id=course.id,
                title=announcement.title,
                first_seen_at=now,
                last_seen_at=now,
            )
            session.add(existing_announcement)
        existing_announcement.body = announcement.body
        existing_announcement.published_at = announcement.published_at
        existing_announcement.source_url = (
            str(announcement.source_url) if announcement.source_url else None
        )
        existing_announcement.last_seen_at = now

    for resource in scan.resources:
        extracted_url = str(resource.url) if resource.url else None
        existing_resource = cast(
            Resource | None,
            session.scalar(
                select(Resource).where(
                    Resource.course_id == course.id,
                    Resource.title == resource.title,
                    Resource.url == extracted_url,
                )
            ),
        )
        if existing_resource is None:
            existing_resource = Resource(
                course_id=course.id,
                title=resource.title,
                first_seen_at=now,
            )
            session.add(existing_resource)
        existing_resource.resource_type = resource.resource_type
        existing_resource.url = extracted_url
        existing_resource.uploaded_at = resource.uploaded_at

    course.last_scanned_at = now
    session.flush()
    return len(scan.assessments), len(scan.resources)
