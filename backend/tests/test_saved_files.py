from pathlib import Path

from app.services.saved_files import saved_file


def test_a_recorded_path_that_is_here_is_used_as_it_is(tmp_path: Path) -> None:
    elsewhere = tmp_path / "imports" / "notes.pdf"
    elsewhere.parent.mkdir()
    elsewhere.write_bytes(b"%PDF")

    assert saved_file(str(elsewhere), tmp_path / "downloads") == elsewhere


def test_a_path_from_another_machine_is_found_by_name(tmp_path: Path) -> None:
    downloads = tmp_path / "downloads"

    from_windows = saved_file(r"C:\Users\someone\agent\data\downloads\abc_Lecture-1.pdf", downloads)
    from_linux = saved_file("/app/data/downloads/abc_Lecture-1.pdf", downloads)

    assert from_windows == from_linux == downloads / "abc_Lecture-1.pdf"


def test_nothing_recorded_means_no_file(tmp_path: Path) -> None:
    assert saved_file(None, tmp_path) is None
    assert saved_file("", tmp_path) is None
