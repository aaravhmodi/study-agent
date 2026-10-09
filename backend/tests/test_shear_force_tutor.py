import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app.config import Settings
from app.schemas.chat import ChatResponse, PlotFigure, SketchFigure
from app.services.answer_quality import assess_answer
from app.services.figure_guide import FIGURE_GUIDE
from app.services.figures import extract_figures
from app.services.rag import TUTOR_GUIDE, TUTOR_INSTRUCTIONS, RagService
from app.services.rag_eval import (
    COURSE_QUESTIONS,
    EVAL_QUESTIONS,
    SHEAR_FORCE_QUESTIONS,
    EvalQuestion,
    run_eval,
)

from tests.fake_openai import LECTURE_7, FakeVectorStores

GOOD = (Path(__file__).parent / "fixtures" / "shear_force_answer.md").read_text(encoding="utf-8")
SHEAR_COURSE = "SYDE 286"


class FakeResponses:
    def __init__(self, text: str = GOOD, **extra: Any) -> None:
        self.calls: list[dict[str, Any]] = []
        self.text = text
        self.extra = extra

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(
            output_text=self.text,
            model_dump=lambda: {"output": []},
            **self.extra,
        )


def _service(tmp_path: Path, responses: FakeResponses, **settings: Any) -> RagService:
    service = RagService(
        Settings(openai_api_key="test-key", **settings),
        client=SimpleNamespace(responses=responses, vector_stores=FakeVectorStores()),  # type: ignore[arg-type]
    )
    service.manifest_path = tmp_path / "manifest.json"
    service.manifest_path.write_text(
        json.dumps({"vector_store_id": "vs-test", "files": {"r1": {"course_code": SHEAR_COURSE}}}),
        encoding="utf-8",
    )
    return service


def test_chat_uses_the_lighter_model_not_the_vision_model(tmp_path: Path) -> None:
    responses = FakeResponses()

    _service(tmp_path, responses).ask("Explain shear force.", SHEAR_COURSE)

    assert Settings().openai_chat_model == "gpt-6-luna"
    assert responses.calls[0]["model"] == "gpt-6-luna"
    assert responses.calls[0]["model"] != Settings().openai_model


def test_chat_model_and_budget_are_configurable(tmp_path: Path) -> None:
    responses = FakeResponses()
    service = _service(
        tmp_path,
        responses,
        openai_chat_model="gpt-6.1-sol",
        openai_chat_reasoning_effort="medium",
        rag_max_results=4,
        rag_max_output_tokens=1200,
    )

    service.ask("Explain shear force.", SHEAR_COURSE)

    call = responses.calls[0]
    assert call["model"] == "gpt-6.1-sol"
    assert call["reasoning"] == {"effort": "medium"}
    # Over-fetched three times, then deduplicated down to at most four passages.
    assert service.client.vector_stores.calls[0]["max_num_results"] == 12  # type: ignore[attr-defined]
    assert call["max_output_tokens"] == 1200


def test_token_budget_defaults_are_small(tmp_path: Path) -> None:
    responses = FakeResponses()
    service = _service(tmp_path, responses)

    service.ask("Explain shear force.", SHEAR_COURSE)

    call = responses.calls[0]
    assert call["reasoning"] == {"effort": "low"}
    assert call["max_output_tokens"] == 3000
    # Passages are sent in the input, so the model gets no file search of its own
    # and at most one web search.
    assert [tool["type"] for tool in call["tools"]] == ["web_search"]
    assert call["max_tool_calls"] == 1
    assert call["prompt_cache_key"] == "study-agent-tutor"
    search = service.client.vector_stores.calls[0]  # type: ignore[attr-defined]
    assert search["max_num_results"] == 18
    assert search["ranking_options"] == {"score_threshold": 0.3}
    assert Settings().rag_context_tokens == 3000


