"""OpenAI hosted vector-store indexing and grounded course Q&A."""

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, cast

from openai import BadRequestError, NotFoundError, OpenAI
from sqlalchemy import select

from app.config import Settings
from app.db.database import SessionLocal, ensure_schema
from app.models import Course, Resource
from app.schemas.chat import ChatCitation, ChatResponse, ChatUsage
from app.schemas.chat_session import ChatTurn
from app.services.answer_cache import AnswerCache, cache_key, index_fingerprint
from app.services.answer_format import clean_answer, clean_citations, display_filename
from app.services.course_notes import NOTES_FILE, course_in_question, tutor_notes
from app.services.figure_guide import FIGURE_GUIDE
from app.services.figures import extract_figures
from app.services.learn_links import viewer_url
from app.services.lecture_scope import lecture_refs, matching_resource_ids
from app.services.pdf_text import passage_pages, refresh_pdf_text_sidecar
from app.services.question_sources import SOURCE_GUIDE, SourceDocument, SourceResolver
from app.services.retrieval import (
    Passage,
    cited_files,
    format_passages,
    from_search,
    select_passages,
)
from app.services.textbook_toc import Chapter, chapters, describe, parse_contents

logger = logging.getLogger(__name__)

# Requests sharing the tutor prefix are routed together so the prefix stays cached.
_CACHE_KEY = "study-agent-tutor"
# Earlier exchanges sent with a follow-up question.
FOLLOW_UP_TURNS = 3

# Smaller, less overlapping chunks than OpenAI's default (800 tokens, 400 overlap):
# the same context budget then holds more distinct, more focused passages.
CHUNK_TOKENS = 400
CHUNK_OVERLAP_TOKENS = 100
CHUNKING = f"static-{CHUNK_TOKENS}-{CHUNK_OVERLAP_TOKENS}"


TUTOR_GUIDE = """\
You are StudyAgent, a university study tutor. The course passages in the input are the \
source of truth: use their notation, sign conventions and examples. Use web search only to \
add context the materials lack (intuition, real-world uses, a clearer derivation), mark \
those sentences "(online)", and never let them contradict the course. If neither supports \
a claim, say so instead of guessing.

When asked to explain a topic or a lecture, find the chapter or lecture it belongs to and \
teach it concept by concept. Use this Markdown layout:
## Overview
Two or three sentences: what it is, why it matters, which lecture or chapter covers it.
## Key concepts
One ### heading per concept (usually 3 to 6), in teaching order. For each: a \
plain-language definition, the governing formula, and how it links to the others.
## Worked example
One short example in numbered steps, from the materials when possible. If its result is a \
function, a diagram or a circuit, end with a figure of it.
## Common mistakes
Two to four bullets.
## Check yourself
Three short questions that test understanding, not recall, each followed by its answer \
hidden like this:
<details><summary>Answer</summary>

One or two sentences.

</details>
## Study checklist
Three to five prioritized bullets, including when to revisit (tomorrow, next week).

If the question looks like a graded assignment or lab problem, do not solve it: explain \
the concepts and give the first step as a hint. Solve practice and self-study problems \
fully: setup figure, steps, then solution figure. For other questions, answer directly \
with only the sections that help. Instructor notes, when given, set exam scope and format: \
say whether the topic is in scope, and write Check yourself questions in that format \
(for multiple choice: four options, one correct). Work out every answer and calculation \
before writing it, so answer keys never need a correction.

Style: short paragraphs, **bold** key terms, LaTeX math with \\( ... \\) inline and \\[ ... \\] \
for display (units like \\text{kN}\\cdot\\text{m}, no Unicode symbols inside \\text{}), and \
cite course files inline by exact filename and page, one file per bracket: \
[Textbook.pdf, p. 12]. Be concise.\
"""

# One static prefix (cached by OpenAI after the first question): how to teach, how to
# cite course questions, then how to draw.
TUTOR_INSTRUCTIONS = TUTOR_GUIDE + "\n\n" + SOURCE_GUIDE + "\n\n" + FIGURE_GUIDE


class VectorFileError(RuntimeError):
    """A single uploaded file could not be processed by the vector store."""


