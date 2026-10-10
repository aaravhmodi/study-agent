"""A course question in an answer: named by file, label and page, and shown from the PDF."""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app import main
from app.config import Settings
from app.db.database import Base
from app.models import Course, Resource
from app.schemas.chat import SourceFigure
from app.services.question_sources import SOURCE_GUIDE
from app.services.rag import TUTOR_INSTRUCTIONS, RagService
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tests.fake_openai import FakeVectorStores
from tests.pdf_fixture import Line, write_pdf

RESOURCE_ID = "0b0c7e2a-1111-4222-8333-444455556666"
SAVED_NAME = f"{RESOURCE_ID}_Problem-Set-2.pdf"
QUESTION: list[Line] = [
    (72, 170, "Problem 2.6"),
    (72, 200, "The voltage drop is the same on every path."),
    (72, 500, "Problem 2.7"),
    (72, 530, "Both current sources are in the same branch."),
]
ANSWER = """\
Here is one from your problem set, Problem 2.6 in Problem-Set-2.pdf, p. 1:

```source
{"file": "Problem-Set-2.pdf", "page": 1, "question": "Problem 2.6"}
```

Start from Kirchhoff's voltage law [Problem-Set-2.pdf, p. 1].
"""


def _downloads(tmp_path: Path) -> Path:
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    pdf = write_pdf(downloads / SAVED_NAME, [QUESTION])
    pdf.with_suffix(".txt").write_text(
        "[Page 1]\nProblem 2.6\nThe voltage drop is the same on every path.\n"
        "Problem 2.7\nBoth current sources are in the same branch.",
        encoding="utf-8",
    )
    return downloads


def test_the_tutor_shows_the_course_question_it_cites(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    def create(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(output_text=ANSWER, model_dump=lambda: {"output": []})

    # Search returns the uploaded text file's name and a slice that starts mid-page.
    hit = SimpleNamespace(
        filename=SAVED_NAME.replace(".pdf", ".txt"),
        file_id="file-set-2",
        score=0.8,
        attributes={"resource_id": RESOURCE_ID},
        content=[SimpleNamespace(type="text", text="The voltage drop is the same on every path.")],
    )
    client = SimpleNamespace(
        responses=SimpleNamespace(create=create), vector_stores=FakeVectorStores([hit])
    )
    service = RagService(Settings(openai_api_key="test-key"), client=client)  # type: ignore[arg-type]
    service.downloads_dir = _downloads(tmp_path)
    service.manifest_path = tmp_path / "manifest.json"
    entry = {
        "course_code": "SYDE 292",
        "file_id": "file-set-2",
        "filename": SAVED_NAME,
        "title": "Problem Set 2",
        "source_url": "https://learn.uwaterloo.ca/d2l/le/content/1/viewContent/2/View",
    }
    service.manifest_path.write_text(
        json.dumps({"vector_store_id": "vs-test", "files": {RESOURCE_ID: entry}}), encoding="utf-8"
    )

    result = service.ask("Give me a practice problem on source interconnections.", "SYDE 292")

    # The passage is named by the PDF it came from and the page it starts on.
    assert (
        "[Problem-Set-2.pdf]\n[Page 1]\nThe voltage drop is the same on every path."
        in calls[0]["input"]
    )
    (figure,) = result.figures
    assert isinstance(figure, SourceFigure)
    assert (figure.title, figure.question, figure.location) == (
        "Problem Set 2",
        "Problem 2.6",
        "p. 1",
    )
    assert figure.images[0].startswith(f"/course-resources/{RESOURCE_ID}/pages/1?top=0.")
    assert "```figure\n0\n```" in result.answer and "```source" not in result.answer
    assert [citation.title for citation in result.citations] == ["Problem Set 2"]
    assert SOURCE_GUIDE in TUTOR_INSTRUCTIONS


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    downloads = _downloads(tmp_path)
    with sessions() as session:
        course = Course(code="SYDE 292", name="Circuits", url="https://learn.example/course")
        session.add(course)
        session.flush()
        session.add(
            Resource(
                id=RESOURCE_ID,
                course_id=course.id,
                title="Problem Set 2",
                resource_type="DOCUMENT",
                local_path=str(downloads / SAVED_NAME),
                first_seen_at=datetime.now(UTC),
            )
        )
        session.add(
            Resource(
                id="moved",
                course_id=course.id,
                title="Problem Set 2",
                resource_type="DOCUMENT",
                # Saved on a Windows machine, then served from a copy of its data.
                local_path=rf"C:\Users\someone\agent\data\downloads\{SAVED_NAME}",
                first_seen_at=datetime.now(UTC),
            )
        )
        session.add(
            Resource(
                id="outside",
                course_id=course.id,
                title="Elsewhere",
                resource_type="DOCUMENT",
                local_path=str(write_pdf(tmp_path / "elsewhere.pdf", [QUESTION])),
                first_seen_at=datetime.now(UTC),
            )
        )
        session.commit()
    monkeypatch.setattr(main, "SessionLocal", sessions)
    monkeypatch.setattr(main, "ensure_schema", lambda: None)
    monkeypatch.setattr(
        type(main.get_settings()), "downloads_dir", property(lambda self: downloads)
    )
    return TestClient(main.app)


def test_a_question_is_served_as_an_image_of_its_part_of_the_page(client: TestClient) -> None:
    page = client.get(f"/course-resources/{RESOURCE_ID}/pages/1")
    question = client.get(f"/course-resources/{RESOURCE_ID}/pages/1?top=0.2&bottom=0.6")

    assert page.status_code == question.status_code == 200
    assert page.headers["content-type"] == question.headers["content-type"] == "image/png"
    assert page.content.startswith(b"\x89PNG") and len(question.content) < len(page.content)


def test_a_database_from_another_machine_still_finds_its_saved_files(client: TestClient) -> None:
    page = client.get("/course-resources/moved/pages/1")

    assert page.status_code == 200 and page.content.startswith(b"\x89PNG")


def test_only_real_pages_of_saved_course_pdfs_are_served(client: TestClient) -> None:
    for url in (
        f"/course-resources/{RESOURCE_ID}/pages/2",
        f"/course-resources/{RESOURCE_ID}/pages/0",
        f"/course-resources/{RESOURCE_ID}/pages/1?top=0.6&bottom=0.2",
        "/course-resources/no-such-resource/pages/1",
        # A resource whose file is not in the downloads folder.
        "/course-resources/outside/pages/1",
    ):
        assert client.get(url).status_code == 404, url
    assert client.get(f"/course-resources/{RESOURCE_ID}/pages/1?top=2").status_code == 422
