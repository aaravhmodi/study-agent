import json
from types import SimpleNamespace

from app.config import Settings
from app.services.rag import RagService, _citations


def test_citations_are_deduplicated() -> None:
    response = SimpleNamespace(
        model_dump=lambda: {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "annotations": [
                                {
                                    "type": "file_citation",
                                    "filename": "lecture-1.pdf",
                                    "file_id": "f1",
                                },
                                {
                                    "type": "file_citation",
                                    "filename": "lecture-1.pdf",
                                    "file_id": "f1",
                                },
                            ]
                        }
                    ],
                }
            ]
        }
    )

    assert _citations(response) == [{"filename": "lecture-1.pdf", "file_id": "f1"}]


def test_missing_api_key_is_rejected() -> None:
    try:
        RagService(Settings(openai_api_key=None))
    except RuntimeError as exc:
        assert "OPENAI_API_KEY" in str(exc)
    else:
        raise AssertionError("missing API key was accepted")


def test_shear_stress_question_is_scoped_to_syde286(tmp_path) -> None:
    class FakeResponses:
        def __init__(self) -> None:
            self.call = None

        def create(self, **kwargs):
            self.call = kwargs
            return SimpleNamespace(
                output_text=(
                    "Shear stress is tangential force per unit area, as described "
                    "in Lecture 1."
                ),
                model_dump=lambda: {},
            )

    fake_responses = FakeResponses()
    fake_client = SimpleNamespace(responses=fake_responses)
    service = RagService(Settings(openai_api_key="test-key"), client=fake_client)
    service.manifest_path = tmp_path / "manifest.json"
    service.manifest_path.write_text(
        json.dumps(
            {
                "vector_store_id": "vs-test",
                "files": {"resource-1": {"course_code": "SYDE 286"}},
            }
        ),
        encoding="utf-8",
    )

    result = service.ask("Explain shear stress from Lecture 1.", "SYDE 286")

    assert "shear stress" in result.answer.lower()
    assert fake_responses.call is not None
    search_tool = fake_responses.call["tools"][0]
    assert search_tool["filters"] == {
        "type": "eq",
        "key": "course_code",
        "value": "SYDE 286",
    }
    assert "Explain shear stress from Lecture 1." in fake_responses.call["input"]
