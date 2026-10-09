from types import SimpleNamespace

from app.services.retrieval import (
    Passage,
    cited_files,
    format_passages,
    from_search,
    select_passages,
    tidy,
)

LOREM = " ".join(f"word{i}" for i in range(200))


def _passage(text: str, score: float, file_id: str = "f1", filename: str = "a.txt") -> Passage:
    return Passage(filename=filename, file_id=file_id, text=text, score=score)


def test_tidy_collapses_pdf_whitespace() -> None:
    assert (
        tidy("Section 1.3\r\n\r\nDIRECT   SHEAR \r\n\r\n\r\nSTRESS ")
        == "Section 1.3\nDIRECT SHEAR\nSTRESS"
    )


def test_search_results_become_passages_without_upload_prefixes() -> None:
    result = SimpleNamespace(
        filename="d229e4c8-ea96-464d-873a-f3a3478209f1_Lecture-1.txt",
        file_id="file-1",
        score=0.73,
        content=[SimpleNamespace(text="Shear\r\n\r\nstress"), SimpleNamespace(text="is V/A")],
    )

    (passage,) = from_search([result])

    assert passage.filename == "Lecture-1.txt"
    assert passage.text == "Shear\nstress is V/A"


def test_identical_and_near_identical_passages_are_sent_once() -> None:
    outline = _passage(LOREM, 0.60, "outline-1", "outline.txt")
    same_outline_other_link = _passage(LOREM, 0.60, "outline-2", "outline.txt")
    nearly_same = _passage(LOREM + " extra words at the end", 0.59, "outline-3", "outline.txt")
    lecture = _passage("Bayes theorem relates P(A|B) to P(B|A).", 0.71, "tut-4", "tut4.txt")

    chosen = select_passages(
        [outline, same_outline_other_link, nearly_same, lecture], budget_tokens=5000, max_passages=6
    )

    assert [passage.file_id for passage in chosen] == ["tut-4", "outline-1"]


def test_best_first_capped_per_file_and_by_budget() -> None:
    passages = [
        _passage(f"distinct passage {i} " + "x" * 400 + f" {i}" * 20, 0.9 - i / 100, "lecture")
        for i in range(5)
    ] + [_passage("other file " + "y" * 400, 0.5, "other", "b.txt")]

    chosen = select_passages(passages, budget_tokens=10_000, max_passages=6, per_file=3)
    assert [p.file_id for p in chosen] == ["lecture"] * 3 + ["other"]
    assert chosen[0].score == 0.9

    tight = select_passages(passages, budget_tokens=250, max_passages=6)
    assert sum(p.tokens for p in tight) <= 250 and len(tight) == 2


def test_one_passage_is_always_sent_even_if_over_budget() -> None:
    (only,) = select_passages([_passage("z" * 8000, 0.8)], budget_tokens=100, max_passages=6)

    assert len(only.text) == 400


def test_passages_are_formatted_for_citation() -> None:
    text = format_passages([_passage("V = dM/dx", 0.8, filename="Lecture-7.pdf")])

    assert text == "Course passages (cite by file name):\n\n[Lecture-7.pdf]\nV = dM/dx"
    assert "none matched" in format_passages([])


def test_citations_are_the_files_the_answer_names() -> None:
    passages = [
        _passage("a", 0.9, "f1", "Lecture-1-Intro-Stress.txt"),
        _passage("b", 0.8, "f2", "SYDE286-Syllabus.txt"),
        _passage("c", 0.7, "f1", "Lecture-1-Intro-Stress.txt"),
    ]

    named = cited_files("Shear stress is V/A [Lecture-1-Intro-Stress.txt].", passages)
    unnamed = cited_files("No citations here.", passages)

    assert named == [{"filename": "Lecture-1-Intro-Stress.txt", "file_id": "f1", "kind": "file"}]
    assert [item["filename"] for item in unnamed] == [
        "Lecture-1-Intro-Stress.txt",
        "SYDE286-Syllabus.txt",
    ]
