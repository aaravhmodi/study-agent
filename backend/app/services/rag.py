"""OpenAI hosted vector-store indexing and grounded course Q&A."""

import json
import logging
import time
from pathlib import Path
from typing import Any, cast

from openai import BadRequestError, NotFoundError, OpenAI
from sqlalchemy import select

from app.config import Settings
from app.db.database import SessionLocal, ensure_schema
from app.models import Course, Resource
from app.schemas.chat import ChatResponse

logger = logging.getLogger(__name__)


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

    def index_resources(
        self, rows: list[tuple[Resource, Course]]
    ) -> tuple[str, int, int, int]:
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
        return vector_store_id, indexed, skipped, failed

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
            if existing and existing.get("content_hash") == resource.content_hash:
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
            }
            indexed += 1
        return indexed, skipped, failed

    def ask(self, question: str, course_code: str | None = None) -> ChatResponse:
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
        scope = f" Focus on course {normalized_course_code}." if normalized_course_code else ""
        prompt = (
            "You are StudyAgent, a careful university study tutor. Answer using the uploaded "
            "course materials as the source of truth. Give a detailed, teachable explanation: "
            "define terms, connect ideas, show formulas or worked examples when supported, "
            "and end with a short prioritized study checklist. If the materials do not support "
            "a claim, say that clearly instead of guessing. Cite supporting filenames inline "
            "like [filename]." + scope + "\n\nStudent question:\n" + question
        )
        file_search: dict[str, Any] = {
            "type": "file_search",
            "vector_store_ids": [str(vector_store_id)],
        }
        if normalized_course_code:
            file_search["filters"] = {
                "type": "eq",
                "key": "course_code",
                "value": normalized_course_code,
            }
        response = self.client.responses.create(
            model=self.settings.openai_model,
            input=prompt,
            tools=cast(Any, [file_search]),
        )
        answer = str(getattr(response, "output_text", "")).strip()
        if not answer:
            raise RuntimeError("OpenAI returned an empty answer")
        citations = _citations(response)
        return ChatResponse.model_validate({"answer": answer, "citations": citations})

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
