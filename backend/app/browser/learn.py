from app.browser.client import BrowserClient
from app.schemas.sync import BrowserTestResult


async def test_learn_connection(browser: BrowserClient) -> BrowserTestResult:
    return await browser.test_connection()
