import base64
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from app import models  # noqa: F401
from app.config import Settings
from app.db.database import Base
from app.models import Course, Resource
from app.schemas.browser import BrowserDownloadedResource
from app.services.document_collector import DocumentCollector
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

_PDF_BYTES = b"%PDF-1.7\n%fake pdf body\n"


class FakeBrowser:
    async def download_resource(self, url: str) -> BrowserDownloadedResource:
        return BrowserDownloadedResource(
            url=url,
            filename="1. Introduction.pdf",
            content_type="application/pdf",
            content_base64=base64.b64encode(_PDF_BYTES).decode("ascii"),
        )


def _collector(tmp_path: Path) -> DocumentCollector:
    collector = DocumentCollector(Settings(openai_api_key=None), cast(Any, FakeBrowser()))
    collector.download_dir = tmp_path
    return collector


def _session_with_document(content_text: str | None) -> tuple[Session, Course, Resource]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    course = Course(code="SYDE 212", name="SYDE 212", url="https://learn.example/course")
    session.add(course)
    session.flush()
    resource = Resource(
        course_id=course.id,
        title="1. Introduction",
        resource_type="DOCUMENT",
        url="https://learn.example/d2l/api/le/1/content/topics/1/file",
        content_text=content_text,
        first_seen_at=datetime.now(UTC),
    )
    session.add(resource)
    session.flush()
    return session, course, resource


@pytest.mark.asyncio
async def test_document_with_content_text_keeps_pdf_suffix(tmp_path: Path) -> None:
    session, course, resource = _session_with_document("Topic description from LEARN")

    saved, failed = await _collector(tmp_path).collect(session, course)

    assert (saved, failed) == (1, 0)
    assert resource.local_path is not None
    path = Path(resource.local_path)
    assert path.suffix == ".pdf"
    assert path.read_bytes() == _PDF_BYTES


@pytest.mark.asyncio
async def test_resave_removes_previously_mislabelled_file(tmp_path: Path) -> None:
    session, course, resource = _session_with_document("Topic description from LEARN")
    stale = tmp_path / f"{resource.id}_1.-Introduction.txt"
    stale.write_bytes(_PDF_BYTES)
    resource.local_path = str(stale)

    await _collector(tmp_path).collect(session, course)

    # The stale binary must not survive where the PDF's text sidecar belongs.
    assert not stale.exists()
    assert resource.local_path is not None
    assert Path(resource.local_path).suffix == ".pdf"


class SkippingBrowser:
    """LEARN item over the browser transfer limit."""

    async def download_resource(self, url: str) -> BrowserDownloadedResource:
        return BrowserDownloadedResource(
            url=url,
            filename="textbook.pdf",
            content_type="application/pdf",
            content_base64="",
            skipped=True,
        )


@pytest.mark.asyncio
async def test_too_large_item_keeps_a_hand_imported_copy(tmp_path: Path) -> None:
    session, course, resource = _session_with_document(None)
    imported = tmp_path / "textbook.pdf"
    imported.write_bytes(_PDF_BYTES)
    resource.local_path, resource.content_hash = str(imported), "hash"
    collector = DocumentCollector(Settings(openai_api_key=None), cast(Any, SkippingBrowser()))

    await collector.collect(session, course)

    assert (resource.local_path, resource.content_hash) == (str(imported), "hash")

    imported.unlink()
    await collector.collect(session, course)
    assert (resource.local_path, resource.content_hash) == (None, None)