def test_instructions_are_static_and_input_holds_only_the_question(tmp_path: Path) -> None:
    responses = FakeResponses()
    service = _service(tmp_path, responses)

    service.ask("Explain shear force.", SHEAR_COURSE)
    service.ask("Explain bending moment.", SHEAR_COURSE)

    first, second = responses.calls
    # An identical instruction prefix on every call lets OpenAI cache it.
    assert first["instructions"] == second["instructions"] == TUTOR_INSTRUCTIONS
    assert first["input"].startswith(
        "Course: SYDE 286\nQuestion: Explain shear force.\n\nCourse passages (cite by file name):"
    )
    assert f"[{LECTURE_7}]\nShear force V is the internal transverse force." in first["input"]


def test_instructions_ask_for_concept_by_concept_chapter_explanations() -> None:
    for section in (
        "## Overview",
        "## Key concepts",
        "## Worked example",
        "## Check yourself",
        "## Study checklist",
    ):
        assert section in TUTOR_INSTRUCTIONS
    assert "chapter or lecture" in TUTOR_INSTRUCTIONS
    assert "### heading per concept" in TUTOR_INSTRUCTIONS
    # The teaching guide stays short; the figure guide is separate and both are a
    # static, cacheable prefix, so they cost little after the first question.
    assert len(TUTOR_GUIDE.split()) < 360
    assert len(FIGURE_GUIDE.split()) < 500
    assert TUTOR_INSTRUCTIONS.startswith(TUTOR_GUIDE) and TUTOR_INSTRUCTIONS.endswith(FIGURE_GUIDE)


def test_every_figure_example_in_the_guide_renders() -> None:
    _, figures = extract_figures(FIGURE_GUIDE)

    plot, fbd, circuit = figures
    assert isinstance(plot, PlotFigure)
    shear = dict(plot.series[0].points)
    # Simply supported 6 m beam, 6 kN at x = 2: R_A = 4 kN, so V drops from 4 to -2 at the load.
    assert shear[0.0] == 4.0 and shear[6.0] == -2.0
    assert [marker.x for marker in plot.markers] == [2.0]
    assert isinstance(fbd, SketchFigure) and "W = mg" in fbd.svg
    assert isinstance(circuit, SketchFigure) and "R = 1 kΩ" in circuit.svg
    for kind in ("mermaid", "svg", "step(x)"):
        assert kind in FIGURE_GUIDE


def test_question_is_filtered_to_the_shear_force_course(tmp_path: Path) -> None:
    responses = FakeResponses()

    service = _service(tmp_path, responses)

    service.ask("Explain shear force.", " syde 286 ")

    assert service.client.vector_stores.calls[0]["filters"] == {  # type: ignore[attr-defined]
        "type": "eq",
        "key": "course_code",
        "value": SHEAR_COURSE,
    }


def test_unscoped_question_searches_every_course(tmp_path: Path) -> None:
    responses = FakeResponses()

    service = _service(tmp_path, responses)

    service.ask("Explain shear force.")

    assert "filters" not in service.client.vector_stores.calls[0]  # type: ignore[attr-defined]
    assert responses.calls[0]["input"].startswith("Question: Explain shear force.\n\n")


def test_shear_force_answer_reaches_the_student_readable(tmp_path: Path) -> None:
    result = _service(tmp_path, FakeResponses()).ask("Explain shear force.", SHEAR_COURSE)

    assert assess_answer(result.answer).readable
    # Sources are the passage files the answer cites by name.
    assert [citation.filename for citation in result.citations] == [
        LECTURE_7,
        "Tutorial_04_Beams.pdf",
    ]


def test_answer_cut_off_by_the_token_limit_says_so(tmp_path: Path) -> None:
    responses = FakeResponses(
        status="incomplete", incomplete_details=SimpleNamespace(reason="max_output_tokens")
    )

    result = _service(tmp_path, responses).ask("Explain shear force.", SHEAR_COURSE)

    assert result.answer.endswith("ask about one concept at a time._")


def test_complete_answer_has_no_cut_off_note(tmp_path: Path) -> None:
    responses = FakeResponses(status="completed", incomplete_details=None)

    result = _service(tmp_path, responses).ask("Explain shear force.", SHEAR_COURSE)

    assert "cut short" not in result.answer


def test_invalid_reasoning_effort_is_rejected() -> None:
    with pytest.raises(ValueError):
        Settings(openai_chat_reasoning_effort="minimal")


