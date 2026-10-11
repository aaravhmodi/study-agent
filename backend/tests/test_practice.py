import pytest
from app.services.figures import MAX_QUIZZES, extract_figures
from app.services.practice import QUIZ_GUIDE, QuizError, parse_quiz

MULTIPLE_CHOICE = """\
Q: Which of these is a **parameter**?
A) The mean height of every student at the university
B) The mean height of 30 students picked at random
C) The tallest student in a tutorial
D) A histogram of one section's heights
Answer: A
Why: A parameter describes the whole population; \\(\\bar{x}\\) of a sample is a statistic.
"""


def test_multiple_choice_knows_which_option_is_right() -> None:
    quiz = parse_quiz(MULTIPLE_CHOICE)

    assert quiz.kind == "quiz"
    assert quiz.question == "Which of these is a **parameter**?"
    assert len(quiz.choices) == 4 and quiz.choices[1].startswith("The mean height of 30")
    assert quiz.correct == 0
    # The answer is the option; nothing is held twice for the page to get wrong.
    assert (quiz.answer, quiz.number) == ("", None)
    assert quiz.explanation.startswith("A parameter describes") and "\\bar{x}" in quiz.explanation


def test_a_numeric_answer_can_be_checked_and_keeps_its_unit() -> None:
    quiz = parse_quiz(
        "Q: A simply supported beam carries 12 kN at midspan.\n"
        "What is each support reaction?\n"
        "Answer: 6 kN\n"
        "Why: By symmetry each support carries half."
    )

    assert quiz.question.splitlines() == [
        "A simply supported beam carries 12 kN at midspan.",
        "What is each support reaction?",
    ]
    assert (quiz.choices, quiz.correct) == ([], None)
    assert (quiz.answer, quiz.number, quiz.unit) == ("6 kN", 6.0, "kN")

    assert parse_quiz("Q: P(A)?\nAnswer: 0.35").number == 0.35
    assert parse_quiz("Q: Stiffness?\nAnswer: -2.5e3 N/m").unit == "N/m"
    # An exact fraction is a number too: the student may type 2/11 or 0.18.
    fraction = parse_quiz("Q: P(sum is 10 | a six)?\nAnswer: 2/11")
    assert (fraction.answer, fraction.unit) == ("2/11", "")
    assert fraction.number == pytest.approx(2 / 11)
    assert parse_quiz("Q: Share late?\nAnswer: 40 %").unit == "%"
    # A ratio of two readings is not one number, and nothing divides by zero.
    assert parse_quiz("Q: Ratio?\nAnswer: 3:2").number is None
    assert parse_quiz("Q: Limit?\nAnswer: 1/0").number is None


def test_an_answer_in_words_is_shown_for_the_student_to_compare() -> None:
    quiz = parse_quiz(
        "Question 2: Why does shear change sign at a point load?\n"
        "Answer: The load adds a jump equal to its size,\nso the diagram steps down.\n"
        "Explanation: Equilibrium of a thin slice at the load."
    )

    assert quiz.number is None and quiz.answer.endswith("so the diagram steps down.")
    assert quiz.explanation == "Equilibrium of a thin slice at the load."
    # A sentence that happens to start with a number is still words.
    assert parse_quiz("Q: How many?\nAnswer: 3 of the 5 supports are pinned").number is None


def test_a_block_that_is_not_a_usable_question_is_refused() -> None:
    for block in (
        "Just some text",
        "Q: No answer given",
        "Answer: 4",
        "Q: One option?\nA) only\nAnswer: A",
        "Q: Which?\nA) x\nB) y\nAnswer: C",
        "Q: Which?\nA) x\nB) y\nAnswer: the second one",
        "Q: Which?\nA) x\nC) y\nAnswer: A",
    ):
        with pytest.raises(QuizError):
            parse_quiz(block)


def test_quiz_blocks_become_questions_in_the_answer() -> None:
    answer = f"## Check yourself\n\n```quiz\n{MULTIPLE_CHOICE}```\n\nKeep going.\n"

    text, figures = extract_figures(answer)

    assert [figure.kind for figure in figures] == ["quiz"]
    assert "```figure\n0\n```" in text and "```quiz" not in text
    # Nothing of the answer is left in the text for the student to read early.
    assert "Answer:" not in text and "A parameter describes" not in text


def test_an_unreadable_quiz_block_stays_as_its_text() -> None:
    answer = "Before.\n\n```quiz\nQ: Which?\nA) x\nB) y\nAnswer: the second one\n```\n\nAfter."

    text, figures = extract_figures(answer)

    assert figures == []
    # The question is not lost, only shown plainly.
    assert "Q: Which?" in text and "```" not in text


def test_a_long_practice_set_is_capped() -> None:
    block = "```quiz\nQ: 1 + 1?\nAnswer: 2\n```\n\n"

    _text, figures = extract_figures(block * (MAX_QUIZZES + 2))

    assert len(figures) == MAX_QUIZZES


def test_the_guide_example_is_a_valid_quiz_block() -> None:
    text, figures = extract_figures(QUIZ_GUIDE)

    assert [figure.kind for figure in figures] == ["quiz"]
    assert figures[0].number == 6.0 and figures[0].unit == "kN"  # type: ignore[union-attr]
    # Part of the static instruction prefix, so it stays short.
    assert len(QUIZ_GUIDE.split()) < 190
