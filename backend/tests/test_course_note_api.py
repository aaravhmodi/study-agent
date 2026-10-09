from pathlib import Path

import pytest
from app import main
from app.cli.commands import app as cli
from app.services.course_notes import list_notes
from fastapi.testclient import TestClient
from typer.testing import CliRunner


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(main, "_notes_path", lambda: tmp_path / "course_notes.json")
    monkeypatch.setattr(main, "_course_code", lambda course_id: "SYDE 212")
    return TestClient(main.app)


def test_notes_are_added_listed_and_deleted_over_the_api(client: TestClient) -> None:
    midterm = client.post(
        "/courses/c1/notes", json={"text": "Chapters 1-4, 40 MC.", "about": "Midterm"}
    ).json()
    client.post("/courses/c1/notes", json={"text": "Office hours on Friday."})

    listed = client.get("/courses/c1/notes").json()
    assert [note["about"] for note in listed] == [None, "Midterm"]
    assert client.delete(f"/courses/c1/notes/{midterm['id']}").json() == {"deleted": True}
    assert client.delete(f"/courses/c1/notes/{midterm['id']}").status_code == 404
    assert len(client.get("/courses/c1/notes").json()) == 1


def test_empty_or_overlong_notes_are_rejected(client: TestClient) -> None:
    assert client.post("/courses/c1/notes", json={"text": ""}).status_code == 422
    assert client.post("/courses/c1/notes", json={"text": "x" * 5000}).status_code == 422
    assert client.post("/courses/c1/notes", json={"text": "   "}).status_code == 422


def test_unknown_course_is_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "_notes_path", lambda: tmp_path / "course_notes.json")

    response = TestClient(main.app).post("/courses/no-such-course/notes", json={"text": "x"})

    assert response.status_code == 404


def test_cli_adds_lists_and_deletes_notes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(type(get_settings()), "data_dir", property(lambda self: tmp_path))
    runner = CliRunner()

    added = runner.invoke(
        cli, ["course-note", "syde 212", "--text", "Chapters 1-4.", "--about", "Midterm"]
    )
    shown = runner.invoke(cli, ["course-note", "SYDE 212"])
    (note,) = list_notes(tmp_path / "course_notes.json", "SYDE 212")
    deleted = runner.invoke(cli, ["course-note", "SYDE 212", "--delete", note.id])

    assert added.exit_code == 0 and "Saved note" in added.output
    assert "about Midterm" in shown.output and "Chapters 1-4." in shown.output
    assert deleted.exit_code == 0
    assert list_notes(tmp_path / "course_notes.json", "SYDE 212") == []
