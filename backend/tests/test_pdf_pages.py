from io import BytesIO
from pathlib import Path

from app.services.pdf_pages import (
    TextLine,
    continuation,
    find_question,
    page_region,
    parse_label,
    question_span,
    render_pdf_page,
)
from PIL import Image

from tests.pdf_fixture import Line, write_pdf

# A page of a numbered exercise list: item numbers hang left of the text, and a
# mention of question 21 has wrapped to the start of a line inside question 22.
EXERCISES = [
    TextLine("Balka ISE 1.09 2.5. CHAPTER EXERCISES 10", 26, 0.06),
    TextLine("20. Suppose a very conservative media outlet", 95, 0.12),
    TextLine("21. A study investigated the effect of aspirin", 95, 0.37),
    TextLine("(a) Is this an experiment?", 117, 0.44),
    TextLine("22. Consider again the information in", 95, 0.62),
    TextLine("Question 21? Suppose that instead", 134, 0.66),
    TextLine("23. Researchers wish to investigate", 95, 0.78),
]


def test_labels_are_read_as_a_kind_and_a_number() -> None:
    assert parse_label("Problem 2.6 (a)") == ("problem", "2.6")
    assert parse_label("Q3") == ("question", "3")
    assert parse_label("Practice Problem 4.1") == ("practice problem", "4.1")
    assert parse_label("21") == ("", "21")
    assert parse_label("the aspirin question") is None


def test_a_numbered_item_is_found_not_a_later_mention_of_it() -> None:
    span = question_span(EXERCISES, "Question 21")

    assert span is not None and span.bare
    # From just above item 21 to just above item 22, skipping the wrapped mention.
    assert 0.35 < span.top < 0.37
    assert span.bottom is not None and 0.60 < span.bottom < 0.62


def test_the_last_question_on_a_page_runs_to_its_end() -> None:
    span = question_span(EXERCISES, "23")

    assert span is not None and span.bottom is None


def test_a_heading_beats_a_solution_step_with_the_same_number() -> None:
    lines = [
        TextLine("Question 1", 48, 0.10),
        TextLine("2. Substitute the reactions.", 48, 0.30),
        TextLine("Question 2", 48, 0.50),
        TextLine("1. Take moments about A.", 48, 0.60),
        TextLine("Question 3", 48, 0.80),
    ]

    span = question_span(lines, "Question 2")

    assert span is not None and not span.bare
    # It ends at the next heading, not at the numbered step inside it.
    assert 0.48 < span.top < 0.50 and span.bottom is not None and span.bottom > 0.78


def test_question_names_are_interchangeable_but_an_example_is_an_example() -> None:
    lines = [TextLine("Exercise 4. A fair coin", 47, 0.2), TextLine("Example 5", 47, 0.6)]

    assert question_span(lines, "Question 4") is not None
    assert question_span(lines, "4") is not None
    assert question_span(lines, "Example 4") is None
    assert question_span(lines, "Problem 5") is None
    assert question_span(lines, "Exercise 9") is None


def test_a_question_continues_to_the_next_pages_first_label() -> None:
    carried_over = [
        TextLine("2.5. CHAPTER EXERCISES 11", 26, 0.06),
        TextLine("down on a table. The 100 tiles", 110, 0.12),
        TextLine("24. A new question", 95, 0.40),
    ]
    starts_fresh = [
        TextLine("SYDE 286 - F2025", 48, 0.04),
        TextLine("Question 3: (4 marks)", 48, 0.15),
    ]

    bottom = continuation(carried_over, bare=True)
    assert bottom is not None and 0.38 < bottom < 0.40
    # Only a running header sits above the label, so nothing was carried over.
    assert continuation(starts_fresh, bare=False) is None
    assert continuation([TextLine("no labels here", 48, 0.3)], bare=True) is None


def _problem_set(tmp_path: Path) -> Path:
    first: list[Line] = [
        (72, 80, "Suggested Problems - Solutions"),
        (72, 170, "Problem 2.6"),
        (72, 200, "The voltage drop is the same on every path."),
        (72, 500, "Problem 2.7"),
        (72, 530, "Both current sources are in the same branch."),
    ]
    second: list[Line] = [
        (72, 110, "so their values must be the same."),
        (72, 300, "Problem 2.8"),
        (72, 330, "The interconnection is valid."),
    ]
    return write_pdf(tmp_path / "problem-set.pdf", [first, second])


def test_a_question_is_found_in_a_pdf_between_its_label_and_the_next(tmp_path: Path) -> None:
    (region,) = find_question(_problem_set(tmp_path), "Problem 2.6")

    assert (region.pdf_page, region.printed_page) == (1, 1)
    assert 0.18 < region.top < 0.21 and 0.60 < region.bottom < 0.63
    assert not region.whole and not region.landscape


def test_a_question_cut_by_the_page_break_carries_onto_the_next_page(tmp_path: Path) -> None:
    first, second = find_question(_problem_set(tmp_path), "Problem 2.7")

    assert (first.pdf_page, first.bottom) == (1, 1.0)
    assert (second.pdf_page, second.top) == (2, 0.0) and 0.35 < second.bottom < 0.38


def test_an_unknown_label_finds_nothing(tmp_path: Path) -> None:
    assert find_question(_problem_set(tmp_path), "Problem 9.9") == []
    assert find_question(_problem_set(tmp_path), "the second one") == []


def _book(tmp_path: Path) -> Path:
    """Two unnumbered front pages, then pages printed 1 to 12, each with a question 3."""

    front: list[list[Line]] = [[(72, 80, "Statistics Explained")], [(72, 80, "Contents")]]
    numbered: list[list[Line]] = [
        [(72, 60, f"CHAPTER EXERCISES {number}"), (72, 300, f"3. Question three of page {number}")]
        for number in range(1, 13)
    ]
    return write_pdf(tmp_path / "book.pdf", front + numbered)


def test_a_repeated_label_is_taken_from_the_cited_printed_page(tmp_path: Path) -> None:
    book = _book(tmp_path)

    (region,) = find_question(book, "Question 3", near_page=7)
    assert (region.pdf_page, region.printed_page) == (9, 7)
    # A label that only exists chapters away is someone else's question 3.
    assert find_question(book, "Problem 2.6", near_page=7) == []

    whole = page_region(book, 7)
    assert whole is not None and (whole.pdf_page, whole.whole) == (9, True)
    assert page_region(book, 40) is None


def test_a_slide_is_shown_whole(tmp_path: Path) -> None:
    deck = write_pdf(
        tmp_path / "lecture.pdf",
        [[(40, 60, "Stress")], [(44, 230, "Example 2"), (44, 300, "Find the normal stress.")]],
        size=(960, 540),
    )

    (region,) = find_question(deck, "Example 2")

    assert (region.pdf_page, region.whole, region.landscape) == (2, True, True)


def test_a_page_band_is_rendered_as_a_smaller_trimmed_image(tmp_path: Path) -> None:
    path = _problem_set(tmp_path)
    (region,) = find_question(path, "Problem 2.6")

    page = Image.open(BytesIO(render_pdf_page(path, 1) or b""))
    crop = Image.open(BytesIO(render_pdf_page(path, 1, region.top, region.bottom) or b""))

    assert page.format == crop.format == "PNG"
    assert page.size == (1224, 1584)
    # Just the two lines of the question, with the page's white margins cut away.
    assert crop.height < page.height / 6 and crop.width < page.width
    assert render_pdf_page(path, 3) is None and render_pdf_page(path, 0) is None
