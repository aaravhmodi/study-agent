import json
from pathlib import Path

import pytest
from app.services.figures import FigureError, extract_figures
from app.services.question_sources import (
    SOURCE_GUIDE,
    SourceDocument,
    SourceResolver,
    parse_source,
)
from app.services.textbook_toc import Chapter

from tests.pdf_fixture import Line, write_pdf


def _problem_set(tmp_path: Path) -> SourceDocument:
    lines: list[Line] = [
        (72, 170, "Problem 2.6"),
        (72, 200, "The voltage drop is the same on every path."),
        (72, 500, "Problem 2.7"),
        (72, 530, "Both current sources are in the same branch."),
    ]
    return SourceDocument(
        resource_id="res-1",
        filename="Problem-Set-2.pdf",
        title="Problem Set 2",
        url="https://learn.example/d2l/le/content/1/viewContent/2/View",
        pdf=write_pdf(tmp_path / "res-1_Problem-Set-2.pdf", [lines]),
    )


def _block(**spec: object) -> str:
    return json.dumps(spec)


def test_a_source_names_the_file_question_and_page_with_a_screenshot(tmp_path: Path) -> None:
    document = _problem_set(tmp_path)

    figure = parse_source(
        _block(file="Problem Set 2.pdf", page=1, question="Problem 2.6", part="(a)"), [document]
    )

    assert figure.kind == "source"
    assert (figure.title, figure.filename) == ("Problem Set 2", "Problem-Set-2.pdf")
    assert figure.question == "Problem 2.6 (a)"
    assert figure.location == "p. 1"
    assert figure.url == document.url
    (image,) = figure.images
    assert image.startswith("/course-resources/res-1/pages/1?top=0.") and "&bottom=0." in image
    assert not figure.whole_page


def test_only_files_the_tutor_was_shown_can_be_cited(tmp_path: Path) -> None:
    documents = [_problem_set(tmp_path)]

    for block in (
        _block(file="Some-Other-Book.pdf", page=1, question="Problem 2.6"),
        _block(file="Problem-Set-2.pdf"),
        _block(page=1, question="Problem 2.6"),
        "not json",
    ):
        with pytest.raises(FigureError):
            parse_source(block, documents)


def test_an_unfound_label_shows_the_cited_page_and_says_so(tmp_path: Path) -> None:
    document = _problem_set(tmp_path)

    figure = parse_source(_block(file="Problem Set 2", page=1, question="Problem 7.1"), [document])

    assert figure.images == ["/course-resources/res-1/pages/1"]
    assert figure.whole_page and figure.location == "p. 1"

    # No label and no such page: the file is still named, without a picture or a page.
    lost = parse_source(_block(file="Problem Set 2", page=9, question="Problem 7.1"), [document])
    assert (lost.images, lost.location, lost.whole_page) == ([], "", False)


def test_a_page_alone_shows_that_page(tmp_path: Path) -> None:
    figure = parse_source(_block(file="Problem-Set-2.pdf", page=1), [_problem_set(tmp_path)])

    assert figure.images == ["/course-resources/res-1/pages/1"]
    assert (figure.question, figure.whole_page) == ("", False)


def test_a_file_without_a_pdf_is_still_referenced() -> None:
    slides = SourceDocument(resource_id="res-2", filename="Tutorial-4.pptx", title="Tutorial 4")

    figure = parse_source(_block(file="Tutorial-4.pptx", page=3, question=7), [slides])

    assert (figure.question, figure.location, figure.images) == ("Question 7", "p. 3", [])


def test_a_book_gives_printed_and_pdf_pages_and_the_chapter(tmp_path: Path) -> None:
    front: list[list[Line]] = [[(72, 80, "Statistics Explained")], [(72, 80, "Contents")]]
    numbered: list[list[Line]] = [
        [(72, 60, f"CHAPTER EXERCISES {number}"), (72, 300, f"3. Question three of page {number}")]
        for number in range(1, 13)
    ]
    book = SourceDocument(
        resource_id="res-3",
        filename="Exercise-manual.pdf",
        title="Exercise manual",
        pdf=write_pdf(tmp_path / "res-3_Exercise-manual.pdf", front + numbered),
        # The passages shown came from printed page 7; the tutor gave no page.
        pages=[7, 8],
        chapters=[
            Chapter(number=1, title="Introduction", first_page=1, last_page=4, sections=[]),
            Chapter(number=2, title="Gathering Data", first_page=5, last_page=None, sections=[]),
        ],
    )

    figure = parse_source(_block(file="Exercise manual", question="Question 3"), [book])

    assert figure.location == "p. 7 (PDF page 9)"
    assert figure.chapter == "Chapter 2: Gathering Data"
    assert figure.images[0].startswith("/course-resources/res-3/pages/9?top=")


def test_the_guide_example_is_a_valid_source_block(tmp_path: Path) -> None:
    document = _problem_set(tmp_path)

    answer, figures = extract_figures(SOURCE_GUIDE, lambda block: parse_source(block, [document]))

    assert [figure.kind for figure in figures] == ["source"]
    assert "```figure\n0\n```" in answer and "```source" not in answer
    # Part of the static instruction prefix, so it stays short.
    assert len(SOURCE_GUIDE.split()) < 180


def test_parts_of_one_question_show_its_screenshot_once(tmp_path: Path) -> None:
    resolve = SourceResolver([_problem_set(tmp_path)])

    first = resolve(_block(file="Problem Set 2", page=1, question="Problem 2.6", part="a"))
    second = resolve(_block(file="Problem Set 2", page=1, question="Problem 2.6", part="b"))
    other = resolve(_block(file="Problem Set 2", page=1, question="Problem 2.7"))

    assert len(first.images) == 1 and len(other.images) == 1
    # The second part is still referenced, by question, file and page.
    assert (second.question, second.location, second.images) == ("Problem 2.6 (b)", "p. 1", [])