def test_eval_set_covers_shear_force_concepts() -> None:
    assert len(SHEAR_FORCE_QUESTIONS) >= 6
    assert all(item.course_code == SHEAR_COURSE for item in SHEAR_FORCE_QUESTIONS)
    assert all(
        any("shear" in term for term in item.expected_terms) for item in SHEAR_FORCE_QUESTIONS
    )
    asked = " ".join(item.question.lower() for item in SHEAR_FORCE_QUESTIONS)
    for concept in ("sign convention", "distributed load", "diagram", "shear stress"):
        assert concept in asked


def _ask_returning(answer: str) -> Any:
    def ask(question: str, course_code: str | None) -> ChatResponse:
        return ChatResponse.model_validate(
            {"answer": answer, "citations": [{"filename": "Lecture_07.pdf"}]}
        )

    return ask


def test_eval_passes_a_readable_answer() -> None:
    questions = [EvalQuestion(question="Explain shear force.", expected_terms=["shear force"])]

    [result] = run_eval(_ask_returning(GOOD), questions)

    assert result.passed
    assert result.quality is not None
    assert len(result.quality.concepts) == 4


def test_eval_fails_an_answer_missing_expected_terms() -> None:
    questions = [EvalQuestion(question="Explain torsion.", expected_terms=["angle of twist"])]

    [result] = run_eval(_ask_returning(GOOD), questions)

    assert not result.passed
    assert result.missing_terms == ["angle of twist"]


def test_eval_records_errors_and_keeps_going() -> None:
    calls: list[str] = []

    def ask(question: str, course_code: str | None) -> ChatResponse:
        calls.append(question)
        if "first" in question:
            raise RuntimeError("No indexed materials found for SYDE 286.")
        return ChatResponse.model_validate(
            {"answer": GOOD, "citations": [{"filename": "Lecture_07.pdf"}]}
        )

    results = run_eval(ask, [EvalQuestion(question="first"), EvalQuestion(question="second")])

    assert calls == ["first", "second"]
    assert results[0].error == "No indexed materials found for SYDE 286."
    assert not results[0].passed
    assert results[1].passed


def test_eval_needs_a_graph_only_where_one_is_expected() -> None:
    plot = {"x": {"min": 0, "max": 6}, "series": [{"expr": "4"}]}
    with_graph = GOOD + f"\n\n```plot\n{json.dumps(plot)}\n```"
    question = EvalQuestion(question="Explain shear force diagrams.", expect_figure=True)

    def ask(answer: str) -> Any:
        _, figures = extract_figures(answer)
        return lambda question, course_code: ChatResponse(
            answer=answer, citations=[{"filename": "Lecture_07.pdf"}], figures=figures
        )

    [missing] = run_eval(ask(GOOD), [question])
    [drawn] = run_eval(ask(with_graph), [question])
    [optional] = run_eval(ask(GOOD), [EvalQuestion(question="Explain shear force.")])

    assert missing.missing_figure and not missing.passed
    assert drawn.figures == ["plot"] and not drawn.missing_figure
    assert optional.passed
    assert sum(item.expect_figure for item in EVAL_QUESTIONS) >= 2


def test_eval_fails_an_answer_without_sources() -> None:
    def ask(question: str, course_code: str | None) -> ChatResponse:
        return ChatResponse.model_validate({"answer": GOOD, "citations": []})

    [result] = run_eval(ask, [EvalQuestion(question="Explain shear force.")])

    assert not result.passed


def test_rag_eval_command_writes_a_report(tmp_path: Path, monkeypatch) -> None:
    from app.cli import commands
    from typer.testing import CliRunner

    class FakeRag:
        def __init__(self, settings: Any) -> None:
            pass

        ask = staticmethod(_ask_returning(GOOD))

    monkeypatch.setattr(commands, "RagService", FakeRag)
    monkeypatch.setattr(commands, "get_settings", lambda: SimpleNamespace(data_dir=tmp_path))

    result = CliRunner().invoke(
        commands.app, ["rag-eval", "-q", "Explain shear force.", "--course", SHEAR_COURSE]
    )

    assert result.exit_code == 0, result.output
    assert "1/1 answers readable" in result.output
    [row] = json.loads((tmp_path / "rag_eval.json").read_text(encoding="utf-8"))
    assert row["course_code"] == SHEAR_COURSE
    assert row["quality"]["issues"] == []


