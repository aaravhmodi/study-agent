"""Keep the text of the pages a sync read, one folder per course.

When a deadline is misread, the page it came from is right there to compare against,
without opening LEARN again: data/pages/SYDE-252/03-outline.uwaterloo.ca-viewer-view-nrzht7.txt
"""

import re
import shutil
from pathlib import Path

from app.schemas.browser import BrowserPageSnapshot


def _slug(text: str, limit: int = 80) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")[:limit] or "page"


def save_pages(root: Path, label: str, pages: list[BrowserPageSnapshot]) -> Path:
    """Replace the label's folder with these pages, in the order they were read."""

    folder = root / _slug(label)
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    seen: set[str] = set()
    for page in pages:
        address = re.sub(r"^https?://", "", page.url)
        if address in seen:
            continue
        seen.add(address)
        name = f"{len(seen):02d}-{_slug(address)}.txt"
        header = f"URL: {page.url}\nTITLE: {page.title or ''}\n\n"
        (folder / name).write_text(header + page.text, encoding="utf-8")
    return folder
