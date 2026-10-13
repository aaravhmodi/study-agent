"""Save student-provided PDFs as searchable resources for a course."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from app.config import Settings
from app.models import Course, Resource
from app.services.document_collector import safe_name
from app.services.pdf_text import extract_pdf_text
from app.services.vision_pdf import VisionPdfTranscriber

MAX_PDF_BYTES = 50 * 1024 * 1024
_CHUNK_BYTES = 1024 * 1024


class CoursePdfError(ValueError):
    """The uploaded PDF cannot be saved as searchable course context."""


def save_course_pdf(
    course: Course,
    filename: str,
    content: BinaryIO,
    settings: Settings,
) -> Resource:
    """Copy one PDF into the downloads folder and extract or transcribe its text."""

    source_name = Path(filename).name
    if not source_name or Path(source_name).suffix.lower() != ".pdf":
        raise CoursePdfError("Choose a PDF file.")

    resource_id = str(uuid4())
    title = Path(source_name).stem.strip()[:255] or "Course PDF"
    target = settings.downloads_dir / f"{resource_id}_{safe_name(title)}.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    total = 0
    header = bytearray()
    try:
        with target.open("wb") as destination:
            while chunk := content.read(_CHUNK_BYTES):
                total += len(chunk)
                if total > MAX_PDF_BYTES:
                    raise CoursePdfError("PDFs must be 50 MB or smaller.")
                if len(header) < 5:
                    header.extend(chunk[: 5 - len(header)])
                digest.update(chunk)
                destination.write(chunk)
        if total == 0 or bytes(header) != b"%PDF-":
            raise CoursePdfError("The selected file is empty or is not a valid PDF.")

        extracted = extract_pdf_text(target)
        if extracted:
            target.with_suffix(".txt").write_text(extracted, encoding="utf-8")
        elif settings.openai_api_key:
            VisionPdfTranscriber(settings).transcribe_to_sidecar(target, title)
        else:
            raise CoursePdfError(
                "This PDF has no selectable text and visual transcription is unavailable."
            )
    except Exception:
        target.unlink(missing_ok=True)
        target.with_suffix(".txt").unlink(missing_ok=True)
        raise

    return Resource(
        id=resource_id,
        course_id=course.id,
        title=title,
        description="Added from your computer and made searchable for this course.",
        resource_type="DOCUMENT",
        local_path=str(target),
        first_seen_at=datetime.now(UTC),
        content_hash=digest.hexdigest(),
        processed=True,
    )
