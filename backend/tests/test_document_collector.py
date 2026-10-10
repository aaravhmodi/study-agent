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


@pytest.mark.asyncio
async def test_each_file_is_announced_as_it_is_fetched(tmp_path: Path) -> None:
    session, course, _resource = _session_with_document(None)
    steps: list[str] = []

    await _collector(tmp_path).collect(session, course, steps.append)

    assert steps == ["SYDE 212: reading 1. Introduction"]


@pytest.mark.asyncio
async def test_an_unchanged_file_keeps_its_saved_copy_and_extracted_text(tmp_path: Path) -> None:
    session, course, resource = _session_with_document(None)
    collector = _collector(tmp_path)
    await collector.collect(session, course)
    pdf = Path(resource.local_path or "")
    # A handwritten PDF's text is an OpenAI transcription, paid for once.
    sidecar = pdf.with_suffix(".txt")
    sidecar.write_text("[OpenAI visual transcription]\nnotes", encoding="utf-8")
    before = (pdf.stat().st_mtime_ns, sidecar.read_text(encoding="utf-8"), resource.content_hash)

    saved, failed = await collector.collect(session, course)

    assert (saved, failed) == (1, 0)
    after = (pdf.stat().st_mtime_ns, sidecar.read_text(encoding="utf-8"), resource.content_hash)
    assert after == before


@pytest.mark.asyncio
async def test_a_changed_file_is_saved_again(tmp_path: Path) -> None:
    session, course, resource = _session_with_document(None)
    collector = _collector(tmp_path)
    await collector.collect(session, course)
    first_hash = resource.content_hash
    pdf = Path(resource.local_path or "")
    pdf.with_suffix(".txt").write_text("text of the old version", encoding="utf-8")

    class NewerBrowser(FakeBrowser):
        async def download_resource(self, url: str) -> BrowserDownloadedResource:
            return BrowserDownloadedResource(
                url=url,
                filename="1. Introduction.pdf",
                content_type="application/pdf",
                content_base64=base64.b64encode(_PDF_BYTES + b"%revised\n").decode("ascii"),
            )

    collector.browser = cast(Any, NewerBrowser())
    await collector.collect(session, course)

    assert resource.content_hash != first_hash
    assert pdf.read_bytes().endswith(b"%revised\n")
