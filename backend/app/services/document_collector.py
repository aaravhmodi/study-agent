"""Save authenticated LEARN resources locally without mutating LMS state."""

import base64
import hashlib
import logging
import re
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.browser.client import BrowserClient, BrowserClientError
from app.config import Settings
from app.models import Course, Resource
from app.services.pdf_text import write_pdf_text_sidecar
from app.services.vision_pdf import VisionPdfTranscriber

logger = logging.getLogger(__name__)


class DocumentCollector:
    def __init__(self, settings: Settings, browser: BrowserClient) -> None:
        self.settings = settings
        self.browser = browser
        self.download_dir = settings.data_dir / "downloads"
        self.vision_pdf = (
            VisionPdfTranscriber(settings)
            if settings.openai_api_key
            else None
        )

    async def collect(self, session: Session, course: Course) -> tuple[int, int]:
        """Download visible course resources; return (saved, failed)."""
        saved = 0
        failed = 0
        # _persist_scan may have removed legacy wrapper rows from the
        # relationship. Query after the flush so deleted ORM instances are
        # not still attempted during this collection pass.
        resources: Iterable[Resource] = session.scalars(
            select(Resource).where(Resource.course_id == course.id)
        ).all()
        for resource in resources:
            if not resource.url or urlsplit(resource.url).scheme not in {"http", "https"}:
                continue
            if _is_video_resource(resource):
                resource.processed = True
                resource.local_path = None
                resource.content_hash = None
                continue
            try:
                # Only text substituted from content_text is saved as .txt;
                # downloaded documents keep the suffix of their actual bytes.
                saved_as_text = False
                if resource.content_text and resource.resource_type == "LINK":
                    content = resource.content_text.encode("utf-8")
                    filename = resource.title
                    content_type = "text/plain; charset=utf-8"
                    saved_as_text = True
                else:
                    downloaded = await self.browser.download_resource(resource.url)
                    if downloaded.skipped:
                        resource.processed = True
                        resource.local_path = None
                        resource.content_hash = None
                        continue
                    downloaded_content = base64.b64decode(
                        downloaded.content_base64, validate=True
                    )
                    content = downloaded_content
                    filename = downloaded.filename
                    content_type = downloaded.content_type
                    if (
                        resource.content_text
                        and resource.resource_type == "PAGE"
                        and content_type.lower().startswith("text/html")
                    ):
                        content = resource.content_text.encode("utf-8")
                        filename = resource.title
                        content_type = "text/plain; charset=utf-8"
                        saved_as_text = True
                if not content:
                    raise ValueError("resource was empty")
                if resource.content_text is None and _is_auth_redirect(
                    downloaded.resolved_url or downloaded.url, downloaded_content
                ):
                    resource.local_path = None
                    resource.content_hash = None
                    raise BrowserClientError("authenticated browser returned a login redirect")
                suffix = ".txt" if saved_as_text else _suffix(
                    filename, content_type, resource.resource_type
                )
                path = self.download_dir / f"{resource.id}_{_safe_name(resource.title)}{suffix}"
                path.parent.mkdir(parents=True, exist_ok=True)
                _remove_previous_file(resource.local_path, path)
                path.write_bytes(content)
                if path.suffix.lower() == ".pdf":
                    # Keep extraction local. The PDF remains the canonical
                    # saved artifact; the sidecar lets indexing use text
                    # without requiring a hosted PDF parser.
                    write_pdf_text_sidecar(path)
                    if course.code == "SYDE 252" and self.vision_pdf is not None:
                        try:
                            self.vision_pdf.transcribe_to_sidecar(path, resource.title)
                        except Exception as exc:
                            logger.warning(
                                "Visual PDF transcription failed for %r (%s)",
                                resource.title,
                                type(exc).__name__,
                            )
                resource.local_path = str(path)
                resource.content_hash = hashlib.sha256(content).hexdigest()
                resource.processed = True
                saved += 1
            except (BrowserClientError, ValueError, OSError) as exc:
                failed += 1
                resource.processed = False
                # Keep the sync alive when one resource is unavailable or too large.
                session.info.setdefault("document_warnings", []).append(
                    f"{resource.title}: {type(exc).__name__}"
                )
                logger.warning(
                    "Could not save course resource %r (%s)",
                    resource.title,
                    type(exc).__name__,
                )
        session.flush()
        return saved, failed


def _suffix(filename: str, content_type: str, resource_type: str) -> str:
    raw_name = Path(filename).name
    match = re.search(r"(\.[a-z0-9]{1,8})$", raw_name, flags=re.IGNORECASE)
    if match:
        return match.group(1).lower()
    mime_suffixes = {
        "application/pdf": ".pdf",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "text/html": ".html",
        "text/plain": ".txt",
    }
    return mime_suffixes.get(content_type.split(";", 1)[0].lower(), {
        "PDF": ".pdf",
        "DOCUMENT": ".docx",
        "SLIDES": ".pptx",
        "PAGE": ".html",
    }.get(resource_type, ".bin"))


def _remove_previous_file(previous: str | None, current: Path) -> None:
    """Delete a resource's earlier download when it is now saved elsewhere.

    A stale file can otherwise sit where the new file's text sidecar belongs
    (e.g. a PDF previously mislabelled as ``.txt``) and be indexed as text.
    """

    if not previous:
        return
    previous_path = Path(previous)
    if previous_path.resolve() != current.resolve():
        previous_path.unlink(missing_ok=True)


def _safe_name(title: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", title).strip("-.")
    return (cleaned or "course-resource")[:100]


def _is_video_resource(resource: Resource) -> bool:
    if resource.resource_type == "VIDEO":
        return True
    searchable = f"{resource.title} {resource.url or ''}"
    return bool(
        re.search(r"\b(video|recording|youtube|panopto)\b", searchable, flags=re.IGNORECASE)
        or re.search(r"\.(?:mp4|webm|m3u8)(?:$|[?#])", searchable, flags=re.IGNORECASE)
    )


def _is_auth_redirect(url: str, content: bytes) -> bool:
    if "/d2l/login" in url.lower() or "sessionexpired" in url.lower():
        return True
    preview = content[:4096].decode("utf-8", errors="ignore").lower()
    return "/d2l/login" in preview or "sessionexpired" in preview
