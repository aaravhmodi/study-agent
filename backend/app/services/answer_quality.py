"""Deterministic readability checks for tutor answers shown to students."""

import re

from pydantic import BaseModel, ConfigDict, Field

# Sections the tutor prompt asks for when explaining a topic.
EXPLAIN_SECTIONS = (
    "Overview",
    "Key concepts",
    "Worked example",
    "Common mistakes",
    "Check yourself",
    "Study checklist",
)

_HEADING = re.compile(r"^(#{2,3})\s+(.+?)\s*#*\s*$", flags=re.MULTILINE)
_INLINE_CITATION = re.compile(
    r"\[[^\]\n]+\.(?:pdf|txt|docx?|pptx|md|html|tex)(?:,\s*(?:pp?\.|\u00a7\u00a7?|ch(?:apter|\.)?)\s*[\d.\u2013-]+)?\]",
    re.IGNORECASE,
)
_LEFTOVER_MARKER = re.compile(r"filecite|turn\d+file\d+|[\ue000-\uf8ff]")
_DISPLAY_MATH = re.compile(r"\\\[[\s\S]+?\\\]|\$\$[\s\S]+?\$\$")
_INLINE_MATH = re.compile(r"\\\([\s\S]+?\\\)")
# KaTeX rejects math-only symbols such as "·" or "×" inside \text{...}.
_UNICODE_IN_TEXT = re.compile(r"\\text\{[^}]*[·×÷°±≤≥]")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


class AnswerQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    word_count: int
    sections: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    practice_questions: int = 0
    inline_citations: int = 0
    longest_paragraph_words: int = 0
    issues: list[str] = Field(default_factory=list)

    @property
    def readable(self) -> bool:
        return not self.issues


def assess_answer(
    answer: str,
    *,
    expect_sections: bool = True,
    min_concepts: int = 3,
    max_words: int = 1400,
    max_paragraph_words: int = 120,
) -> AnswerQuality:
    """Score an answer; ``issues`` lists every problem a student would notice."""

    issues: list[str] = []
    headings = [(len(marks), title.strip()) for marks, title in _HEADING.findall(answer)]
    sections = [title for level, title in headings if level == 2]
    concepts = _concepts(headings)
    words = len(answer.split())
    prose = _DISPLAY_MATH.sub(" ", answer)
    paragraphs = [block for block in re.split(r"\n\s*\n", prose) if block.strip()]
    longest = max((len(block.split()) for block in paragraphs if _is_prose(block)), default=0)

    if words < 80:
        issues.append(f"too short ({words} words)")
    if words > max_words:
        issues.append(f"too long ({words} words)")
    if longest > max_paragraph_words:
        issues.append(f"wall of text ({longest}-word paragraph)")
    if _LEFTOVER_MARKER.search(answer):
        issues.append("leftover citation markers")
    if not _math_balanced(answer):
        issues.append("unbalanced math delimiters")
    if answer.count("```") % 2:
        issues.append("unclosed code fence")
    hidden_answers = answer.count("<details>")
    if hidden_answers != answer.count("</details>"):
        issues.append("unclosed hidden answer")
    if _has_bare_latex(answer):
        issues.append("LaTeX outside math delimiters")
    if _UNICODE_IN_TEXT.search(answer):
        issues.append("Unicode symbol inside \\text{} (KaTeX shows it in red)")
    if _long_sentences(prose):
        issues.append("run-on sentences")
    citations = len(_INLINE_CITATION.findall(answer))
    if citations == 0:
        issues.append("no inline source citation")
    if expect_sections:
        lowered = [section.lower() for section in sections]
        missing = [name for name in EXPLAIN_SECTIONS if not any(name.lower() in s for s in lowered)]
        if missing:
            issues.append("missing sections: " + ", ".join(missing))
        if len(concepts) < min_concepts:
            issues.append(f"only {len(concepts)} concepts explained")
        if len({concept.lower() for concept in concepts}) != len(concepts):
            issues.append("repeated concept headings")
        if hidden_answers < 2:
            issues.append(f"only {hidden_answers} self-test questions with hidden answers")
    return AnswerQuality(
        word_count=words,
        sections=sections,
        concepts=concepts,
        practice_questions=hidden_answers,
        inline_citations=citations,
        longest_paragraph_words=longest,
        issues=issues,
    )


def _concepts(headings: list[tuple[int, str]]) -> list[str]:
    """Return the ### headings nested under the "Key concepts" section."""

    concepts: list[str] = []
    inside = False
    for level, title in headings:
        if level == 2:
            inside = "concept" in title.lower()
        elif inside:
            concepts.append(title)
    return concepts


def _is_prose(block: str) -> bool:
    stripped = block.lstrip()
    return not stripped.startswith(("|", "-", "*", "#", ">")) and not stripped[:1].isdigit()


def _math_balanced(answer: str) -> bool:
    return (
        answer.count("\\(") == answer.count("\\)")
        and answer.count("\\[") == answer.count("\\]")
        and answer.count("$$") % 2 == 0
    )


def _has_bare_latex(answer: str) -> bool:
    outside = _INLINE_MATH.sub(" ", _DISPLAY_MATH.sub(" ", answer))
    outside = re.sub(r"(?<![\\$\w])\$[^$\n]+\$", " ", outside)
    return bool(re.search(r"\\(?:frac|int|sum|sigma|tau|Delta|cdot|sqrt)\b", outside))


def _long_sentences(prose: str, limit: int = 45) -> bool:
    # Each line is judged on its own so terse bullets never merge into one "sentence".
    for line in _INLINE_MATH.sub("x", prose).splitlines():
        if line.lstrip().startswith("|"):
            continue
        if any(len(sentence.split()) > limit for sentence in _SENTENCE_END.split(line)):
            return True
    return False
