import pytest
from app.browser.client import MockBrowserClient
from app.schemas.course import CourseDiscoveryResult


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
