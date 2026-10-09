"""Clean model answers and citations before they are shown to the student."""

import re

# File-search answers can embed citation markers such as
# "fileciteturn0file3" that only OpenAI's own UI renders.
_CITATION_MARKER = re.compile(
    r"[-]*filecite(?:[-]*turn\d+file\d+)+[-]*"
)
_PRIVATE_USE = re.compile(r"[-]")
_SPACE_BEFORE_PUNCTUATION = re.compile(r"[ \t]+([.,;:!?])")
_TRAILING_SPACE = re.compile(r"[ \t]+$", flags=re.MULTILINE)
# Saved downloads are named "<resource uuid>_<title>.<ext>".
_UPLOAD_PREFIX = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_", flags=re.IGNORECASE
)


def clean_answer(text: str) -> str:
    """Remove hosted-UI citation markers that would render as stray text."""

    text = _CITATION_MARKER.sub("", text)
    text = _PRIVATE_USE.sub("", text)
    text = _SPACE_BEFORE_PUNCTUATION.sub(r"\1", text)
    return _TRAILING_SPACE.sub("", text).strip()


def display_filename(filename: str) -> str:
    """Drop the resource-id prefix the collector adds to saved filenames."""

    return _UPLOAD_PREFIX.sub("", filename)


def clean_citations(citations: list[dict[str, str | None]]) -> list[dict[str, str | None]]:
    """Show each source once, by its readable filename."""

    seen: set[str] = set()
    cleaned: list[dict[str, str | None]] = []
    for citation in citations:
        filename = display_filename(str(citation.get("filename") or ""))
        url = citation.get("url")
        key = url or filename
        if not filename or key in seen:
            continue
        seen.add(key)
        if url:
            cleaned.append({"filename": filename, "url": url})
        else:
            cleaned.append({"filename": filename, "file_id": citation.get("file_id")})
    return cleaned
