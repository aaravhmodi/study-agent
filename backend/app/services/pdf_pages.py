"""Find a question in a saved course PDF and render it for the dashboard."""

import re
import threading
from collections.abc import Sequence
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any, NamedTuple

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
from PIL import Image, ImageChops
from pydantic import BaseModel, ConfigDict, Field

from app.services.pdf_text import printed_page_offset

MAX_PAGE_PIXELS = 2200
PAGE_SCALE = 2.0
# Pages read closely for a label, nearest the cited page first.
_MAX_CANDIDATE_PAGES = 12
# A cited page can be off by the length of a long question. Further away, the same
# label belongs to another chapter's question.
_NEARBY_PAGES = 3
# White space kept around a cropped question, in pixels.
_TRIM_MARGIN = 24
# Labels of one list start at the same indent; allow this much drift, in PDF points.
_INDENT_TOLERANCE = 4.0
# Space kept above a label's first line, as a fraction of the page height. A question
# ends this far above the next label too, which clears a shaded heading bar.
_PAD = 0.012
# Running headers sit above this fraction of the page; text below it is the page's content.
_HEADER_ZONE = 0.08

# PDFium is not thread-safe, and the dashboard asks for several images at once.
_PDFIUM = threading.Lock()

# Raised when a PDF cannot be opened or read.
PdfError = pdfium.PdfiumError

_NUMBER = r"\d+(?:[.\-]\d+)*"
_KINDS = r"practice\s+problem|sample\s+problem|problem|example|exercise|question|quiz|q"
# "Problem 2.6", "Example 4.3:", "Q3." at the start of a line.
_EXPLICIT = re.compile(rf"^({_KINDS})\s*\.?\s*#?\s*({_NUMBER})(?!\d)", re.IGNORECASE)
# "21." or "(4)" at the start of a line: an item of a numbered exercise list.
_BARE = re.compile(r"^\(?(\d{1,3})[.)](?:\s|$)")
_LABEL = re.compile(rf"^\s*([a-z][a-z .]*?)?\s*#?\s*({_NUMBER})", re.IGNORECASE)
# Names for a numbered question that documents and the tutor use interchangeably.
_GENERIC = {"question", "problem", "exercise", "practice problem"}


class TextLine(NamedTuple):
    text: str
    # Where the line's first character sits: PDF points from the left edge of the
    # page, and the fraction of the page height from its top.
    left: float
    top: float


class PageRegion(BaseModel):
    """A horizontal band of one PDF page, as fractions of its height from the top."""

    model_config = ConfigDict(extra="forbid")

    pdf_page: int = Field(ge=1)
    printed_page: int | None = None
    top: float = Field(default=0.0, ge=0, le=1)
    bottom: float = Field(default=1.0, ge=0, le=1)
    # Slides are shown whole, and cited by slide rather than page.
    landscape: bool = False

    @property
    def whole(self) -> bool:
        return self.top <= 0 and self.bottom >= 1


class QuestionSpan(NamedTuple):
    top: float
    # None when the question runs to the end of the page.
    bottom: float | None
    # Labelled by a bare number ("21."), as in a numbered exercise list.
    bare: bool


class _Mark(NamedTuple):
    """A line that starts like a question label."""

    line: int
    left: float
    top: float
    kind: str  # "" for a bare number
    number: str


def parse_label(label: str) -> tuple[str, str] | None:
    """("problem", "2.6") from "Problem 2.6 (a)"; the kind is "" for a bare "21"."""

    match = _LABEL.match(label)
    if not match:
        return None
    return _kind(match.group(1) or ""), match.group(2)


def question_span(lines: Sequence[TextLine], label: str) -> QuestionSpan | None:
    """Where a labelled question starts and ends on a page, as fractions of its height."""

    wanted = parse_label(label)
    if wanted is None:
        return None
    marks = _marks(lines)
    chosen = _pick(marks, *wanted)
    if chosen is None:
        return None
    following = _following(marks, chosen)
    top = max(chosen.top - _PAD, 0.0)
    bottom = max(following.top - _PAD, top) if following else None
    return QuestionSpan(top, bottom, bare=not chosen.kind)


