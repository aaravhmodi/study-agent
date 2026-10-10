from datetime import UTC, datetime, timedelta

import pytest
from app import main
from app.browser.client import MockBrowserClient
from app.config import Settings
from app.db.database import Base
from app.models import SyncRun
from app.schemas.sync import BrowserTestResult
from app.services import sync_service
from app.services.sync_service import SyncService
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


@pytest.fixture()
def sessions() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _run(hours_ago: int, status: str, finished: bool = True) -> SyncRun:
    started = NOW - timedelta(hours=hours_ago)
    return SyncRun(
        started_at=started,
        finished_at=started + timedelta(minutes=10) if finished else None,
        status=status,
        courses_found=6 if status == "COMPLETED" else 0,
    )


def test_the_dashboard_shows_the_last_sync_that_brought_anything_in(
    sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    with sessions() as session:
        session.add_all(
            [
                _run(50, "COMPLETED"),
                # Later attempts that got nowhere: not signed in, then cut off by a restart.
                _run(3, "FAILED"),
                _run(1, "RUNNING", finished=False),
            ]
        )
        session.commit()
    monkeypatch.setattr(main, "SessionLocal", sessions)
    monkeypatch.setattr(main, "ensure_schema", lambda: None)
    monkeypatch.setattr(main, "get_settings", lambda: Settings(_env_file=None))

    last_sync = TestClient(main.app).get("/api/dashboard").json()["last_sync"]

    assert (last_sync["status"], last_sync["courses_found"]) == ("COMPLETED", 6)
    assert last_sync["finished_at"] is not None


class SignedOutBrowser(MockBrowserClient):
    async def test_connection(self) -> BrowserTestResult:
        return BrowserTestResult(
            browser_connected=True,
            learn_reachable=False,
            url="https://adfs.example/adfs/ls/",
            title="Sign In",
            message="",
        )


@pytest.mark.asyncio
async def test_a_sync_cut_off_by_a_restart_is_no_longer_called_running(
    sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    with sessions() as session:
        session.add(_run(1, "RUNNING", finished=False))
        session.commit()
    monkeypatch.setattr(sync_service, "SessionLocal", sessions)
    monkeypatch.setattr(sync_service, "ensure_schema", lambda: None)

    with pytest.raises(RuntimeError, match="not authenticated"):
        await SyncService(Settings(_env_file=None), browser=SignedOutBrowser()).run()

    with sessions() as session:
        earlier, latest = session.scalars(select(SyncRun).order_by(SyncRun.started_at)).all()
    assert (earlier.status, earlier.error) == ("INTERRUPTED", "Stopped before it finished.")
    assert earlier.finished_at is not None
    assert latest.status == "FAILED"


def test_an_announcement_linked_two_ways_is_read_and_saved_once(
    sessions: sessionmaker[Session],
) -> None:
    from app.agents.course_agent import _extract_announcements
    from app.models import Announcement, Course
    from app.schemas.browser import BrowserPageSnapshot, PageLink
    from app.schemas.extraction import CourseScanResult
    from app.services.sync_service import _persist_scan

    page = "https://learn.uwaterloo.ca/d2l/le/news/1292394/1146084/view"
    listing = BrowserPageSnapshot(
        url="https://learn.uwaterloo.ca/d2l/lms/news/main.d2l",
        links=[PageLink(text="Midterm Details", href=f"{page}?ou=1292394")],
    )
    home = BrowserPageSnapshot(
        url="https://learn.uwaterloo.ca/d2l/home/1292394",
        links=[PageLink(text="Midterm Details", href=page)],
    )
    detail = BrowserPageSnapshot(url=page, text="The midterm covers chapters 1 to 6.")

    (announcement,) = _extract_announcements([listing, home, detail])
    assert str(announcement.source_url) == page
    assert announcement.body == "The midterm covers chapters 1 to 6."

    with sessions() as session:
        course = Course(code="SYDE 286", name="SYDE 286", url="https://learn.example/286")
        session.add(course)
        session.flush()
        # An earlier sync saved the same announcement under its ?ou= address too.
        session.add(
            Announcement(
                course_id=course.id,
                title="Midterm Details",
                source_url=f"{page}?ou=1292394",
                first_seen_at=NOW,
                last_seen_at=NOW,
            )
        )
        session.flush()

        _persist_scan(
            session, course, CourseScanResult(course_name="x", announcements=[announcement])
        )
        session.flush()

        saved = session.scalars(select(Announcement)).all()
        assert [row.source_url for row in saved] == [page]
