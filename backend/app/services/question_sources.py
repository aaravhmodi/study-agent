"""Turn the tutor's ```source blocks into references to the student's own course files.

The tutor names the file, page and label of each course question it gives. Only a
file it was shown passages from can be cited, and the label is then looked up in the
local PDF, so the page in the reference is the one the question is really on.
"""

import json
import logging
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.schemas.chat import SourceFigure
from app.services.figures import FigureError
from app.services.pdf_pages import PageRegion, PdfError, find_question, page_region
from app.services.textbook_toc import Chapter

logger = logging.getLogger(__name__)

SOURCE_GUIDE = """\
Course questions: when you give an example, a worked example or a practice question, take \
it from the course passages whenever one fits, and say exactly where it is from: its label, \
file and page, as in "Problem 2.6 (a) in Problem Set 2.pdf, p. 1". Right before the \
question, add a source block so the student sees the original:
```source
{"file": "Problem Set 2.pdf", "page": 1, "question": "Problem 2.6", "part": "a"}
```
"file" is the passage's filename; "page" is the [Page N] marker the question follows; \
"question" is its label as printed ("Example 4.3", "Exercise 7", or "21" for item 21 of a \
numbered list; leave it out for a slide or page that is one unlabelled question); "part" \
names a single sub-part. One block per question, six at most, only for questions you can \
see in the passages. A question you wrote yourself gets no block: call it a new question \
and name the course question it is modelled on, if any.\
"""


class SourceSpec(BaseModel):
    """What the tutor writes in a source block."""

    model_config = ConfigDict(extra="ignore", coerce_numbers_to_str=True)

    file: str = Field(min_length=1, max_length=300)
    page: int | None = Field(default=None, ge=1, le=9999)
    question: str = Field(default="", max_length=60)
    part: str = Field(default="", max_length=12)


class SourceDocument(BaseModel):
    """A course file the tutor was shown passages from."""

    model_config = ConfigDict(extra="forbid")

    resource_id: str
    filename: str
    # The file's name and page on LEARN.
    title: str
    url: str | None = None
    # The saved PDF, when the file is one.
    pdf: Path | None = None
    # Printed pages of the passages shown, used when the tutor gives no page.
    pages: list[int] = Field(default_factory=list)
    chapters: list[Chapter] = Field(default_factory=list)


class SourceResolver:
    """Resolves one answer's source blocks, showing each question's screenshot once."""

    def __init__(self, documents: list[SourceDocument]) -> None:
        self.documents = documents
        self._shown: set[tuple[str, ...]] = set()

    def __call__(self, block: str) -> SourceFigure:
        figure = parse_source(block, self.documents)
        images = tuple(figure.images)
        if images in self._shown:
            # Parts (a) and (b) of one question: the second reference needs no picture.
            return figure.model_copy(update={"images": [], "whole_page": False})
        self._shown.add(images)
        return figure


def parse_source(text: str, documents: list[SourceDocument]) -> SourceFigure:
    """Resolve a source block against the files in hand, or raise FigureError."""

    try:
        spec = SourceSpec.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise FigureError("invalid source block") from exc
    label = " ".join(spec.question.split())
    if not label and spec.page is None:
        raise FigureError("a source needs a question label or a page")
    document = _document(spec.file, documents)
    if document is None:
        raise FigureError("the source is not a file among the passages")
    regions, whole_page = _regions(document, label, spec.page)
    part = spec.part.strip("() ")
    printed = regions[0].printed_page if regions else None
    if label.isdigit():
        # An item of a numbered list reads better with a name: "Question 21".
        label = f"Question {label}"
    # Without a PDF to check, the tutor's page is all there is to go on.
    unchecked = f"p. {spec.page}" if spec.page and not document.pdf else ""
    return SourceFigure(
        title=document.title,
        filename=document.filename,
        question=f"{label} ({part})" if label and part else label,
        location=_location(regions) or unchecked,
        chapter=_chapter(document.chapters, printed) if printed else "",
        url=document.url,
        images=[_image_url(document.resource_id, region) for region in regions],
        whole_page=whole_page,
    )


def _regions(
    document: SourceDocument, label: str, page: int | None
) -> tuple[list[PageRegion], bool]:
    """Where the question is in the PDF, and whether only its page could be found."""

    if document.pdf is None:
        return [], False
    near = page or (document.pages[0] if document.pages else None)
    try:
        found = find_question(document.pdf, label, near) if label else []
        if found:
            return found, False
        whole = page_region(document.pdf, page) if page else None
    except (PdfError, OSError):
        # A PDF that cannot be read still gets its reference, without the picture.
        logger.warning("Could not read a course PDF for a source reference", exc_info=True)
        return [], False
    return ([whole], bool(label)) if whole else ([], False)


def _file_key(name: str) -> str:
    """A name to compare files by: "Problem Set 2" is "Problem-Set-2.pdf"."""

    stem = re.sub(r"\.(?:pdf|txt|docx?|pptx|md|html|tex)$", "", name.strip().lower())
    return " ".join(re.split(r"[\s_-]+", stem)).strip()


def _document(name: str, documents: list[SourceDocument]) -> SourceDocument | None:
    key = _file_key(name)
    for document in documents:
        if key and key in {_file_key(document.filename), _file_key(document.title)}:
            return document
    return None


def _location(regions: list[PageRegion]) -> str:
    if not regions:
        return ""
    first, last = regions[0], regions[-1]
    if first.landscape:
        return f"slide {first.pdf_page}"
    several = last.pdf_page != first.pdf_page
    pdf_pages = (
        f"PDF pages {first.pdf_page}-{last.pdf_page}" if several else f"PDF page {first.pdf_page}"
    )
    if first.printed_page is None:
        return pdf_pages
    printed = (
        f"pp. {first.printed_page}-{last.printed_page}" if several else f"p. {first.printed_page}"
    )
    # Books number their pages after the front matter; give both to turn to either.
    return printed if first.printed_page == first.pdf_page else f"{printed} ({pdf_pages})"


def _chapter(chapters: list[Chapter], printed_page: int) -> str:
    for chapter in chapters:
        if chapter.first_page <= printed_page and (
            chapter.last_page is None or printed_page <= chapter.last_page
        ):
            return f"Chapter {chapter.number}: {chapter.title}"
    return ""


def _image_url(resource_id: str, region: PageRegion) -> str:
    url = f"/course-resources/{resource_id}/pages/{region.pdf_page}"
    return url if region.whole else f"{url}?top={region.top:.3f}&bottom={region.bottom:.3f}"
