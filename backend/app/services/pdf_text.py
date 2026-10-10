"""Extract text from downloaded PDFs without sending the document anywhere."""

import logging
import re
from bisect import bisect_right
from collections import Counter
from functools import lru_cache
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
    return "\n\n".join(_label_pages(pages)).strip()


# A printed page number at the end of a page's first line ("... TYPES OF SAMPLING 12").
_HEADER_NUMBER = re.compile(r"(?:^|\s)(\d{1,4})\s*$")


def printed_page_offset(pages: list[str]) -> int | None:
    """How far PDF page numbers run ahead of the printed ones, if the document prints them.

    Books number their pages after the front matter, so PDF page 20 can be page 12.
    Returns None unless most pages agree, as slides and handouts rarely print numbers.
    """

    offsets: Counter[int] = Counter()
    for index, text in enumerate(pages, 1):
        first = next((line for line in text.splitlines() if line.strip()), "")
        match = _HEADER_NUMBER.search(first)
        if match:
            offsets[index - int(match.group(1))] += 1
    if not offsets:
        return None
    offset, agreeing = offsets.most_common(1)[0]
    with_text = sum(1 for text in pages if text)
    return offset if agreeing >= 10 and agreeing >= 0.6 * with_text else None


def _label_pages(pages: list[str]) -> list[str]:
    """Head each page so answers can cite it ("[course text.pdf, p. 87]").

    Pages are labelled with the number printed on them when the document has one,
    so a citation matches the page a student turns to in the book.
    """

    offset = printed_page_offset(pages) or 0
    labelled: list[str] = []
    for index, text in enumerate(pages, 1):
        if not text:
            continue
        printed = index - offset
        label = f"[Page {printed}]" if printed >= 1 else f"[Front matter, PDF page {index}]"
        labelled.append(f"{label}\n{text}")
    return labelled


def write_pdf_text_sidecar(path: Path) -> Path | None:
    """Write extracted text beside a PDF and return the sidecar path."""

    text = extract_pdf_text(path)
    if not text:
        return None
    sidecar = path.with_suffix(".txt")
    sidecar.write_text(text, encoding="utf-8")
    return sidecar


def refresh_pdf_text_sidecar(path: Path) -> bool:
    """Re-extract a PDF whose sidecar predates page labels; True when it was rewritten.

    Every sidecar written since starts with a bracketed line: a page label, or the
    marker of a visual transcription, which must not be replaced by plain extraction.
    """

    sidecar = path.with_suffix(".txt")
    try:
        with sidecar.open(encoding="utf-8", errors="ignore") as handle:
            start = handle.read(200).lstrip()
    except OSError:
        return False
    if not start or start.startswith("["):
        return False
    text = extract_pdf_text(path)
    if not text:
        return False
    sidecar.write_text(text, encoding="utf-8")
    return True


_PAGE_LABEL = re.compile(r"\[Page (\d+)\]")
# Enough of a passage to find it once in a whole book.
_PROBE_CHARS = 120


def passage_pages(sidecar: Path, passage: str) -> list[int]:
    """Printed pages a retrieved passage covers, found by locating it in the sidecar.

    Search returns a slice of the uploaded text, and a slice that starts mid-page
    carries no label for the page it starts on.
    """

    try:
        text, positions, numbers = _labelled_text(str(sidecar), sidecar.stat().st_mtime_ns)
    except OSError:
        return []
    wanted = " ".join(passage.split())
    if not wanted or not positions:
        return []
    start = text.find(wanted)
    if start < 0:
        # The sidecar may have gained labels since it was indexed; a short probe still matches.
        start = text.find(wanted[:_PROBE_CHARS])
    if start < 0:
        tail = text.find(wanted[-_PROBE_CHARS:])
        if tail < 0:
            return []
        start = max(tail + _PROBE_CHARS - len(wanted), 0)
    first = bisect_right(positions, start) - 1
    last = bisect_right(positions, start + len(wanted) - 1) - 1
    return sorted(set(numbers[max(first, 0) : last + 1])) if last >= 0 else []


@lru_cache(maxsize=16)
def _labelled_text(sidecar: str, _modified: int) -> tuple[str, list[int], list[int]]:
    """A sidecar's text on one line, with where each page label sits and its number."""

    text = " ".join(Path(sidecar).read_text(encoding="utf-8", errors="ignore").split())
    labels = list(_PAGE_LABEL.finditer(text))
    return text, [label.start() for label in labels], [int(label.group(1)) for label in labels]
