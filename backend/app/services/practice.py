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
Topic: Beam reactions
Q: A simply supported beam carries 12 kN at midspan. What is each support reaction?
Answer: 6 kN
Why: By symmetry each support carries half the load.
```
Topic names the concept tested in two or three words, the same words each time for the \
same concept, so the student's results add up by topic. \
For multiple choice, put the options between Q and Answer, one per line as "A) ..." to \
"D) ...", and give the letter: "Answer: B". Otherwise Answer is the model answer; ask for \
one quantity per question, and when it is a number, write the number then its unit in \
plain text ("6 kN", "0.35"), so the student's number can be checked. Why: one or two \
sentences. Give the kind of question the student asks for. Each Q stands alone: it \
states every number and condition needed, never "as in Question 4" or "the flight above", \
even when a source block shows the original. Markdown and \\( \\) math work in Q, the \
options and Why. One block per question; a figure the question needs goes before its block.\
"""

MAX_CHOICES = 6

# The tutor sometimes dresses a label in Markdown ("**Q:**", "**Answer:** B").
_MARK = r"[*_]{0,3}"
_QUESTION = re.compile(rf"^\s*{_MARK}(?:Q|Question)\s*\d*\s*[:.)]{_MARK}\s*(.*)$", re.IGNORECASE)
_CHOICE = re.compile(rf"^\s*{_MARK}\(?([A-Fa-f])[).:]{_MARK}\s+(\S.*)$")
_ANSWER = re.compile(
    rf"^\s*{_MARK}(?:Correct\s+answer|Answer|Solution)\s*:{_MARK}\s*(.*)$", re.IGNORECASE
)
_TOPIC = re.compile(rf"^\s*{_MARK}Topic\s*:{_MARK}\s*(.*)$", re.IGNORECASE)
_WHY = re.compile(
    rf"^\s*{_MARK}(?:Why|Explanation|Because|Reason)\s*:{_MARK}\s*(.*)$", re.IGNORECASE
)
# "B", "(B)", "B)" or "B. the second option": the letter of a multiple-choice answer.
_LETTER = re.compile(r"^[*_]{0,3}\(?([A-Fa-f])(?:[).:*_]|\s|$)")
# One number, then at most one short unit with no space in it: "6 kN", "0.35",
# "-2.5e3 N/m", "40 %". "2 mA; 8 V" is two answers, so it is not a number.
_NUMBER = re.compile(
    r"^([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*([A-Za-zµΩ°%][A-Za-zµΩ°%·/^0-9²³-]{0,11})?$"
)
# A probability is often an exact fraction: "2/11".
_FRACTION = re.compile(r"^(-?\d+)\s*/\s*(\d+)$")
_THOUSANDS = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+)(?![\d,])")
_TEXT = re.compile(r"\\(?:text|mathrm|operatorname)\{([^{}]*)\}")
_FENCE = re.compile(r"^[ \t]*```")
# What is left of a symbol's name once its subscript is gone has no digits, no
# arithmetic and no summation: "\sum M_A = 0" is a statement, not an answer.
_SUBSCRIPT = re.compile(r"_(?:\{[^{}]*\}|\w)")
_NOT_A_NAME = re.compile(r"[\d+*/-]|\\(?:sum|int|frac|sqrt|prod|lim)\b")
_MONEY = re.compile(r"^\\?\$(?=\s*\d)")
# LaTeX and Markdown dressing, and the plain text each stands for.
_DRESSING = (
    ("\\(", ""),
    ("\\)", ""),
    ("\\[", ""),
    ("\\]", ""),
    ("\\$", "\x00"),
    ("$", ""),
    ("\x00", "$"),
    ("\\,", " "),
    ("\\;", " "),
    ("\\ ", " "),
    ("~", " "),
    ("\\%", "%"),
    ("\\approx", "="),
    ("≈", "="),
    ("\\cdot", "·"),
    ("\\Omega", "Ω"),
    ("\\mu", "µ"),
    ("^\\circ", "°"),
    ("−", "-"),
)


class QuizError(ValueError):
    """The block is not a question the page could ask and mark."""