def continuation(lines: Sequence[TextLine], bare: bool) -> float | None:
    """How far down the next page a question continues: up to that page's first label.

    None when the page has no such label, or nothing but a running header above it.
    """

    marks = [mark for mark in _marks(lines) if (not mark.kind) == bare]
    if not marks:
        return None
    indent = min(mark.left for mark in marks)
    first = next(mark for mark in marks if mark.left <= indent + _INDENT_TOLERANCE)
    if not any(_HEADER_ZONE < line.top < first.top - _PAD for line in lines):
        return None
    return first.top - _PAD


def find_question(path: Path, label: str, near_page: int | None = None) -> list[PageRegion]:
    """The part of the PDF showing a labelled question: one region, or two if it runs on.

    Labels repeat (every chapter has a question 3), so only pages around the printed
    page ``near_page`` are searched when it is given. Empty when the label does not
    start a line there. Raises PdfError or OSError when the PDF cannot be read.
    """

    wanted = parse_label(label)
    if wanted is None:
        return []
    texts, offset = _document(str(path), path.stat().st_mtime_ns)
    # Cheap first pass over the whole document: a line that starts with the number.
    starts = re.compile(
        rf"^[ \t]*(?:(?:{_KINDS})\s*\.?\s*#?\s*|\()?{re.escape(wanted[1])}(?!\d)",
        re.IGNORECASE | re.MULTILINE,
    )
    pages = [number for number, text in enumerate(texts, 1) if starts.search(text)]
    if near_page:
        hint = near_page + offset
        pages = [number for number in pages if abs(number - hint) <= _NEARBY_PAGES]
        pages.sort(key=lambda number: (abs(number - hint), number))
    with _PDFIUM, pdfium.PdfDocument(path) as document:
        for number in pages[:_MAX_CANDIDATE_PAGES]:
            page = document[number - 1]
            try:
                span = question_span(_lines(page), label)
                if span is None:
                    continue
                region = _region(page, number, offset)
                if region.landscape or page.get_rotation():
                    return [region]
                found = [region.model_copy(update={"top": span.top, "bottom": span.bottom or 1.0})]
                if span.bottom is None and number < len(document):
                    found += _continued(document, number + 1, offset, span.bare)
                return found
            finally:
                page.close()
    return []


def page_region(path: Path, printed_page: int) -> PageRegion | None:
    """The whole page a printed page number refers to, or None when out of range."""

    texts, offset = _document(str(path), path.stat().st_mtime_ns)
    number = printed_page + offset
    if not 1 <= number <= len(texts):
        return None
    with _PDFIUM, pdfium.PdfDocument(path) as document:
        page = document[number - 1]
        try:
            return _region(page, number, offset)
        finally:
            page.close()


def render_pdf_page(
    path: Path, page_number: int, top: float = 0.0, bottom: float = 1.0
) -> bytes | None:
    """Return a one-based PDF page (or a band of it) as PNG, or None when out of range."""

    with _PDFIUM, pdfium.PdfDocument(path) as document:
        if page_number < 1 or page_number > len(document):
            return None
        page = document[page_number - 1]
        try:
            width, height = page.get_size()
            scale = min(PAGE_SCALE, MAX_PAGE_PIXELS / max(width, height))
            cropped = top > 0 or bottom < 1
            # The crop is what to cut off each side: (left, bottom, right, top).
            crop = (0, (1 - bottom) * height, 0, top * height) if cropped else (0, 0, 0, 0)
            bitmap = page.render(scale=scale, crop=crop, fill_color=(255, 255, 255, 255))
            image = bitmap.to_pil().convert("RGB")
        finally:
            page.close()
    if cropped:
        image = _trim(image)
    output = BytesIO()
    image.save(output, format="PNG")
    image.close()
    return output.getvalue()


def _kind(text: str) -> str:
    kind = " ".join(text.lower().replace(".", " ").split())
    return "question" if kind == "q" else kind


def _marks(lines: Sequence[TextLine]) -> list[_Mark]:
    marks: list[_Mark] = []
    for index, line in enumerate(lines):
        explicit = _EXPLICIT.match(line.text)
        bare = None if explicit else _BARE.match(line.text)
        if explicit:
            kind, number = _kind(explicit.group(1)), explicit.group(2)
            marks.append(_Mark(index, line.left, line.top, kind, number))
        elif bare:
            marks.append(_Mark(index, line.left, line.top, "", bare.group(1)))
    return marks


