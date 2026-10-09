import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app.config import Settings
from app.services.answer_format import clean_citations
from app.services.lecture_scope import lecture_refs, matching_resource_ids
from app.services.rag import RagService, _citations

PREFIX = "b0467ae8-9051-4969-8f79-f903ef74fc92_"
FILES: dict[str, dict[str, str]] = {
    "r-l7": {"course_code": "SYDE 286", "filename": f"{PREFIX}Lecture_07_Shear_and_Moment.pdf"},
    "r-l17": {"course_code": "SYDE 286", "filename": "L17_Torsion.pdf"},
    "r-l7-short": {"course_code": "SYDE 286", "filename": "L7 notes.txt"},
    "r-hw7": {"course_code": "SYDE 286", "filename": "Homework_7.pdf"},
    "r-252-l7": {"course_code": "SYDE 252", "filename": "Lecture 7 - Convolution.pdf"},
    "r-wk3": {"course_code": "SYDE 212", "filename": "Week3-Bayes.pptx"},
}


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("What did Lecture 7 cover?", {("lecture", 7)}),
        ("summarize lec 7", {("lecture", 7)}),
        ("Explain lectures 7", {("lecture", 7)}),
        ("week 3 and Ch. 5", {("week", 3), ("chapter", 5)}),
        ("Tutorial #4 problem 2", {("tutorial", 4)}),
        ("Explain shear force.", set()),
    ],
)
def test_lecture_references_are_parsed(question: str, expected: set[tuple[str, int]]) -> None:
    assert lecture_refs(question) == expected


def test_lecture_number_matches_padded_and_short_filenames_only() -> None:
    ids = matching_resource_ids("What was in lecture 7?", FILES, "SYDE 286")

    assert ids == ["r-l7", "r-l7-short"]


def test_lecture_match_is_limited_to_the_course() -> None:
    assert matching_resource_ids("Lecture 7", FILES, "SYDE 252") == ["r-252-l7"]
    assert set(matching_resource_ids("Lecture 7", FILES, None)) == {
        "r-l7",
        "r-l7-short",
        "r-252-l7",
    }


def test_week_reference_matches_week_files() -> None:
    assert matching_resource_ids("Explain week 3", FILES, "SYDE 212") == ["r-wk3"]


class FakeResponses:
    def __init__(self, annotations: list[dict[str, Any]] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.annotations = annotations or []

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        payload = {"output": [{"content": [{"annotations": self.annotations}]}]}
        return SimpleNamespace(output_text="An answer.", model_dump=lambda: payload)


def _service(tmp_path: Path, responses: FakeResponses, **settings: Any) -> RagService:
    service = RagService(
        Settings(openai_api_key="test-key", **settings),
        client=SimpleNamespace(responses=responses),  # type: ignore[arg-type]
    )
    service.manifest_path = tmp_path / "manifest.json"
    service.manifest_path.write_text(
        json.dumps({"vector_store_id": "vs-test", "files": FILES}), encoding="utf-8"
    )
    return service


def test_named_lecture_narrows_file_search_to_its_files(tmp_path: Path) -> None:
    responses = FakeResponses()

    _service(tmp_path, responses).ask("What did lecture 7 cover?", "SYDE 286")

    call = responses.calls[0]
    assert call["tools"][0]["filters"] == {
        "type": "and",
        "filters": [
            {"type": "eq", "key": "course_code", "value": "SYDE 286"},
            {
                "type": "or",
                "filters": [
                    {"type": "eq", "key": "resource_id", "value": "r-l7"},
                    {"type": "eq", "key": "resource_id", "value": "r-l7-short"},
                ],
            },
        ],
    }
    assert "Lecture files: Lecture_07_Shear_and_Moment.pdf, L7 notes.txt" in call["input"]


def test_single_lecture_file_uses_a_plain_filter(tmp_path: Path) -> None:
    responses = FakeResponses()

    _service(tmp_path, responses).ask("Summarize lecture 7", "SYDE 252")

    assert responses.calls[0]["tools"][0]["filters"]["filters"][1] == {
        "type": "eq",
        "key": "resource_id",
        "value": "r-252-l7",
    }


def test_unknown_lecture_falls_back_to_the_whole_course(tmp_path: Path) -> None:
    responses = FakeResponses()

    _service(tmp_path, responses).ask("What did lecture 30 cover?", "SYDE 286")

    call = responses.calls[0]
    assert call["tools"][0]["filters"] == {"type": "eq", "key": "course_code", "value": "SYDE 286"}
    assert "Lecture files" not in call["input"]


def test_web_search_adds_online_context_cheaply(tmp_path: Path) -> None:
    responses = FakeResponses()

    _service(tmp_path, responses).ask("Explain shear force.", "SYDE 286")

    assert responses.calls[0]["tools"][1] == {"type": "web_search", "search_context_size": "low"}


def test_web_search_can_be_turned_off(tmp_path: Path) -> None:
    responses = FakeResponses()

    _service(tmp_path, responses, rag_web_search=False).ask("Explain shear force.", "SYDE 286")

    assert [tool["type"] for tool in responses.calls[0]["tools"]] == ["file_search"]


def test_online_sources_are_returned_with_their_urls(tmp_path: Path) -> None:
    responses = FakeResponses(
        [
            {"type": "file_citation", "filename": f"{PREFIX}Lecture_07.pdf", "file_id": "f1"},
            {
                "type": "url_citation",
                "title": "Shear and moment diagrams",
                "url": "https://x.org/a",
            },
            {"type": "url_citation", "title": "Same page again", "url": "https://x.org/a"},
        ]
    )

    result = _service(tmp_path, responses).ask("Explain shear force.", "SYDE 286")

    assert [citation.model_dump() for citation in result.citations] == [
        {"filename": "Lecture_07.pdf", "file_id": "f1", "url": None},
        {"filename": "Shear and moment diagrams", "file_id": None, "url": "https://x.org/a"},
    ]


def test_non_web_urls_are_never_cited() -> None:
    response = SimpleNamespace(
        model_dump=lambda: {"annotations": [{"type": "url_citation", "url": "javascript:x"}]}
    )

    assert _citations(response) == []


def test_web_and_file_citations_with_same_title_are_both_kept() -> None:
    citations = clean_citations(
        [
            {"filename": "Beam theory", "file_id": "f1"},
            {"filename": "Beam theory", "url": "https://x.org/beams"},
        ]
    )

    assert len(citations) == 2