def parse_quiz(text: str) -> QuizFigure:
    """Read a ```quiz block, or raise QuizError when it is not a usable question."""

    question: list[str] = []
    choices: list[list[str]] = []
    answer: list[str] = []
    why: list[str] = []
    part: list[str] | None = None
    in_code = False
    topic = ""
    for line in text.splitlines():
        if not in_code and not topic and (match := _TOPIC.match(line)):
            # One line, wherever the tutor put it; it is never part of the question.
            topic = " ".join(match.group(1).strip("*_ .").split())[:60]
        elif _FENCE.match(line):
            # Code in a question or its answer is kept whole, labels inside it unread.
            in_code = not in_code
            if part is not None:
                part.append(line)
        elif in_code:
            if part is not None:
                part.append(line)
        elif not question and (match := _QUESTION.match(line)):
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
        value, unit = answer_value(given)
        return QuizFigure(
            question=asked,
            answer=given,
            number=value,
            unit=unit,
            explanation=_joined(why),
            topic=topic,
        )
    if not 2 <= len(options) <= MAX_CHOICES:
        raise QuizError("multiple choice needs two to six options")
    letter = _LETTER.match(given)
    correct = ord(letter.group(1).upper()) - ord("A") if letter else -1
    if not 0 <= correct < len(options):
        raise QuizError("the answer is not the letter of one of the options")
    return QuizFigure(
        question=asked, choices=options, correct=correct, explanation=_joined(why), topic=topic
    )


def answer_value(answer: str) -> tuple[float | None, str]:
    """The one number an answer states and its unit, or (None, "") otherwise.

    Only an answer that is a single quantity can be marked by its number. One in
    words, or with several parts ("2 mA; 8 V"), is shown for the student to compare.
    """

    plain = _plain(answer)
    if fraction := _FRACTION.match(plain):
        bottom = int(fraction.group(2))
        return (int(fraction.group(1)) / bottom, "") if bottom else (None, "")
    money = plain.startswith("$")
    if number := _NUMBER.match(plain.removeprefix("$").strip()):
        unit = (number.group(2) or "").strip()
        if money and unit:
            return None, ""
        return float(number.group(1)), "$" if money else unit
    return None, ""


def _plain(answer: str) -> str:
    r"""An answer without its Markdown and LaTeX dressing: "6 kN" from "\(R_A = 6\,\text{kN}\)"."""

    text = answer.strip().strip("*_").strip().rstrip(".")
    if len(text.splitlines()) > 1:
        return ""
    # One dollar sign before a number is money; a pair of them is math.
    money = text.count("$") == 1 and _MONEY.match(text) is not None
    if money:
        text = _MONEY.sub("", text, count=1)
    text = ("\x00" if money else "") + _TEXT.sub(r"\1", text)
    for dressing, bare in _DRESSING:
        text = text.replace(dressing, bare)
    # "R_A = 6 kN" states one value. "x = 2, y = 3" states two, and "B(6) - 12(2) = 0"
    # is an equation to solve, so both are left alone.
    if text.count("=") == 1:
        name, value = text.split("=", 1)
        if _NOT_A_NAME.search(_SUBSCRIPT.sub("", name)):
            return ""
        text = value
    text = _THOUSANDS.sub(lambda match: match.group(1).replace(",", ""), text)
    return " ".join(text.split())


def quiz_blocks(answer: str) -> list[tuple[int, int, str]]:
    """Each ```quiz block in an answer as (start, end, body).

    A question about code holds a fenced block of its own. The fence that closes the
    quiz is the one met when no inner block is open, so the inner one stays inside.
    """

    blocks: list[tuple[int, int, str]] = []
    offset = 0
    start: int | None = None
    body_start = 0
    inner = False
    for line in answer.splitlines(keepends=True):
        stripped = line.strip()
        if start is None:
            if re.fullmatch(r"```[ \t]*quiz", stripped):
                start, body_start, inner = offset, offset + len(line), False
        elif stripped.startswith("```"):
            if inner:
                inner = False
            elif stripped == "```":
                blocks.append((start, offset + len(line), answer[body_start:offset]))
                start = None
            else:
                inner = True
        offset += len(line)
    return blocks


def _joined(lines: list[str]) -> str:
    return "\n".join(lines).strip()
