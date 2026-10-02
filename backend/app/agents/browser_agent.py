from app.browser.client import BrowserClient


class BrowserAgent:
    """Thin orchestration boundary for future model-directed Browser Use tasks."""

    def __init__(self, browser: BrowserClient) -> None:
        self.browser = browser
