import subprocess

import pytest
from app.browser.client import (
    BrowserClientError,
    BrowserUseClient,
    MockBrowserClient,
    _download_script,
)
from app.config import Settings
from app.models import Resource
from app.schemas.course import CourseDiscoveryResult
from app.services.document_collector import _is_video_resource


@pytest.mark.asyncio
async def test_mock_browser_client_validates_structured_output() -> None:
    browser = MockBrowserClient({"courses": [], "warnings": []})
    result = await browser.run_task("discover courses", CourseDiscoveryResult)
    assert isinstance(result, CourseDiscoveryResult)
    assert result.courses == []


@pytest.mark.asyncio
async def test_mock_browser_connection_is_safe_and_read_only() -> None:
    result = await MockBrowserClient().test_connection()
    assert result.browser_connected is True
    assert result.learn_reachable is True


def test_download_script_is_valid_python() -> None:
    script = _download_script("https://learn.uwaterloo.ca/d2l/common/viewFile/123")
    compile(script, "download.py", "exec")
    assert "data-location" in script
    assert "chunked" in script
    assert "media resource is not downloaded" in script
    assert "AbortController" in script


@pytest.mark.asyncio
async def test_download_timeout_becomes_resource_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = BrowserUseClient(Settings(), executable="browser-use")
    monkeypatch.setattr(client, "is_installed", lambda: True)

    def raise_timeout(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise subprocess.TimeoutExpired("browser-use", timeout=30)

    monkeypatch.setattr("app.browser.client._run_cli", raise_timeout)

    with pytest.raises(BrowserClientError, match="resource download timed out"):
        await client.download_resource("https://learn.uwaterloo.ca/resource")


def test_stale_video_rows_are_skipped_by_title_or_url() -> None:
    assert _is_video_resource(
        Resource(
            title="Explained - LDO' - Video",
            url="https://learn.uwaterloo.ca/d2l/le/content/1296009/viewContent/1/View",
            resource_type="PAGE",
        )
    )
    assert _is_video_resource(
        Resource(
            title="Course media",
            url="https://learn.uwaterloo.ca/content/lecture.mp4",
            resource_type="DOCUMENT",
        )
    )