def _pick(marks: list[_Mark], kind: str, number: str) -> _Mark | None:
    """The line that starts the wanted question, not a later mention of it.

    A cross-reference ("see Question 21") can wrap to the start of a line, but it is
    indented with the text, so the leftmost match is the label.
    """

    numbered = [mark for mark in marks if mark.number == number]
    # "Question 4" can be printed as "Exercise 4" or "4."; an example is only an example.
    loose = not kind or kind in _GENERIC
    exact = [
        mark
        for mark in numbered
        if mark.kind == kind or (loose and not mark.kind) or (not kind and mark.kind in _GENERIC)
    ]
    pool = exact or [mark for mark in numbered if loose and mark.kind in _GENERIC]
    if not pool:
        return None
    indent = min(mark.left for mark in pool)
    leftmost = [mark for mark in pool if mark.left <= indent + _INDENT_TOLERANCE]
    return min(leftmost, key=lambda mark: (not mark.kind, mark.line))


def _following(marks: list[_Mark], chosen: _Mark) -> _Mark | None:
    """The next label of the same list: the same form, at the same indent."""

    for mark in marks:
        if (
            mark.line > chosen.line
            and bool(mark.kind) == bool(chosen.kind)
            and abs(mark.left - chosen.left) <= _INDENT_TOLERANCE
        ):
            return mark
    return None


def _continued(document: Any, number: int, offset: int, bare: bool) -> list[PageRegion]:
    page = document[number - 1]
    try:
        bottom = continuation(_lines(page), bare)
        if bottom is None or page.get_rotation():
            return []
        return [_region(page, number, offset).model_copy(update={"bottom": bottom})]
    finally:
        page.close()


def _region(page: Any, number: int, offset: int) -> PageRegion:
    width, height = page.get_size()
    printed = number - offset
    return PageRegion(
        pdf_page=number,
        printed_page=printed if printed >= 1 else None,
        landscape=width > height,
    )


def _lines(page: Any) -> list[TextLine]:
    """Each line of text on a page with the position of its first character."""

    left_edge, bottom_edge, _right, top_edge = page.get_bbox()
    height = (top_edge - bottom_edge) or 1.0
    textpage = page.get_textpage()
    try:
        # Read character by character: indexes into the page's joined text can drift
        # from PDFium's own, which the character boxes are looked up by.
        count = textpage.count_chars()
        chars = [chr(pdfium_raw.FPDFText_GetUnicode(textpage, index)) for index in range(count)]
        lines: list[TextLine] = []
        start = 0
        for end in range(count + 1):
            if end < count and chars[end] not in "\r\n":
                continue
            first = next((i for i in range(start, end) if not chars[i].isspace()), None)
            if first is not None:
                box_left, _box_bottom, _box_right, box_top = textpage.get_charbox(first)
                lines.append(
                    TextLine(
                        text="".join(chars[first:end]).strip(),
                        left=box_left - left_edge,
                        top=min(max((top_edge - box_top) / height, 0.0), 1.0),
                    )
                )
            start = end + 1
        return lines
    finally:
        textpage.close()


@lru_cache(maxsize=8)
def _document(path: str, _modified: int) -> tuple[tuple[str, ...], int]:
    """Each page's text, and how far PDF page numbers run ahead of the printed ones."""

    texts: list[str] = []
    with _PDFIUM, pdfium.PdfDocument(path) as document:
        for index in range(len(document)):
            page = document[index]
            textpage = page.get_textpage()
            try:
                texts.append(textpage.get_text_range().strip())
            finally:
                textpage.close()
                page.close()
    return tuple(texts), printed_page_offset(texts) or 0


def _trim(image: Image.Image) -> Image.Image:
    """Cut the white space around a cropped question, keeping a small margin."""

    blank = Image.new("RGB", image.size, (255, 255, 255))
    box = ImageChops.difference(image, blank).getbbox()
    if box is None:
        return image
    left, upper, right, lower = box
    return image.crop(
        (
            max(left - _TRIM_MARGIN, 0),
            max(upper - _TRIM_MARGIN, 0),
            min(right + _TRIM_MARGIN, image.width),
            min(lower + _TRIM_MARGIN, image.height),
        )
    )
