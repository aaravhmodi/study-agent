from pathlib import Path

from app.services import pdf_text


class _Page:
    def __init__(self, text: str) -> None:
        self.text = text

    def extract_text(self) -> str:
        return self.text


class _Reader:
    pages = [_Page("first page"), _Page("second page")]


def test_extract_pdf_text_joins_pages(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(pdf_text, "PdfReader", lambda _path, **_kwargs: _Reader())
    pdf_path = tmp_path / "lecture.pdf"
    pdf_path.write_bytes(b"not a real PDF for this isolated parser test")

    assert pdf_text.extract_pdf_text(pdf_path) == "[Page 1]\nfirst page\n\n[Page 2]\nsecond page"


def test_write_pdf_text_sidecar(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(pdf_text, "PdfReader", lambda _path, **_kwargs: _Reader())
    pdf_path = tmp_path / "lecture.pdf"
    pdf_path.write_bytes(b"placeholder")

    sidecar = pdf_text.write_pdf_text_sidecar(pdf_path)

    assert sidecar == tmp_path / "lecture.txt"
    assert sidecar.read_text(encoding="utf-8") == "[Page 1]\nfirst page\n\n[Page 2]\nsecond page"


def test_shear_stress_question_has_lecture_text_to_search(monkeypatch, tmp_path: Path) -> None:
    class LectureOneReader:
        pages = [
            _Page("Lecture 1: Shear stress is tangential force divided by area. The symbol is tau.")
        ]

    monkeypatch.setattr(pdf_text, "PdfReader", lambda _path, **_kwargs: LectureOneReader())
    pdf_path = tmp_path / "Lecture-1-Intro-Stress.pdf"
    pdf_path.write_bytes(b"placeholder")

    extracted = pdf_text.extract_pdf_text(pdf_path).lower()

    assert "shear stress" in extracted
    assert "tangential force" in extracted
    assert "tau" in extracted


def test_books_are_labelled_with_their_printed_page_numbers() -> None:
    front = ["Title page", "Contents\n1 Introduction 1"]
    body = [f"Balka ISE 1.10 SECTION {n}\ntext of page {n}" for n in range(1, 13)]

    assert pdf_text.printed_page_offset(front + body) == 2
    labels = [page.splitlines()[0] for page in pdf_text._label_pages(front + body)]
    assert labels[:3] == ["[Front matter, PDF page 1]", "[Front matter, PDF page 2]", "[Page 1]"]
    assert labels[-1] == "[Page 12]"


def test_slides_without_printed_numbers_keep_pdf_pages() -> None:
    slides = [f"Part {n} of the lecture\nbullet" for n in range(1, 15)]

    assert pdf_text.printed_page_offset(slides) is None
    assert pdf_text._label_pages(slides)[0].startswith("[Page 1]\n")


def test_a_few_numbered_headers_are_not_enough() -> None:
    pages = [f"Header {n}\nx" for n in range(1, 6)] + [f"Slide {n} title\nx" for n in range(20)]

    assert pdf_text.printed_page_offset(pages) is None
