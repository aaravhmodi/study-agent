"""Attach a file the student downloaded themselves to the LEARN item it came from.

Some items (a whole textbook) are too large for the browser download path, which
skips anything over 15 MB. The student downloads them from LEARN once, and this
records the copy against the same resource so it is indexed and cited with its
LEARN title and link like any synced file.
"""

import hashlib
import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Course, Resource
from app.services.document_collector import safe_name
from app.services.learn_links import topic_key
from app.services.pdf_text import write_pdf_text_sidecar


class ImportFileError(ValueError):
    """The file or the LEARN link cannot be matched."""


def find_resource(session: Session, link: str) -> tuple[Resource, Course]:
    """The synced resource for a LEARN viewer or download link, preferring active courses."""

    key = topic_key(link)
    if key is None:
        raise ImportFileError("not a LEARN content link (…/viewContent/<id>/View)")
    course_id, topic_id = key
    pattern = f"%/{course_id}/content/topics/{topic_id}/%"
    rows = session.execute(
        select(Resource, Course).join(Course).where(Resource.url.like(pattern))
    ).all()
    if not rows:
        raise ImportFileError("no synced LEARN item has that link; run `study-agent sync` first")
    resource, course = max(rows, key=lambda row: row[1].active)
    return resource, course


def import_file(session: Session, downloads_dir: Path, source: Path, link: str) -> Resource:
    """Copy ``source`` into the downloads folder as the file for the LEARN item at ``link``."""

    if not source.is_file():
        raise ImportFileError(f"file not found: {source}")
    resource, _course = find_resource(session, link)
    content = source.read_bytes()
    if not content:
        raise ImportFileError("file is empty")
    suffix = source.suffix.lower() or ".bin"
    target = downloads_dir / f"{resource.id}_{safe_name(resource.title)}{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != target.resolve():
        shutil.copyfile(source, target)
    if suffix == ".pdf":
        write_pdf_text_sidecar(target)
    resource.local_path = str(target)
    resource.content_hash = hashlib.sha256(content).hexdigest()
    resource.processed = True
    session.commit()
    return resource
