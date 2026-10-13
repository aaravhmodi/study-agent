import io
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app.models import Course
from app.services.course_upload import CoursePdfError, save_course_pdf

from tests.pdf_fixture import write_pdf


def settings(folder: Path) -> Any:
    # Only where files go and whether pictures of pages can be transcribed are read.
    return SimpleNamespace(downloads_dir=folder, openai_api_key=None)


COURSE = Course(id="course-286", name="SYDE 286 - Fall 2026", code="SYDE 286", url="https://x")


def test_a_pdf_with_text_is_saved_beside_its_text_for_the_course(tmp_path: Path) -> None:
    source = write_pdf(tmp_path / "source.pdf", [[(72, 72, "Torsion formula: tau = T r / J")]])

    with source.open("rb") as content:
        resource = save_course_pdf(COURSE, "My Strain Notes.pdf", content, settings(tmp_path / "d"))

    saved = Path(resource.local_path or "")
    assert saved.parent == tmp_path / "d" and saved.read_bytes() == source.read_bytes()
    assert "Torsion formula" in saved.with_suffix(".txt").read_text(encoding="utf-8")
    assert (resource.course_id, resource.title, resource.resource_type, resource.processed) == (
        "course-286",
        "My Strain Notes",
        "DOCUMENT",
        True,
    )


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("notes.docx", b"%PDF-1.4 really", "Choose a PDF file."),
        ("notes.pdf", b"", "The selected file is empty or is not a valid PDF."),
        (
            "notes.pdf",
            b"<html>not a pdf</html>",
            "The selected file is empty or is not a valid PDF.",
        ),
    ],
)
def test_anything_that_isnt_a_pdf_is_refused_and_nothing_is_left_behind(
    tmp_path: Path, name: str, content: bytes, message: str
) -> None:
    with pytest.raises(CoursePdfError, match=message):
        save_course_pdf(COURSE, name, io.BytesIO(content), settings(tmp_path))

    assert list(tmp_path.iterdir()) == []


def test_a_scan_with_no_text_needs_transcription_to_be_available(tmp_path: Path) -> None:
    blank = write_pdf(tmp_path / "scan.pdf", [[]])

    with blank.open("rb") as content, pytest.raises(CoursePdfError, match="no selectable text"):
        save_course_pdf(COURSE, "scan.pdf", content, settings(tmp_path / "d"))

    assert list((tmp_path / "d").iterdir()) == []
