"""How the tutor really writes answers, and what the page should make of each.

The cases come from live answers across the six courses. A wrong reading here either
marks a right answer wrong or, worse, marks a partial answer right.
"""

import pytest
from app.services.figures import extract_figures
from app.services.practice import answer_value, parse_quiz, quiz_blocks

ONE_NUMBER = [
    ("6 kN", 6.0, "kN"),
    ("0.35", 0.35, ""),
    ("1326", 1326.0, ""),
    ("2598960", 2598960.0, ""),
    ("2,598,960", 2598960.0, ""),
    ("-2.5e3 N/m", -2500.0, "N/m"),
    ("40 %", 40.0, "%"),
    ("40%", 40.0, "%"),
    ("12.5 kN·m", 12.5, "kN·m"),
    ("9.81 m/s^2", 9.81, "m/s^2"),
    ("2 kΩ", 2.0, "kΩ"),
    ("3 mA", 3.0, "mA"),
    ("25 °C", 25.0, "°C"),
    ("120 ways", 120.0, "ways"),
    ("$6,805.83", 6805.83, "$"),
    ("$9,798.32.", 9798.32, "$"),
    ("\\$1,312.38", 1312.38, "$"),
    ("**6 kN**", 6.0, "kN"),
    ("6 kN.", 6.0, "kN"),
    ("\\(6\\,\\text{kN}\\)", 6.0, "kN"),
    ("\\(R_A = 6\\,\\text{kN}\\)", 6.0, "kN"),
    ("$0.35$", 0.35, ""),
    ("\\(P(A \\mid B) = 0.6\\)", 0.6, ""),
    ("\\(\\approx 0.182\\)", 0.182, ""),
    ("≈ 0.182", 0.182, ""),
    ("\\(4.7\\ \\text{k}\\Omega\\)", 4.7, "kΩ"),
    ("\\(100\\ \\mu\\text{F}\\)", 100.0, "µF"),
    ("−4 kN", -4.0, "kN"),
    ("+6 V", 6.0, "V"),
]

FRACTIONS = [("2/11", 2 / 11), ("3 / 8", 0.375), ("\\(1/6\\)", 1 / 6), ("-1/2", -0.5)]

NOT_ONE_NUMBER = [
    # Several quantities: marking the first alone would pass a half answer.
    "2 mA; 8 V",
    "2 kΩ; 3 mA",
    "6 V; 18 mW",
    "\\(A_y=6\\,\\text{kN}\\), \\(B_y=6\\,\\text{kN}\\)",
    "x = 2, y = 3",
    "Future amount: $6,312.38; interest earned: $1,312.38",
    "6 kN at A and 6 kN at B",
    "3:2",
    "1/0",
    "between 4 and 6",
    "3 of the 5 supports are pinned",
    # Words.
    "The load adds a step equal to its size.",
    "True",
    "B",
    "",
    # Code.
    "```r\nmean(x)\n```",
    "mean(heights)",
    # A range or an interval is two numbers.
    "0.2 to 0.4",
    "(0.21, 0.39)",
]


@pytest.mark.parametrize(("answer", "number", "unit"), ONE_NUMBER)
def test_an_answer_that_is_one_quantity_is_marked_by_its_number(
    answer: str, number: float, unit: str
) -> None:
    value, found_unit = answer_value(answer)

    assert value == pytest.approx(number)
    assert found_unit == unit


@pytest.mark.parametrize(("answer", "number"), FRACTIONS)
def test_an_exact_fraction_is_its_value(answer: str, number: float) -> None:
    value, unit = answer_value(answer)

    assert value == pytest.approx(number) and unit == ""


@pytest.mark.parametrize("answer", NOT_ONE_NUMBER)
def test_anything_else_is_left_for_the_student_to_compare(answer: str) -> None:
    assert answer_value(answer) == (None, "")