def test_eval_covers_every_course_and_a_lecture_in_each() -> None:
    courses = {"SYDE 212", "SYDE 252", "SYDE 262", "SYDE 286", "SYDE 292", "SYDE 292L"}

    assert {item.course_code for item in EVAL_QUESTIONS} == courses
    lecture_courses = {
        item.course_code for item in COURSE_QUESTIONS if "Lecture 1" in item.question
    }
    assert lecture_courses == courses - {"SYDE 292L"}


def test_answers_return_drawable_figures(tmp_path: Path) -> None:
    plot = json.dumps(
        {
            "x": {"label": "x (m)", "min": 0, "max": 4},
            "series": [{"label": "V(x)", "expr": "10 - 5*x"}],
        }
    )
    responses = FakeResponses(text=GOOD + f"\n\n```plot\n{plot}\n```\n")

    response = _service(tmp_path, responses).ask("Explain shear force.", SHEAR_COURSE)

    (figure,) = response.figures
    assert figure.kind == "plot"
    assert response.answer.endswith("```figure\n0\n```")
    payload = ChatResponse.model_validate_json(response.model_dump_json())
    assert payload.figures == response.figures


def test_answers_report_their_token_usage(tmp_path: Path) -> None:
    usage = SimpleNamespace(
        input_tokens=12000,
        input_tokens_details=SimpleNamespace(cached_tokens=7000),
        output_tokens=900,
    )
    responses = FakeResponses(usage=usage)

    result = _service(tmp_path, responses).ask("Explain shear force.", SHEAR_COURSE)

    assert result.usage is not None
    assert (result.usage.input_tokens, result.usage.cached_tokens, result.usage.output_tokens) == (
        12000,
        7000,
        900,
    )


def test_repeated_question_is_answered_from_the_cache(tmp_path: Path) -> None:
    responses = FakeResponses()
    service = _service(tmp_path, responses)

    first = service.ask("Explain shear force.", SHEAR_COURSE)
    again = service.ask("  explain shear FORCE ", "syde 286")

    assert len(responses.calls) == 1
    assert not first.cached and again.cached
    assert again.answer == first.answer and again.usage is None


