"""Turn the tutor's ```quiz blocks into practice questions answered on the page.

The tutor writes each question in a few labelled lines. This module reads them, checks
they make a usable question, and works out how the page can mark the student's answer:
which option is right, or which number.
"""

import re

from app.schemas.chat import QuizFigure

QUIZ_GUIDE = """\
Practice questions: every Check yourself question, and any practice question the student \
should try before seeing its answer, is a quiz block, never text with the answer in view:
```quiz
Q: A simply supported beam carries 12 kN at midspan. What is each support reaction?
Answer: 6 kN
Why: By symmetry each support carries half the load.
```
For multiple choice, put the options between Q and Answer, one per line as "A) ..." to \
"D) ...", and give the letter: "Answer: B". Otherwise Answer is the model answer; when it \
is a number, write the number then its unit in plain text ("6 kN", "0.35"), so the \
student's number can be checked. Why is one or two sentences. Markdown and \\( \\) math \
work in Q, the options and Why. One block per question; a figure or code the question \
needs goes before its block.\
"""

MAX_CHOICES = 6

_QUESTION = re.compile(r"^\s*(?:Q|Question)\s*\d*\s*[:.)]\s*(.*)$", re.IGNORECASE)
_CHOICE = re.compile(r"^\s*\(?([A-Fa-f])[).:]\s+(\S.*)$")
_ANSWER = re.compile(r"^\s*Answer\s*:\s*(.*)$", re.IGNORECASE)
_WHY = re.compile(r"^\s*(?:Why|Explanation|Because)\s*:\s*(.*)$", re.IGNORECASE)
# "B", "(B)", "B)" or "B. the second option": the letter of a multiple-choice answer.
_LETTER = re.compile(r"^\(?([A-Fa-f])(?:[).:]|\s|$)")
# A number, then at most a short unit: "6 kN", "0.35", "-2.5e3 N/m", "40 %".
_NUMBER = re.compile(r"^(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*([^\d\s].{0,15})?$")


class QuizError(ValueError):
    """The block is not a question the page could ask and mark."""


def parse_quiz(text: str) -> QuizFigure:
    """Read a ```quiz block, or raise QuizError when it is not a usable question."""

    question: list[str] = []
    choices: list[list[str]] = []
    answer: list[str] = []
    why: list[str] = []
    part: list[str] | None = None
    for line in text.splitlines():
        if not question and (match := _QUESTION.match(line)):
            part = question
            part.append(match.group(1))
        elif (match := _WHY.match(line)) and answer:
            part = why
            part.append(match.group(1))
        elif (match := _ANSWER.match(line)) and question and not answer:
            part = answer
            part.append(match.group(1))
        elif (match := _CHOICE.match(line)) and question and not answer:
            # Options are lettered in order, so a stray "A) ..." mid-question is text.
            if ord(match.group(1).upper()) - ord("A") != len(choices):
                raise QuizError("the options are not lettered in order")
            choices.append([match.group(2)])
            part = choices[-1]
        elif part is not None:
            part.append(line)

    asked, given = _joined(question), _joined(answer)
    if not asked or not given:
        raise QuizError("a quiz needs a question and an answer")
    options = [_joined(option) for option in choices]
    if not options:
        number = _NUMBER.match(given)
        return QuizFigure(
            question=asked,
            answer=given,
            number=float(number.group(1)) if number else None,
            unit=(number.group(2) or "").strip() if number else "",
            explanation=_joined(why),
        )
    if not 2 <= len(options) <= MAX_CHOICES:
        raise QuizError("multiple choice needs two to six options")
    letter = _LETTER.match(given)
    correct = ord(letter.group(1).upper()) - ord("A") if letter else -1
    if not 0 <= correct < len(options):
        raise QuizError("the answer is not the letter of one of the options")
    return QuizFigure(question=asked, choices=options, correct=correct, explanation=_joined(why))


def _joined(lines: list[str]) -> str:
    return "\n".join(lines).strip()
