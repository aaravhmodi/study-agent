"""The two tasks the dashboard can start: read LEARN again, and rebuild the tutor's index."""

import asyncio
from collections.abc import Callable

from app.browser.client import BrowserClient, BrowserUseClient, MockBrowserClient
from app.config import Settings, get_settings
from app.services.rag import RagService
from app.services.sync_service import SyncService

Progress = Callable[[str], None]


def browser_client(settings: Settings) -> BrowserClient:
    if settings.browser_mode == "mock":
        return MockBrowserClient.demo(settings.timezone)
    return BrowserUseClient(settings)


def sync_learn(progress: Progress) -> str:
    """Read LEARN through the signed-in browser, then index whatever is new."""

    settings = get_settings()
    progress("Connecting to LEARN")
    service = SyncService(settings, browser=browser_client(settings), progress=progress)
    try:
        summary = asyncio.run(service.run())
    except RuntimeError as exc:
        if "not authenticated" in str(exc) and settings.learn_signin_url:
            raise RuntimeError(
                "LEARN is asking for a sign-in. Sign in through the LEARN sign-in window, "
                "then sync again."
            ) from exc
        raise
    found = (
        f"{summary.courses_found} courses, {summary.assessments_found} assessments, "
        f"{summary.resources_found} files"
    )
    if not settings.openai_api_key:
        return f"Synced {found}."
    progress(f"Synced {found}. Indexing new files")
    return f"Synced {found}. {rebuild_index(progress)}"


def rebuild_index(progress: Progress) -> str:
    """Bring the tutor's index in line with the saved course files."""

    progress("Comparing saved files with the index")
    _store, indexed, skipped, failed = RagService(get_settings()).index_database()
    result = f"Indexed {indexed} new or changed files; {skipped} unchanged."
    return f"{result} {failed} could not be indexed." if failed else result
