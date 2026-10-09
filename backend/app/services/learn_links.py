"""Turn the links saved for course files into pages a student can open on LEARN."""

import re
from urllib.parse import urlsplit

# The collector saves D2L's download API URL; the viewer page shows the same topic in LEARN.
_TOPIC_FILE = re.compile(r"^/d2l/api/le/[\d.]+/(\d+)/content/topics/(\d+)/file/?$")


_TOPIC_VIEW = re.compile(r"^/d2l/le/content/(\d+)/viewContent/(\d+)/View/?$", re.IGNORECASE)


def topic_key(url: str | None) -> tuple[str, str] | None:
    """(course id, topic id) from a LEARN viewer or download link, else None."""

    if not url:
        return None
    path = urlsplit(url.strip()).path
    match = _TOPIC_FILE.match(path) or _TOPIC_VIEW.match(path)
    return (match.group(1), match.group(2)) if match else None


def viewer_url(url: str | None) -> str | None:
    """The page to open for a source, or None if the link is missing or not http(s)."""

    if not url:
        return None
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    topic = _TOPIC_FILE.match(parts.path)
    if topic:
        course, topic_id = topic.groups()
        return (
            f"{parts.scheme}://{parts.netloc}/d2l/le/content/{course}/viewContent/{topic_id}/View"
        )
    return url.strip()