WHY = "It comes from a sample."
LABEL_STYLES = [
    f"Q: Which is a statistic?\nA) mu\nB) x-bar\nAnswer: B\nWhy: {WHY}",
    f"**Q:** Which is a statistic?\n**A)** mu\n**B)** x-bar\n**Answer:** B\n**Why:** {WHY}",
    f"Question 1: Which is a statistic?\n(A) mu\n(B) x-bar\nCorrect answer: (B)\nReason: {WHY}",
    f"Q1. Which is a statistic?\nA. mu\nB. x-bar\nAnswer: B. x-bar\nReason: {WHY}",
    f"Q: Which is a statistic?\n\nA) mu\n\nB) x-bar\n\nAnswer: **B**\n\nWhy: {WHY}",
    f"  Q: Which is a statistic?\n  a) mu\n  b) x-bar\n  Answer: b\n  Why: {WHY}",
]


@pytest.mark.parametrize("block", LABEL_STYLES)
def test_the_same_question_is_read_however_its_labels_are_dressed(block: str) -> None:
    quiz = parse_quiz(block)

    assert quiz.question == "Which is a statistic?"
    assert (quiz.choices, quiz.correct) == (["mu", "x-bar"], 1)
    assert quiz.explanation == WHY


CODE_QUESTION = """\
Before.

```quiz
Q: What does this print?
```r
x <- c(2, 4, 6)
# Answer: not a label, just a comment
mean(x)
```
Answer: 4
Why: The mean of 2, 4 and 6 is 4.
```

Between.

```quiz
Q: Write R code for the standard deviation of `x`.
Answer:
```r
sd(x)
```
Why: `sd` uses the sample formula.
```

After.
"""


def test_a_question_about_code_keeps_its_code_block() -> None:
    first, second = (body for _start, _end, body in quiz_blocks(CODE_QUESTION))

    printed = parse_quiz(first)
    assert "```r\nx <- c(2, 4, 6)" in printed.question and printed.question.endswith("```")
    # A label-looking line inside the code is code.
    assert "# Answer: not a label" in printed.question
    assert (printed.answer, printed.number) == ("4", 4.0)

    written = parse_quiz(second)
    assert written.answer == "```r\nsd(x)\n```" and written.number is None
    assert written.explanation == "`sd` uses the sample formula."


def test_questions_about_code_come_out_of_an_answer_whole() -> None:
    text, figures = extract_figures(CODE_QUESTION)

    assert [figure.kind for figure in figures] == ["quiz", "quiz"]
    # Nothing of either question is left behind, and the rest of the answer is intact.
    assert "```r" not in text and "Answer" not in text and "```quiz" not in text
    assert [line for line in text.splitlines() if line and not line.startswith("```")] == [
        "Before.",
        "0",
        "Between.",
        "1",
        "After.",
    ]


def test_quizzes_and_other_figures_keep_their_places() -> None:
    answer = (
        "```quiz\nQ: 1 + 1?\nAnswer: 2\n```\n\n"
        '```plot\n{"title": "Line", "series": [{"label": "y", "expr": "x"}], '
        '"x": {"min": 0, "max": 1}}\n```\n\n'
        "```quiz\nQ: 2 + 2?\nAnswer: 4\n```\n"
    )

    text, figures = extract_figures(answer)

    slots = [int(line) for line in text.splitlines() if line.isdigit()]
    # Every figure is placed exactly once, each placeholder at its own block.
    assert sorted(slots) == list(range(len(figures)))
    by_place = [figures[slot] for slot in slots]
    assert [figure.kind for figure in by_place][0] == "quiz"
    assert [figure.kind for figure in by_place][-1] == "quiz"
    assert by_place[0].question == "1 + 1?" and by_place[-1].question == "2 + 2?"  # type: ignore[union-attr]


def test_an_unfinished_quiz_block_is_left_as_it_is() -> None:
    answer = "Intro.\n\n```quiz\nQ: Cut off by the length limit"

    text, figures = extract_figures(answer)

    assert figures == [] and "Q: Cut off by the length limit" in text
