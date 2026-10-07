"""Save authenticated LEARN resources locally without mutating LMS state."""

import base64
import hashlib
import logging
import re
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app.browser.client import BrowserClient, BrowserClientError
from app.config import Settings
from app.models import Course, Resource
from app.services.pdf_text import write_pdf_text_sidecar

logger = logging.getLogger(__name__)


class DocumentCollector:
    def __init__(self, settings: Settings, browser: BrowserClient) -> None:
        self.settings = settings
        self.browser = browser
        self.download_dir = settings.data_dir / "downloads"

    async def collect(self, session: Session, course: Course) -> tuple[int, int]:
        """Download visible course resources; return (saved, failed)."""
        saved = 0
        failed = 0
        resources: Iterable[Resource] = course.resources
        for resource in resources:
            if not resource.url or urlsplit(resource.url).scheme not in {"http", "https"}:
                continue
            if resource.resource_type == "VIDEO":
                resource.processed = True
                resource.local_path = None
                resource.content_hash = None
                continue
            try:
                if resource.content_text and resource.resource_type == "LINK":
                    content = resource.content_text.encode("utf-8")
                    filename = resource.title
                    content_type = "text/plain; charset=utf-8"
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
                if not content:
                    raise ValueError("resource was empty")
                if resource.content_text is None and _is_auth_redirect(
                    downloaded.resolved_url or downloaded.url, downloaded_content
                ):
                    resource.local_path = None
                    resource.content_hash = None
                    raise BrowserClientError("authenticated browser returned a login redirect")
                suffix = ".txt" if resource.content_text else _suffix(
                    filename, content_type, resource.resource_type
                )
                path = self.download_dir / f"{resource.id}_{_safe_name(resource.title)}{suffix}"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                if path.suffix.lower() == ".pdf":
                    # Keep extraction local. The PDF remains the canonical
                    # saved artifact; the sidecar lets indexing use text
                    # without requiring a hosted PDF parser.
                    write_pdf_text_sidecar(path)
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


def _safe_name(title: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", title).strip("-.")
    return (cleaned or "course-resource")[:100]


def _is_auth_redirect(url: str, content: bytes) -> bool:
    if "/d2l/login" in url.lower() or "sessionexpired" in url.lower():
        return True
    preview = content[:4096].decode("utf-8", errors="ignore").lower()
    return "/d2l/login" in preview or "sessionexpired" in preview
