"""Run tutor questions against the live index and score how readable the answers are."""

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.chat import ChatResponse
from app.services.answer_quality import AnswerQuality, assess_answer


class EvalQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    course_code: str | None = None
    # "Explain ..." questions must follow the concept-by-concept layout.
    explain: bool = True
    expected_terms: list[str] = Field(default_factory=list)
    # Questions about a shape (a diagram, a distribution) should come with a graph.
    expect_figure: bool = False


class EvalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    course_code: str | None
    quality: AnswerQuality | None = None
    missing_terms: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    figures: list[str] = Field(default_factory=list)
    missing_figure: bool = False
    error: str | None = None

    @property
    def passed(self) -> bool:
        return (
            self.error is None
            and self.quality is not None
            and self.quality.readable
            and not self.missing_terms
            and bool(self.citations)
            and not self.missing_figure
        )


_SHEAR = "SYDE 286"

SHEAR_FORCE_QUESTIONS: list[EvalQuestion] = [
    EvalQuestion(
        question="Explain shear force.",
        course_code=_SHEAR,
        expected_terms=["shear force", "bending moment"],
    ),
    EvalQuestion(
        question="Explain the chapter on shear force and bending moment diagrams.",
        course_code=_SHEAR,
        expected_terms=["shear force", "bending moment", "diagram"],
    ),
    EvalQuestion(
        question="Explain how distributed load, shear force and bending moment are related.",
        course_code=_SHEAR,
        expected_terms=["distributed load", "shear force", "bending moment"],
    ),
    EvalQuestion(
        question="Explain the sign convention for internal shear force in a beam.",
        course_code=_SHEAR,
        expected_terms=["shear force", "sign"],
    ),
    EvalQuestion(
        question="Explain how to draw the shear force diagram for a simply supported beam "
        "with a point load.",
        course_code=_SHEAR,
        expected_terms=["shear force", "support", "reaction"],
        expect_figure=True,
    ),
    EvalQuestion(
        question="Explain shear stress and how it differs from shear force.",
        course_code=_SHEAR,
        expected_terms=["shear stress", "shear force"],
    ),
    EvalQuestion(
        question="What is the maximum shear force in a cantilever with a uniform load?",
        course_code=_SHEAR,
        explain=False,
        expected_terms=["shear force", "cantilever"],
    ),
]


# One core-topic question and one lecture lookup per Fall 2026 course.
COURSE_QUESTIONS: list[EvalQuestion] = [
    EvalQuestion(
        question="Explain conditional probability and Bayes' theorem.",
        course_code="SYDE 212",
        expected_terms=["conditional probability", "bayes"],
    ),
    EvalQuestion(
        question="Explain the normal distribution and how to find P(a < X < b).",
        course_code="SYDE 212",
        expected_terms=["normal", "standard deviation"],
        expect_figure=True,
    ),
    EvalQuestion(
        question="Explain signal energy and power.",
        course_code="SYDE 252",
        expected_terms=["energy", "power"],
    ),
    EvalQuestion(
        question="Explain present worth and the time value of money.",
        course_code="SYDE 262",
        expected_terms=["present worth", "interest"],
    ),
    EvalQuestion(
        question="Explain normal stress and strain.",
        course_code=_SHEAR,
        expected_terms=["stress", "strain"],
    ),
    EvalQuestion(
        question="Explain Kirchhoff's voltage and current laws.",
        course_code="SYDE 292",
        expected_terms=["kirchhoff", "voltage", "current"],
    ),
    EvalQuestion(
        question="Explain how to measure voltage and current safely with a multimeter.",
        course_code="SYDE 292L",
        expected_terms=["multimeter", "voltage", "current"],
    ),
    *[
        EvalQuestion(question="Explain what Lecture 1 covered.", course_code=code)
        for code in ("SYDE 212", "SYDE 252", "SYDE 262", _SHEAR, "SYDE 292")
    ],
]

EVAL_QUESTIONS: list[EvalQuestion] = SHEAR_FORCE_QUESTIONS + COURSE_QUESTIONS


def run_eval(
    ask: Callable[[str, str | None], ChatResponse], questions: list[EvalQuestion]
) -> list[EvalResult]:
    """Ask every question and score its answer."""

    results: list[EvalResult] = []
    for item in questions:
        try:
            response = ask(item.question, item.course_code)
        except Exception as exc:  # reported per question so one failure never stops the run
            results.append(
                EvalResult(question=item.question, course_code=item.course_code, error=str(exc))
            )
            continue
        lowered = response.answer.lower()
        results.append(
            EvalResult(
                question=item.question,
                course_code=item.course_code,
                quality=assess_answer(response.answer, expect_sections=item.explain),
                missing_terms=[term for term in item.expected_terms if term not in lowered],
                citations=[citation.filename for citation in response.citations],
                figures=[figure.kind for figure in response.figures],
                missing_figure=item.expect_figure and not response.figures,
            )
        )
    return results
