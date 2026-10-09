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


class EvalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    course_code: str | None
    quality: AnswerQuality | None = None
    missing_terms: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    error: str | None = None

    @property
    def passed(self) -> bool:
        return (
            self.error is None
            and self.quality is not None
            and self.quality.readable
            and not self.missing_terms
            and bool(self.citations)
        )


_SHEAR = "SYDE 286"

EVAL_QUESTIONS: list[EvalQuestion] = [
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
            )
        )
    return results
