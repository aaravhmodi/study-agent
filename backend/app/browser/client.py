import asyncio
import json
import logging
import shutil
import subprocess
from abc import ABC, abstractmethod
from typing import Any, TypeVar

from pydantic import BaseModel

from app.config import Settings
from app.schemas.sync import BrowserTestResult

logger = logging.getLogger(__name__)
ModelT = TypeVar("ModelT", bound=BaseModel)


class BrowserClientError(RuntimeError):
    """Raised when the Browser Use harness cannot complete a safe operation."""


class BrowserClient(ABC):
    @abstractmethod
    async def run_task(
        self, objective: str, output_schema: type[ModelT] | None = None
    ) -> ModelT | dict[str, Any]:
        """Run a read-only browser task and validate structured output when requested."""

    @abstractmethod
    async def test_connection(self) -> BrowserTestResult:
        """Verify browser attachment and LEARN reachability without changing page state."""


class MockBrowserClient(BrowserClient):
    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.payload = payload or {}

    async def run_task(
        self, objective: str, output_schema: type[ModelT] | None = None
    ) -> ModelT | dict[str, Any]:
        del objective
        return output_schema.model_validate(self.payload) if output_schema else self.payload

    async def test_connection(self) -> BrowserTestResult:
        return BrowserTestResult(
            browser_connected=True,
            learn_reachable=True,
            url="https://learn.uwaterloo.ca",
            title="Mock Waterloo LEARN",
            message="Mock browser mode is active.",
        )


class BrowserUseClient(BrowserClient):
    """Adapter for the current Browser Use CLI local Chrome harness.

    Browser Use CLI is the browser-control layer. Semantic task execution will be
    added in the course-agent milestone; this milestone uses its read-only probe.
    """

    def __init__(self, settings: Settings, executable: str | None = None) -> None:
        self.settings = settings
        local_executable = (
            settings.project_root / ".browser-use-venv" / "Scripts" / "browser-use.exe"
        )
        self.executable = executable or (
            str(local_executable) if local_executable.exists() else settings.browser_use_executable
        )

    def is_installed(self) -> bool:
        return shutil.which(self.executable) is not None

    async def run_task(
        self, objective: str, output_schema: type[ModelT] | None = None
    ) -> ModelT | dict[str, Any]:
        logger.info("Running read-only browser probe for objective: %s", objective[:120])
        result = await self.test_connection()
        if output_schema is None:
            return result.model_dump()
        return output_schema.model_validate(result.model_dump())

    async def test_connection(self) -> BrowserTestResult:
        if not self.is_installed():
            raise BrowserClientError(
                "Browser Use CLI was not found. Install it with uv tool install and run "
                "browser-use skill install."
            )
        completed = await asyncio.to_thread(
            _run_cli, self.executable, _probe_script(self.settings.learn_url)
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or "unknown Browser Use error"
            raise BrowserClientError(f"Browser Use failed: {detail[-2000:]}")
        try:
            return BrowserTestResult.model_validate(_extract_result(completed.stdout))
        except Exception as exc:
            raise BrowserClientError(f"Browser Use returned invalid probe output: {exc}") from exc


def _run_cli(executable: str, script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [executable],
        input=script,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )


def _extract_result(stdout: str) -> dict[str, Any]:
    marker = "STUDY_AGENT_RESULT="
    for line in reversed(stdout.splitlines()):
        if line.startswith(marker):
            value = json.loads(line.removeprefix(marker))
            if not isinstance(value, dict):
                raise BrowserClientError("Browser Use probe did not return an object")
            return value
    raise BrowserClientError("Browser Use probe did not return a structured result")


def _probe_script(learn_url: str) -> str:
    encoded_url = json.dumps(learn_url)
    return f"""import json
from urllib.parse import urlsplit, urlunsplit

target_url = {encoded_url}
tabs = list_tabs()
matching = [tab for tab in tabs if target_url.split('/')[2] in str(tab.get('url', ''))]
if matching:
    switch_tab(matching[0].get('id') or matching[0].get('index') or matching[0])
else:
    new_tab(target_url)
wait_for_load()
info = page_info()
url = str(info.get('url', ''))
parsed = urlsplit(url)
safe_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))
safe_title = ''.join(
    character for character in str(info.get('title') or '') if ord(character) < 128
)
print('STUDY_AGENT_RESULT=' + json.dumps({{
    'browser_connected': True,
    'learn_reachable': (parsed.hostname or '').lower() == 'learn.uwaterloo.ca',
    'url': safe_url or None,
    'title': safe_title or None,
    'message': 'Read-only Browser Use probe completed.'
}}))
"""
