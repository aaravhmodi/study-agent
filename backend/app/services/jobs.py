"""A bounded, in-process FIFO for dashboard sync and index work."""

import logging
import threading
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.logging import redact

logger = logging.getLogger(__name__)
MAX_LINES = 400
MAX_QUEUED = 8
Work = Callable[[Callable[[str], None]], str]


class JobLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    at: datetime
    text: str


class JobStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = ""
    state: Literal["idle", "running", "done", "failed"] = "idle"
    message: str = ""
    lines: list[JobLine] = Field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    queued: list[str] = Field(default_factory=list)


class JobRunner:
    """Runs one task at a time and keeps up to MAX_QUEUED requests in FIFO order."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status = JobStatus()
        self._pending: deque[tuple[str, Work]] = deque()
        self._worker: threading.Thread | None = None

    def status(self) -> JobStatus:
        with self._lock:
            result = self._status.model_copy(deep=True)
            result.queued = [name for name, _ in self._pending]
            return result

    def start(self, name: str, work: Work) -> bool:
        """Enqueue work; False means the bounded waiting queue is full."""
        with self._lock:
            if self._worker is not None:
                if len(self._pending) >= MAX_QUEUED:
                    return False
                self._pending.append((name, work))
                return True
            self._status = JobStatus(name=name, state="running", started_at=datetime.now(UTC))
            first = (name, work)
            self._worker = threading.Thread(
                target=self._run_queue, args=(first,), name="job-worker", daemon=True
            )
            self._worker.start()
            return True

    def _run_queue(self, task: tuple[str, Work]) -> None:
        current = task
        while True:
            name, work = current
            try:
                message, state = work(self._progress), "done"
            except Exception as exc:
                logger.warning("Dashboard task failed (%s)", type(exc).__name__)
                message, state = redact(str(exc)) or type(exc).__name__, "failed"
            with self._lock:
                self._status.message = message
                self._status.state = state
                self._status.finished_at = datetime.now(UTC)
                if not self._pending:
                    self._worker = None
                    return
                name, work = self._pending.popleft()
                current = (name, work)
                self._status = JobStatus(name=name, state="running", started_at=datetime.now(UTC))

    def _progress(self, line: str) -> None:
        with self._lock:
            entry = JobLine(at=datetime.now(UTC), text=redact(line))
            self._status.lines = [*self._status.lines, entry][-MAX_LINES:]