class RagService:
    def __init__(self, settings: Settings, client: OpenAI | None = None) -> None:
        if not settings.openai_api_key and client is None:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        self.settings = settings
        # Uploads occasionally hit connection resets; the SDK's exponential
        # backoff (0.5s doubling to 8s) rides those out with a few more tries.
        self.client = client or OpenAI(api_key=settings.openai_api_key, max_retries=6)
        self.manifest_path = settings.data_dir / "rag_manifest.json"
        self.downloads_dir = settings.downloads_dir

    def index_database(self) -> tuple[str, int, int, int]:
        ensure_schema()
        with SessionLocal() as session:
            rows = session.execute(
                select(Resource, Course)
                .join(Course, Resource.course_id == Course.id)
                .where(Course.active.is_(True))
                .order_by(Course.code, Resource.title)
            ).all()
            return self.index_resources([(resource, course) for resource, course in rows])

    def index_resources(self, rows: list[tuple[Resource, Course]]) -> tuple[str, int, int, int]:
        """Sync saved resources into the vector store; return (id, indexed, skipped, failed)."""
        manifest = self._load_manifest()
        vector_store_id = str(manifest.get("vector_store_id") or self._create_vector_store())
        manifest["vector_store_id"] = vector_store_id
        try:
            indexed, skipped, failed = self._index_into(manifest, vector_store_id, rows)
        finally:
            # Persist deletions and uploads even when a run aborts, so the
            # next run does not repeat them or orphan hosted files.
            self._save_manifest(manifest)
        self._remove_untracked(vector_store_id, manifest.get("files", {}))
        return vector_store_id, indexed, skipped, failed

    def _remove_untracked(self, vector_store_id: str, files: dict[str, Any]) -> None:
        """Delete store files no manifest entry points at (left by earlier failed runs).

        They have no LEARN title or link, and stale copies crowd out current passages.
        """

        tracked = {entry.get("file_id") for entry in files.values()}
        stored = self.client.vector_stores.files.list(vector_store_id, limit=100)
        untracked = [item.id for item in stored if item.id not in tracked]
        for file_id in untracked:
            self._delete_old_file(vector_store_id, file_id)
        if untracked:
            logger.info("Removed %d untracked files from the vector store", len(untracked))

    def _index_into(
        self,
        manifest: dict[str, Any],
        vector_store_id: str,
        rows: list[tuple[Resource, Course]],
    ) -> tuple[int, int, int]:
        indexed = 0
        skipped = 0
        failed = 0
        files = manifest.setdefault("files", {})
        eligible_ids = {
            resource.id
            for resource, _course in rows
            if resource.local_path
            and resource.content_hash
            and Path(resource.local_path).is_file()
            and Path(resource.local_path).suffix.lower() in _INDEXABLE_SUFFIXES
        }
        for resource_id in list(files):
            if resource_id not in eligible_ids:
                self._delete_old_file(vector_store_id, files[resource_id].get("file_id"))
                del files[resource_id]
        for resource, course in rows:
            if not resource.local_path or not resource.content_hash:
                skipped += 1
                continue
            existing = files.get(resource.id)
            if Path(resource.local_path).suffix.lower() == ".pdf":
                # Text extracted before pages were labelled cannot be cited by page.
                refresh_pdf_text_sidecar(Path(resource.local_path))
            upload_hash = _upload_hash(resource.local_path)
            if (
                existing
                and existing.get("content_hash") == resource.content_hash
                and existing.get("chunking") == CHUNKING
                # Re-extracted text (e.g. new page labels) is re-indexed too; entries
                # saved before this was recorded take the current hash.
                and existing.setdefault("upload_hash", upload_hash) == upload_hash
            ):
                # Unchanged file: keep its LEARN title and link current without re-uploading.
                existing["title"] = resource.title
                existing["source_url"] = resource.url
                if "chapters" not in existing:
                    existing["chapters"] = _chapters_of(Path(resource.local_path))
                skipped += 1
                continue
            path = Path(resource.local_path)
            if not path.is_file() or path.suffix.lower() not in _INDEXABLE_SUFFIXES:
                skipped += 1
                continue
            if existing:
                self._delete_old_file(vector_store_id, existing.get("file_id"))
                del files[resource.id]
            upload_path = _local_text_path(path)
            with upload_path.open("rb") as handle:
                uploaded = self.client.files.create(file=handle, purpose="assistants")
            try:
                vector_file = self.client.vector_stores.files.create(
                    vector_store_id=vector_store_id,
                    file_id=uploaded.id,
                    attributes={
                        "course_code": course.code or course.name,
                        "course_name": course.name,
                        "resource_id": resource.id,
                        "resource_type": resource.resource_type,
                    },
                    chunking_strategy={
                        "type": "static",
                        "static": {
                            "max_chunk_size_tokens": CHUNK_TOKENS,
                            "chunk_overlap_tokens": CHUNK_OVERLAP_TOKENS,
                        },
                    },
                )
                self._wait_for_file(vector_store_id, vector_file.id)
            except (VectorFileError, BadRequestError) as exc:
                # One unprocessable document should not abort the whole index.
                failed += 1
                logger.warning(
                    "Could not index %s %r (%s): %s",
                    course.code or course.name,
                    resource.title,
                    upload_path.name,
                    exc,
                )
                self._delete_old_file(vector_store_id, uploaded.id)
                continue
            files[resource.id] = {
                "content_hash": resource.content_hash,
                "file_id": uploaded.id,
                "filename": path.name,
                "course_code": course.code or course.name,
                "source_url": resource.url,
                "title": resource.title,
                "chunking": CHUNKING,
                "upload_hash": upload_hash,
                "chapters": _chapters_of(path),
            }
            indexed += 1
        return indexed, skipped, failed

    def ask(
        self,
        question: str,
        course_code: str | None = None,
        *,
        fresh: bool = False,
        history: list[ChatTurn] | None = None,
    ) -> ChatResponse:
        manifest = self._load_manifest()
        vector_store_id = manifest.get("vector_store_id")
        if not vector_store_id:
            raise RuntimeError("No vector store found. Run `study-agent rag-index` first.")
        normalized_course_code = course_code.strip().upper() if course_code else None
        if normalized_course_code and not any(
            str(item.get("course_code", "")).upper() == normalized_course_code
            for item in manifest.get("files", {}).values()
        ):
            raise RuntimeError(
                f"No indexed materials found for {normalized_course_code}. "
                "Sign in to LEARN, run `study-agent sync`, then `study-agent rag-index`."
            )
        files = manifest.get("files", {})
        cache = AnswerCache(self.manifest_path.with_name("answer_cache.json"))
        note_course = normalized_course_code or course_in_question(
            question, {str(entry.get("course_code", "")).upper() for entry in files.values()}
        )
        note = tutor_notes(self.notes_path, note_course)
        key = cache_key(question, normalized_course_code, settings=self._answer_shape(files, note))
        earlier = (history or [])[-FOLLOW_UP_TURNS:]
        # A follow-up depends on the conversation, so it is never served from the cache.
        if not fresh and not earlier and (saved := cache.get(key)):
            return saved.model_copy(update={"cached": True, "usage": None})
        lecture_ids = matching_resource_ids(question, files, normalized_course_code)
        context = []
        if normalized_course_code:
            context.append(f"Course: {normalized_course_code}")
        if note:
            context.append(
                f"Instructor notes for {note_course} (what the professor said, saved by the "
                f"student; newest first):\n{note}"
            )
        named_chapters = _chapter_numbers(question)
        outline = _chapter_outline(
            files, note_course, named_chapters | _chapter_numbers(note or "")
        )
        if outline:
            context.append(outline)
        if lecture_ids:
            names = ", ".join(
                display_filename(str(files[resource_id].get("filename", "")))
                for resource_id in lecture_ids
            )
            context.append(f"Lecture files: {names}")
        if earlier:
            context.append(
                "Earlier in this conversation (answer the new question as a follow-up; "
                "do not repeat what was already explained):"
            )
            for turn in earlier:
                context.append(f"Student: {turn.question}\nTutor: {_brief(turn.response.answer)}")
            context.append(f"New question: {question}")
        else:
            context.append(f"Question: {question}")
        # A short follow-up ("why?") is searched together with the question it follows.
        search_text = f"{earlier[-1].question}\n{question}" if earlier else question
        # "Chapter 3" means nothing to semantic search; its title and sections do.
        search_text += _chapter_search_terms(files, note_course, named_chapters)
        passages, documents = self._located(
            self._passages(search_text, str(vector_store_id), normalized_course_code, lecture_ids),
            files,
        )
        context.append("")
        context.append(format_passages(passages))
        tools: list[dict[str, Any]] = []
        if self.settings.rag_web_search:
            tools.append({"type": "web_search", "search_context_size": "low"})
        response = self.client.responses.create(
            model=self.settings.openai_chat_model,
            # Static instructions form a stable prefix that OpenAI can cache.
            instructions=TUTOR_INSTRUCTIONS,
            input="\n".join(context),
            tools=cast(Any, tools),
            # One web search at most; course passages are already in the input.
            max_tool_calls=1,
            prompt_cache_key=_CACHE_KEY,
            reasoning=cast(Any, {"effort": self.settings.openai_chat_reasoning_effort}),
            max_output_tokens=self.settings.rag_max_output_tokens,
        )
        answer = clean_answer(str(getattr(response, "output_text", "")))
        if not answer:
            raise RuntimeError("OpenAI returned an empty answer")
        if _hit_output_limit(response):
            answer += "\n\n_Answer cut short by the length limit; ask about one concept at a time._"
        # Files named only in a source block count as cited, so look before blocks are swapped.
        course_files = [_with_learn_link(item, files) for item in cited_files(answer, passages)]
        answer, figures = extract_figures(answer, SourceResolver(documents))
        citations = clean_citations(course_files + _citations(response))
        result = ChatResponse(
            answer=answer,
            citations=[ChatCitation.model_validate(citation) for citation in citations],
            figures=figures,
            usage=_usage(response),
        )
        if not earlier:
            cache.put(key, result)
        return result

    def _located(
        self, passages: list[Passage], files: dict[str, Any]
    ) -> tuple[list[Passage], list[SourceDocument]]:
        """Name each passage by its course file and page, and list the files in hand.

        Search results carry the uploaded text file's name and no page for a passage
        that starts mid-page; the saved file and its extracted text supply both.
        """

        resource_ids = {
            str(entry.get("file_id")): str(resource_id)
            for resource_id, entry in files.items()
            if entry.get("file_id")
        }
        root = self.downloads_dir.resolve()
        located: list[Passage] = []
        documents: dict[str, SourceDocument] = {}
        for passage in passages:
            resource_id = passage.resource_id or resource_ids.get(passage.file_id)
            entry = files.get(resource_id) if resource_id else None
            if not resource_id or not entry or not entry.get("filename"):
                located.append(passage)
                continue
            saved = (root / str(entry["filename"])).resolve()
            is_pdf = (
                saved.suffix.lower() == ".pdf" and saved.is_relative_to(root) and saved.is_file()
            )
            pages = passage_pages(saved.with_suffix(".txt"), passage.text) if is_pdf else []
            text = passage.text
            if pages and not text.startswith("[Page "):
                text = f"[Page {pages[0]}]\n{text}"
            filename = display_filename(str(entry["filename"]))
            located.append(
                passage.model_copy(update={"filename": filename, "text": text, "pages": pages})
            )
            document = documents.setdefault(
                resource_id,
                SourceDocument(
                    resource_id=resource_id,
                    filename=filename,
                    title=str(entry.get("title") or "").strip() or filename,
                    url=viewer_url(entry.get("source_url")),
                    pdf=saved if is_pdf else None,
                    chapters=[Chapter.model_validate(raw) for raw in entry.get("chapters") or []],
                ),
            )
            document.pages += [page for page in pages if page not in document.pages]
        return located, list(documents.values())

    @property
    def notes_path(self) -> Path:
        return self.manifest_path.with_name(NOTES_FILE)

    def _answer_shape(self, files: dict[str, Any], note: str | None = None) -> dict[str, Any]:
        """Everything besides the question that changes what an answer looks like."""

        settings = self.settings
        return {
            "model": settings.openai_chat_model,
            "effort": settings.openai_chat_reasoning_effort,
            "max_output": settings.rag_max_output_tokens,
            "passages": [settings.rag_max_results, settings.rag_context_tokens],
            "min_score": settings.rag_min_score,
            "web": settings.rag_web_search,
            "prompt": hashlib.sha256(TUTOR_INSTRUCTIONS.encode("utf-8")).hexdigest()[:16],
            "index": index_fingerprint(files),
            "note": hashlib.sha256((note or "").encode("utf-8")).hexdigest()[:16],
            # Bump when the saved response format changes (4: course questions shown
            # from the student's files).
            "format": 4,
        }

    def _passages(
        self,
        question: str,
        vector_store_id: str,
        course_code: str | None,
        lecture_ids: list[str],
    ) -> list[Passage]:
        """Search the course index once and keep the best distinct passages."""

        search: dict[str, Any] = {
            "query": question,
            # Over-fetch: duplicates and repeats from one file are dropped below.
            "max_num_results": min(self.settings.rag_max_results * 3, 50),
            "rewrite_query": True,
            "ranking_options": {"score_threshold": self.settings.rag_min_score},
        }
        filters = _file_filters(course_code, lecture_ids)
        if filters:
            search["filters"] = filters
        results = self.client.vector_stores.search(vector_store_id, **search)
        return select_passages(
            from_search(results.data),
            budget_tokens=self.settings.rag_context_tokens,
            max_passages=self.settings.rag_max_results,
        )

    def _create_vector_store(self) -> str:
        vector_store = self.client.vector_stores.create(name="StudyAgent course materials")
        return str(vector_store.id)

    def _wait_for_file(self, vector_store_id: str, vector_file_id: str) -> None:
        for _ in range(120):
            current = self.client.vector_stores.files.retrieve(
                vector_file_id, vector_store_id=vector_store_id
            )
            status = str(getattr(current, "status", ""))
            if status == "completed":
                return
            if status in {"failed", "cancelled"}:
                last_error = getattr(current, "last_error", None)
                reason = getattr(last_error, "message", None) or "no reason given"
                raise VectorFileError(f"Vector-store file processing {status}: {reason}")
            time.sleep(0.5)
        raise VectorFileError("Timed out waiting for vector-store file processing")

    def _delete_old_file(self, vector_store_id: str, file_id: Any) -> None:
        if not file_id:
            return
        # Detach and delete independently: either may already be gone after
        # an interrupted run, which should not leave the other behind.
        try:
            self.client.vector_stores.files.delete(file_id, vector_store_id=vector_store_id)
        except NotFoundError:
            pass
        except Exception:
            logger.warning("Could not detach a stale indexed file", exc_info=True)
        try:
            self.client.files.delete(file_id)
        except NotFoundError:
            pass
        except Exception:
            logger.warning("Could not remove a stale indexed file", exc_info=True)

    def _load_manifest(self) -> dict[str, Any]:
        if not self.manifest_path.is_file():
            return {"files": {}}
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {"files": {}}
        except (OSError, json.JSONDecodeError):
            return {"files": {}}

    def _save_manifest(self, manifest: dict[str, Any]) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _file_filters(course_code: str | None, resource_ids: list[str]) -> dict[str, Any] | None:
    """Limit file search to a course and, when a lecture is named, to its files."""

    course = {"type": "eq", "key": "course_code", "value": course_code} if course_code else None
    if not resource_ids:
        return course
    lectures: dict[str, Any] = {
        "type": "or",
        "filters": [
            {"type": "eq", "key": "resource_id", "value": resource_id}
            for resource_id in resource_ids
        ],
    }
    if len(resource_ids) == 1:
        lectures = lectures["filters"][0]
    return {"type": "and", "filters": [course, lectures]} if course else lectures