def test_fresh_question_and_reindexing_skip_the_cache(tmp_path: Path) -> None:
    responses = FakeResponses()
    service = _service(tmp_path, responses)
    service.ask("Explain shear force.", SHEAR_COURSE)

    service.ask("Explain shear force.", SHEAR_COURSE, fresh=True)
    assert len(responses.calls) == 2

    manifest = json.loads(service.manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["r1"]["content_hash"] = "new lecture notes"
    service.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    service.ask("Explain shear force.", SHEAR_COURSE)
    assert len(responses.calls) == 3


def test_course_notes_go_with_questions_about_that_course(tmp_path: Path) -> None:
    from app.services.course_notes import save_note

    responses = FakeResponses()
    service = _service(tmp_path, responses)
    save_note(service.notes_path, SHEAR_COURSE, "Midterm covers chapters 1-4; 40 multiple choice.")

    service.ask("What is on the midterm?", SHEAR_COURSE)
    service.ask("What is on the syde286 midterm?")  # course named in the question
    service.ask("What is on the midterm?")  # no course chosen or named: no notes

    first, named, other = (call["input"] for call in responses.calls)
    note = "Instructor notes for SYDE 286 (added by the student):\nMidterm covers chapters 1-4"
    assert note in first and note in named
    assert "Instructor notes" not in other


def test_changing_course_notes_refreshes_saved_answers(tmp_path: Path) -> None:
    from app.services.course_notes import save_note

    responses = FakeResponses()
    service = _service(tmp_path, responses)
    service.ask("What is on the midterm?", SHEAR_COURSE)
    save_note(service.notes_path, SHEAR_COURSE, "Midterm covers chapters 1-4.")

    service.ask("What is on the midterm?", SHEAR_COURSE)

    assert len(responses.calls) == 2


def _turn(question: str, answer: str) -> Any:
    from datetime import UTC, datetime

    from app.schemas.chat_session import ChatTurn

    return ChatTurn(
        question=question,
        course_code=SHEAR_COURSE,
        response=ChatResponse(answer=answer),
        asked_at=datetime.now(UTC),
    )


def test_follow_up_sends_the_conversation_and_searches_with_the_last_question(
    tmp_path: Path,
) -> None:
    responses = FakeResponses()
    service = _service(tmp_path, responses)
    history = [
        _turn("Explain bending.", "Old answer."),
        _turn(
            "Explain shear force.",
            "V is the internal force.\n\n```figure\n0\n```\n\n"
            "<details><summary>Answer</summary>secret</details> More.",
        ),
        _turn("And the sign convention?", "Positive shear rotates clockwise."),
        _turn("What about moment?", "M is the internal couple."),
    ]

    service.ask("Why is it negative there?", SHEAR_COURSE, history=history)

    sent = responses.calls[0]["input"]
    assert "Earlier in this conversation" in sent
    assert "Student: Explain bending." not in sent  # only the last three exchanges
    assert "Student: Explain shear force.\nTutor: V is the internal force. More." in sent
    assert "secret" not in sent and "figure" not in sent
    assert "New question: Why is it negative there?" in sent
    search = service.client.vector_stores.calls[0]  # type: ignore[attr-defined]
    assert search["query"] == "What about moment?\nWhy is it negative there?"


def test_follow_ups_are_never_cached(tmp_path: Path) -> None:
    responses = FakeResponses()
    service = _service(tmp_path, responses)
    history = [_turn("Explain shear force.", "V is the internal force.")]

    service.ask("Why?", SHEAR_COURSE, history=history)
    service.ask("Why?", SHEAR_COURSE, history=history)
    service.ask("Why?", SHEAR_COURSE)  # a fresh question with the same text

    assert len(responses.calls) == 3


BOOK_CHAPTERS = [
    {
        "number": 3,
        "title": "Descriptive Statistics",
        "first_page": 21,
        "last_page": 58,
        "sections": ["3.3 Numerical Measures", "3.4 Boxplots"],
    },
    {
        "number": 4,
        "title": "Probability",
        "first_page": 59,
        "last_page": 96,
        "sections": ["4.5 Bayes' Theorem"],
    },
]


def _service_with_book(tmp_path: Path, responses: FakeResponses) -> RagService:
    service = _service(tmp_path, responses)
    files = {
        "r1": {"course_code": SHEAR_COURSE},
        "book": {"course_code": SHEAR_COURSE, "title": "Course text", "chapters": BOOK_CHAPTERS},
    }
    service.manifest_path.write_text(
        json.dumps({"vector_store_id": "vs-test", "files": files}), encoding="utf-8"
    )
    return service


def test_named_chapters_are_outlined_and_searched_by_their_titles(tmp_path: Path) -> None:
    responses = FakeResponses()
    service = _service_with_book(tmp_path, responses)

    service.ask("Give me practice questions on chapter 3.", SHEAR_COURSE)

    sent = responses.calls[0]["input"]
    assert "[Course text] Chapter 3: Descriptive Statistics (pp. 21-58): 3.3 Numerical" in sent
    assert "Chapter 4" not in sent
    query = service.client.vector_stores.calls[0]["query"]  # type: ignore[attr-defined]
    assert query.endswith("\nDescriptive Statistics: Numerical Measures, Boxplots")


def test_chapters_in_course_notes_are_outlined_too(tmp_path: Path) -> None:
    from app.services.course_notes import save_note

    responses = FakeResponses()
    service = _service_with_book(tmp_path, responses)
    save_note(service.notes_path, SHEAR_COURSE, "Midterm: chapters 3-4.")

    service.ask("What is on the midterm?", SHEAR_COURSE)

    sent = responses.calls[0]["input"]
    assert "Chapter 3: Descriptive Statistics" in sent and "Chapter 4: Probability" in sent
    # Only chapters the question itself names change the search.
    assert service.client.vector_stores.calls[0]["query"] == "What is on the midterm?"  # type: ignore[attr-defined]
