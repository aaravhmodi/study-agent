"""One long task at a time for the dashboard, run in the background.

A sync or an index takes minutes, so the dashboard starts it here and asks how it is
going. Only the latest task is remembered, and only until the server restarts.
"""

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.logging import redact

logger = logging.getLogger(__name__)

MAX_LINES = 400

# A task reports progress through the function it is given and returns its result.
Work = Callable[[Callable[[str], None]], str]


class JobLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at: datetime
    text: str


class JobStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = ""
    state: Literal["idle", "running", "done", "failed"] = "idle"
    # The result of a finished task, or why it failed.
    message: str = ""
    # What the task has reported so far, oldest first (the latest MAX_LINES).
    lines: list[JobLine] = []
    started_at: datetime | None = None
    finished_at: datetime | None = None


class JobRunner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status = JobStatus()

    def status(self) -> JobStatus:
        with self._lock:
            return self._status.model_copy(deep=True)

    def start(self, name: str, work: Work) -> bool:
        """Run ``work`` in the background; False when another task is still running."""

        with self._lock:
            if self._status.state == "running":
                return False
            self._status = JobStatus(name=name, state="running", started_at=datetime.now(UTC))
        threading.Thread(target=self._run, args=(work,), name=f"job-{name}", daemon=True).start()
        return True

    def _run(self, work: Work) -> None:
        try:
            message, state = work(self._progress), "done"
        except Exception as exc:  # the task's failure is the result to report
            logger.warning("Dashboard task failed (%s)", type(exc).__name__)
            message, state = redact(str(exc)) or type(exc).__name__, "failed"
        with self._lock:
            self._status.message = message
            self._status.state = "done" if state == "done" else "failed"
            self._status.finished_at = datetime.now(UTC)

    def _progress(self, line: str) -> None:
        with self._lock:
            entry = JobLine(at=datetime.now(UTC), text=redact(line))
            self._status.lines = [*self._status.lines, entry][-MAX_LINES:]