def _chapters_of(path: Path) -> list[dict[str, Any]]:
    """Chapters from a document's table of contents, if it has one."""

    text_path = _local_text_path(path)
    if text_path.suffix.lower() not in {".txt", ".md"}:
        return []
    try:
        text = text_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    return [chapter.model_dump() for chapter in chapters(parse_contents(text))]


def _chapter_numbers(text: str) -> set[int]:
    return {number for family, number in lecture_refs(text) if family == "chapter"}


def _course_chapters(
    files: dict[str, Any], course_code: str | None, wanted: set[int]
) -> list[tuple[str, Chapter]]:
    """(book title, chapter) for the wanted chapters of the course's textbooks."""

    found: list[tuple[str, Chapter]] = []
    for entry in files.values():
        if course_code and str(entry.get("course_code", "")).upper() != course_code:
            continue
        book = str(entry.get("title") or display_filename(str(entry.get("filename", ""))))
        for raw in entry.get("chapters") or []:
            chapter = Chapter.model_validate(raw)
            if chapter.number in wanted:
                found.append((book, chapter))
    return found[:12]


def _chapter_outline(files: dict[str, Any], course_code: str | None, wanted: set[int]) -> str:
    found = _course_chapters(files, course_code, wanted)
    if not found:
        return ""
    lines = [f"[{book}] {describe(chapter)}" for book, chapter in found]
    return "Textbook chapters named here (from the book's table of contents):\n" + "\n".join(lines)


