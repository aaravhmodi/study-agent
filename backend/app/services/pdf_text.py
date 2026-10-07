"""Extract text from downloaded PDFs without sending the document anywhere."""

import logging
from pathlib import Path

from pypdf import PdfReader

_PYPDF_LOGGERS = (
    logging.getLogger("pypdf"),
    logging.getLogger("pypdf._reader"),
)


def extract_pdf_text(path: Path) -> str:
    """Return normalized text from a PDF, or an empty string for image-only PDFs."""

    previous_levels = [logger.level for logger in _PYPDF_LOGGERS]
    for logger in _PYPDF_LOGGERS:
        logger.setLevel(logging.ERROR)
    try:
        # Brightspace materials occasionally contain imperfect xref tables.
        # pypdf can recover these when strict parsing is disabled.
        reader = PdfReader(str(path), strict=False)
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except Exception:
        # A malformed, encrypted, or unsupported PDF should not prevent the
        # original downloaded file from being saved and cited.
        return ""
    finally:
        for logger, previous_level in zip(_PYPDF_LOGGERS, previous_levels, strict=True):
            logger.setLevel(previous_level)
    return "\n\n".join(page for page in pages if page).strip()


def write_pdf_text_sidecar(path: Path) -> Path | None:
    """Write extracted text beside a PDF and return the sidecar path."""

    text = extract_pdf_text(path)
    if not text:
        return None
    sidecar = path.with_suffix(".txt")
    sidecar.write_text(text, encoding="utf-8")
    return sidecar
