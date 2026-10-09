from datetime import UTC, datetime
from pathlib import Path

import pytest
from app import models  # noqa: F401
from app.db.database import Base
from app.models import Course, Resource
from app.services.manual_import import ImportFileError, find_resource, import_file
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

DOWNLOAD = "https://learn.uwaterloo.ca/d2l/api/le/1.82/1299242/content/topics/6617316/file"
VIEW = "https://learn.uwaterloo.ca/d2l/le/content/1299242/viewContent/6617316/View"


def _session() -> tuple[Session, Resource]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    now = datetime.now(UTC)
    for active in (False, True):
        course = Course(
            code="SYDE 212", name="SYDE 212 - Fall 2026", url=f"https://x/{active}", active=active
        )
        session.add(course)
        session.flush()
        resource = Resource(
            course_id=course.id,
            title="SYDE 212 course text (Jeremy)",
            resource_type="DOCUMENT",
            url=DOWNLOAD,
            processed=True,
            first_seen_at=now,
        )
        session.add(resource)
        session.flush()
    return session, resource  # the active course's copy


def test_view_link_finds_the_active_courses_item() -> None:
    session, active = _session()

    resource, course = find_resource(session, VIEW)

    assert resource.id == active.id and course.active


def test_imported_file_is_saved_for_indexing(tmp_path: Path) -> None:
    session, active = _session()
    source = tmp_path / "Downloads" / "textbook.txt"
    source.parent.mkdir()
    source.write_text("Chapter 1: Data", encoding="utf-8")

    resource = import_file(session, tmp_path / "downloads", source, VIEW)

    assert resource.id == active.id
    saved = Path(resource.local_path or "")
    assert saved.read_text(encoding="utf-8") == "Chapter 1: Data"
    assert saved.name == f"{active.id}_SYDE-212-course-text-Jeremy.txt"
    assert resource.content_hash and resource.processed


@pytest.mark.parametrize(
    ("link", "reason"),
    [
        ("https://outline.uwaterloo.ca/viewer/view/x", "not a LEARN content link"),
        (
            "https://learn.uwaterloo.ca/d2l/le/content/1/viewContent/2/View",
            "run `study-agent sync`",
        ),
    ],
)
def test_unknown_links_are_rejected(link: str, reason: str, tmp_path: Path) -> None:
    session, _ = _session()
    source = tmp_path / "a.pdf"
    source.write_bytes(b"%PDF")

    with pytest.raises(ImportFileError, match=reason):
        import_file(session, tmp_path / "downloads", source, link)


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    session, _ = _session()

    with pytest.raises(ImportFileError, match="file not found"):
        import_file(session, tmp_path / "downloads", tmp_path / "nope.pdf", VIEW)


def test_import_command_reports_unknown_links(tmp_path: Path) -> None:
    from app.cli.commands import app
    from typer.testing import CliRunner

    source = tmp_path / "book.pdf"
    source.write_bytes(b"%PDF")

    result = CliRunner().invoke(
        app, ["import-file", str(source), "--link", "https://example.com/x", "--no-index"]
    )

    assert result.exit_code == 1
    assert "not a LEARN content link" in result.output


@pytest.mark.parametrize(
    "link_args", [["--link", "https://example.com/x"], ["https://example.com/x"]]
)
def test_import_command_takes_the_link_either_way(tmp_path: Path, link_args: list[str]) -> None:
    from app.cli.commands import app
    from typer.testing import CliRunner

    source = tmp_path / "book.pdf"
    source.write_bytes(b"%PDF")

    result = CliRunner().invoke(app, ["import-file", str(source), *link_args, "--no-index"])

    # Both forms reach link checking (and fail on this non-LEARN link).
    assert "not a LEARN content link" in result.output


def test_import_command_without_a_link_says_so(tmp_path: Path) -> None:
    from app.cli.commands import app
    from typer.testing import CliRunner

    source = tmp_path / "book.pdf"
    source.write_bytes(b"%PDF")

    result = CliRunner().invoke(app, ["import-file", str(source), "--no-index"])

    assert result.exit_code == 1 and "LEARN page link" in result.output