def _chapter_search_terms(files: dict[str, Any], course_code: str | None, wanted: set[int]) -> str:
    found = _course_chapters(files, course_code, wanted)
    return "".join(
        f"\n{chapter.title}: "
        + ", ".join(section.split(" ", 1)[-1] for section in chapter.sections)
        for _book, chapter in found[:3]
    )


def _upload_hash(local_path: str | None) -> str | None:
    """Hash of the bytes rag-index uploads for a file (its text sidecar when it has one)."""

    if not local_path or not Path(local_path).is_file():
        return None
    return hashlib.sha256(_local_text_path(Path(local_path)).read_bytes()).hexdigest()


def _brief(answer: str, limit: int = 800) -> str:
    """An earlier answer, without figures or hidden quiz answers, shortened for context."""

    text = re.sub(r"```figure\s*\d+\s*```", " ", answer)
    text = re.sub(r"<details>[\s\S]*?</details>", " ", text)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _usage(response: Any) -> ChatUsage | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    details = getattr(usage, "input_tokens_details", None)
    return ChatUsage(
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        cached_tokens=int(getattr(details, "cached_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
    )


def _hit_output_limit(response: Any) -> bool:
    details = getattr(response, "incomplete_details", None)
    return getattr(response, "status", None) == "incomplete" and (
        getattr(details, "reason", None) == "max_output_tokens"
    )


def _with_learn_link(
    citation: dict[str, str | None], files: dict[str, Any]
) -> dict[str, str | None]:
    """Add the LEARN title and page of the indexed file a citation came from."""

    entry = next((e for e in files.values() if e.get("file_id") == citation.get("file_id")), None)
    if entry is None:
        return citation
    title = str(entry.get("title") or "").strip() or None
    return {**citation, "title": title, "url": viewer_url(entry.get("source_url"))}


def _citations(response: Any) -> list[dict[str, str | None]]:
    """Extract file citations from an SDK response without logging its contents."""
    payload = response.model_dump() if hasattr(response, "model_dump") else {}
    found: list[dict[str, str | None]] = []
    seen: set[tuple[str, str | None]] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            kind = value.get("type")
            if kind in {"file_citation", "file_search_result"}:
                filename = value.get("filename") or value.get("file_name")
                file_id = value.get("file_id")
                if isinstance(filename, str):
                    key = (filename, file_id if isinstance(file_id, str) else None)
                    if key not in seen:
                        seen.add(key)
                        found.append({"filename": filename, "file_id": key[1]})
            elif kind == "url_citation":
                url = value.get("url")
                if isinstance(url, str) and url.startswith(("https://", "http://")):
                    title = value.get("title")
                    key = (url, None)
                    if key not in seen:
                        seen.add(key)
                        name = title if isinstance(title, str) else url
                        found.append({"filename": name, "title": name, "url": url, "kind": "web"})
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return found


def _local_text_path(path: Path) -> Path:
    """Prefer the text extracted beside a PDF, while retaining PDF fallback."""

    if path.suffix.lower() == ".pdf":
        sidecar = path.with_suffix(".txt")
        if sidecar.is_file() and sidecar.stat().st_size:
            return sidecar
    return path


# Extensions accepted by OpenAI file search; spreadsheets (.csv, .xlsx) are not.
# https://developers.openai.com/api/docs/guides/tools-file-search
_INDEXABLE_SUFFIXES = {
    ".c",
    ".cpp",
    ".css",
    ".doc",
    ".docx",
    ".html",
    ".java",
    ".js",
    ".json",
    ".md",
    ".pdf",
    ".php",
    ".pptx",
    ".py",
    ".rb",
    ".tex",
    ".ts",
    ".txt",
}
