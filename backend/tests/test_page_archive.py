from pathlib import Path

import pytest
from app.config import Settings
from app.schemas.browser import BrowserPageSnapshot
from app.services import sync_service
from app.services.page_archive import save_pages
from app.services.sync_service import SyncService


def test_a_sync_keeps_the_pages_it_read_and_drops_the_last_syncs(tmp_path: Path) -> None:
    old = tmp_path / "SYDE-252" / "01-gone.txt"
    old.parent.mkdir(parents=True)
    old.write_text("from the sync before")
    pages = [
        BrowserPageSnapshot(url="https://learn.uwaterloo.ca/d2l/home/1318237", text="Home"),
        BrowserPageSnapshot(
            url="https://outline.uwaterloo.ca/viewer/view/nrzht7",
            title="SYDE 252",
            text="#2\nOctober 9, 2026",
        ),
        # The same page read twice is kept once.
        BrowserPageSnapshot(url="https://learn.uwaterloo.ca/d2l/home/1318237", text="Home"),
    ]

    folder = save_pages(tmp_path, "SYDE 252", pages)

    assert folder == tmp_path / "SYDE-252"
    assert sorted(path.name for path in folder.iterdir()) == [
        "01-learn-uwaterloo-ca-d2l-home-1318237.txt",
        "02-outline-uwaterloo-ca-viewer-view-nrzht7.txt",
    ]
    outline = (folder / "02-outline-uwaterloo-ca-viewer-view-nrzht7.txt").read_text()
    assert outline == (
        "URL: https://outline.uwaterloo.ca/viewer/view/nrzht7\nTITLE: SYDE 252\n\n"
        "#2\nOctober 9, 2026"
    )


def test_a_sync_carries_on_when_the_pages_cant_be_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The pages folder once belonged to root after Docker created it for a mount.
    blocked = tmp_path / "pages"
    blocked.write_text("a file where the folder should be")
    monkeypatch.setattr(
        sync_service, "save_pages", lambda root, label, pages: save_pages(blocked, label, pages)
    )
    messages: list[str] = []

    SyncService(Settings(_env_file=None), progress=messages.append)._keep_pages("SYDE 252", [])

    assert messages[0].startswith("WARNING could not keep the pages read for SYDE 252")
