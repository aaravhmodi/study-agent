from pathlib import Path

import pytest
from app import main
from app.cli.commands import app as cli
from app.services.course_notes import get_note
from fastapi.testclient import TestClient
from typer.testing import CliRunner


@pytest.fixture()
def notes_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "course_notes.json"
    monkeypatch.setattr(main, "_notes_path", lambda: path)
    return path


def test_unknown_course_note_is_404(notes_path: Path) -> None:
    response = TestClient(main.app).put("/courses/no-such-course/note", json={"text": "x"})

    assert response.status_code == 404


def test_overlong_note_is_rejected(notes_path: Path) -> None:
    response = TestClient(main.app).put("/courses/x/note", json={"text": "x" * 5000})

    assert response.status_code == 422


def test_cli_sets_shows_and_clears_a_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(type(get_settings()), "data_dir", property(lambda self: tmp_path))
    runner = CliRunner()

    saved = runner.invoke(cli, ["course-note", "syde 212", "--text", "Midterm: chapters 1-4."])
    shown = runner.invoke(cli, ["course-note", "SYDE 212"])
    cleared = runner.invoke(cli, ["course-note", "SYDE 212", "--clear"])

    assert saved.exit_code == 0 and "Saved the note for SYDE 212" in saved.output
    assert "Midterm: chapters 1-4." in shown.output
    assert cleared.exit_code == 0
    assert get_note(tmp_path / "course_notes.json", "SYDE 212") is None
