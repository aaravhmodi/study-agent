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
