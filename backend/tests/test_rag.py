import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
from app.config import Settings
from app.models import Course, Resource
from app.services.rag import CHUNKING, RagService, _citations
from openai import NotFoundError

from tests.fake_openai import FakeVectorStores


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
                    "Shear stress is tangential force per unit area, as described in Lecture 1."
                ),
                model_dump=lambda: {},
            )

    fake_responses = FakeResponses()
    fake_client = SimpleNamespace(responses=fake_responses, vector_stores=FakeVectorStores())
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
    assert fake_client.vector_stores.calls[0]["filters"] == {
        "type": "eq",
        "key": "course_code",
        "value": "SYDE 286",
    }
    assert "Explain shear stress from Lecture 1." in fake_responses.call["input"]


class FakeIndexClient:
    """Minimal OpenAI stand-in: uploads whose name contains "bad" fail processing."""

    def __init__(self) -> None:
        self.uploaded: dict[str, str] = {}
        self.deleted: list[str] = []
        self.chunking: list[Any] = []
        # Files already in the vector store, tracked or not.
        self.stored: list[str] = []
        self.files = SimpleNamespace(create=self._create_file, delete=self._delete_file)
        self.vector_stores = SimpleNamespace(
            files=SimpleNamespace(
                create=self._attach,
                retrieve=self._retrieve,
                list=lambda vector_store_id, limit: [
                    SimpleNamespace(id=file_id) for file_id in self.stored
                ],
                delete=self._detach,
            )
        )

    def _attach(self, vector_store_id, file_id, attributes, chunking_strategy):
        self.chunking.append(chunking_strategy)
        return SimpleNamespace(id=file_id)

    def _create_file(self, file, purpose):
        file_id = f"file-{len(self.uploaded)}"
        self.uploaded[file_id] = Path(file.name).name
        return SimpleNamespace(id=file_id)

    def _retrieve(self, file_id, vector_store_id):
        if "bad" in self.uploaded[file_id]:
            return SimpleNamespace(
                status="failed", last_error=SimpleNamespace(message="unsupported file")
            )
        return SimpleNamespace(status="completed")

    def _detach(self, file_id, vector_store_id):
        if file_id == "file-gone":
            raise _not_found()

    def _delete_file(self, file_id):
        if file_id == "file-gone":
            raise _not_found()
        self.deleted.append(file_id)


def _not_found() -> NotFoundError:
    request = httpx.Request("DELETE", "https://api.openai.com/v1/files/file-gone")
    return NotFoundError("gone", response=httpx.Response(404, request=request), body=None)


def _resource(tmp_path, resource_id: str, filename: str) -> tuple[Resource, Course]:
    path = tmp_path / filename
    path.write_text("lecture notes", encoding="utf-8")
    course = Course(code="SYDE 212", name="SYDE 212", url="https://learn.example/course")
    resource = Resource(
        id=resource_id,
        title=filename,
        resource_type="DOCUMENT",
        local_path=str(path),
        content_hash=f"hash-{resource_id}",
    )
    return resource, course


def test_failed_file_is_skipped_and_manifest_is_saved(tmp_path, caplog) -> None:
    client = FakeIndexClient()
    service = RagService(Settings(openai_api_key="test-key"), client=cast(Any, client))
    service.manifest_path = tmp_path / "manifest.json"
    service.manifest_path.write_text(
        json.dumps(
            {
                "vector_store_id": "vs-test",
                "files": {
                    "removed": {"file_id": "file-gone"},
                    "also-removed": {"file_id": "file-old"},
                },
            }
        ),
        encoding="utf-8",
    )
    rows = [
        _resource(tmp_path, "r-bad", "bad.txt"),
        _resource(tmp_path, "r-good", "good.txt"),
    ]

    with caplog.at_level(logging.WARNING):
        vector_store_id, indexed, skipped, failed = service.index_resources(rows)

    assert (vector_store_id, indexed, skipped, failed) == ("vs-test", 1, 0, 1)
    assert "unsupported file" in caplog.text
    # An already-deleted stale file is not reported as a problem.
    assert "stale indexed file" not in caplog.text
    # The failed upload is cleaned up rather than orphaned.
    assert "file-0" in client.deleted
    assert "file-old" in client.deleted
    manifest = json.loads(service.manifest_path.read_text(encoding="utf-8"))
    assert set(manifest["files"]) == {"r-good"}


def test_files_are_indexed_in_small_chunks_and_reindexed_when_chunking_changes(tmp_path) -> None:
    client = FakeIndexClient()
    service = RagService(Settings(openai_api_key="test-key"), client=cast(Any, client))
    service.manifest_path = tmp_path / "manifest.json"
    current = _resource(tmp_path, "r-current", "current.txt")
    old = _resource(tmp_path, "r-old", "old.txt")
    service.manifest_path.write_text(
        json.dumps(
            {
                "vector_store_id": "vs-test",
                "files": {
                    "r-current": {
                        "file_id": "f-1",
                        "content_hash": "hash-r-current",
                        "chunking": CHUNKING,
                    },
                    # Indexed before chunking was recorded: OpenAI's default 800/400.
                    "r-old": {"file_id": "f-2", "content_hash": "hash-r-old"},
                },
            }
        ),
        encoding="utf-8",
    )

    _, indexed, skipped, failed = service.index_resources([current, old])

    assert (indexed, skipped, failed) == (1, 1, 0)
    assert client.chunking == [
        {"type": "static", "static": {"max_chunk_size_tokens": 400, "chunk_overlap_tokens": 100}}
    ]
    assert "f-2" in client.deleted
    manifest = json.loads(service.manifest_path.read_text(encoding="utf-8"))
    assert manifest["files"]["r-old"]["chunking"] == CHUNKING == "static-400-100"
    # Unchanged files are not re-uploaded but get their LEARN title and link refreshed.
    assert manifest["files"]["r-current"]["title"] == "current.txt"
    assert manifest["files"]["r-current"]["file_id"] == "f-1"


def test_untracked_vector_store_files_are_removed(tmp_path) -> None:
    client = FakeIndexClient()
    client.stored = ["f-1", "file-stale-outline"]
    service = RagService(Settings(openai_api_key="test-key"), client=cast(Any, client))
    service.manifest_path = tmp_path / "manifest.json"
    current = _resource(tmp_path, "r-current", "current.txt")
    service.manifest_path.write_text(
        json.dumps(
            {
                "vector_store_id": "vs-test",
                "files": {
                    "r-current": {
                        "file_id": "f-1",
                        "content_hash": "hash-r-current",
                        "chunking": CHUNKING,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    service.index_resources([current])

    assert client.deleted == ["file-stale-outline"]
