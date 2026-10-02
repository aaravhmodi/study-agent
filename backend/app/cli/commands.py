import asyncio
from datetime import UTC, datetime

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from app.browser.client import BrowserClientError, BrowserUseClient, MockBrowserClient
from app.config import get_settings
from app.db.database import Base, SessionLocal, engine
from app.logging import configure_logging
from app.models import Assessment, Course
from app.services.sync_service import SyncService

app = typer.Typer(help="Local-first academic agent for Waterloo LEARN.")
browser_app = typer.Typer(help="Browser connection and diagnostics.")
app.add_typer(browser_app, name="browser")
console = Console()


def _browser_client() -> BrowserUseClient | MockBrowserClient:
    settings = get_settings()
    if settings.browser_mode == "mock":
        return MockBrowserClient()
    return BrowserUseClient(settings)


@app.command()
def setup() -> None:
    """Create local directories, initialize the database, and report prerequisites."""
    configure_logging()
    settings = get_settings()
    settings.data_dir.joinpath("downloads").mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    console.print("[green][OK][/green] Local directories ready")
    console.print("[green][OK][/green] SQLite database initialized")
    console.print(f"[green][OK][/green] Browser mode: {settings.browser_mode}")
    if settings.openai_api_key:
        console.print("[green][OK][/green] OpenAI API key configured")
    else:
        console.print(
            "[yellow][WARN][/yellow] OPENAI_API_KEY is not set (semantic AI extraction is disabled)"
        )
    if settings.browser_mode == "mock":
        console.print("[green][OK][/green] Mock browser mode selected")
    elif BrowserUseClient(settings).is_installed():
        console.print("[green][OK][/green] Browser Use CLI detected")
    else:
        console.print("[yellow][WARN][/yellow] Browser Use CLI not found on PATH")
    console.print(
        "Next: keep Chrome signed in to LEARN and run [cyan]study-agent browser test[/cyan]."
    )


@browser_app.command("test")
def browser_test() -> None:
    """Verify a read-only connection to Chrome and Waterloo LEARN."""
    configure_logging()
    console.print("Connecting to the local browser...")
    try:
        result = asyncio.run(_browser_client().test_connection())
    except (BrowserClientError, OSError, TimeoutError) as exc:
        console.print(f"[red][FAIL] Browser test failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print("[green][OK][/green] Browser session connected")
    if result.learn_reachable:
        console.print("[green][OK][/green] Waterloo LEARN reachable")
    else:
        console.print(
            "[yellow][WARN][/yellow] Browser connected, but the current page did not confirm LEARN"
        )
    if result.url:
        console.print(f"  URL: {result.url}")
    if result.title:
        console.print(f"  Title: {result.title}")


@app.command()
def sync() -> None:
    """Discover active courses and read assessment, announcement, content, and outline surfaces."""
    configure_logging()
    console.print("Connecting to Waterloo LEARN and scanning active courses...")
    service = SyncService(get_settings(), browser=_browser_client(), progress=console.print)
    try:
        summary = asyncio.run(service.run())
    except Exception as exc:
        console.print(f"[red][FAIL] Sync failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(
        f"[green][OK][/green] Sync complete: {summary.courses_found} courses, "
        f"{summary.assessments_found} assessments, {summary.resources_found} resources"
    )


@app.command()
def courses() -> None:
    """List stored active courses."""
    table = Table("Code", "Course", "Term", "Last scanned")
    with SessionLocal() as session:
        for course in session.scalars(
            select(Course).where(Course.active.is_(True)).order_by(Course.name)
        ):
            table.add_row(
                course.code or "-",
                course.name,
                course.term or "-",
                course.last_scanned_at.strftime("%Y-%m-%d %H:%M UTC")
                if course.last_scanned_at
                else "never",
            )
    console.print(table)


@app.command()
def assessments() -> None:
    """List upcoming and overdue assessments stored from the last sync."""
    table = Table("Course", "Assessment", "Type", "Due", "Status")
    now = datetime.now(UTC)
    with SessionLocal() as session:
        statement = (
            select(Assessment, Course)
            .join(Course, Assessment.course_id == Course.id)
            .where(Course.active.is_(True))
            .order_by(Assessment.due_at.is_(None), Assessment.due_at)
        )
        for assessment, course in session.execute(statement):
            due_at = _as_utc(assessment.due_at)
            due = due_at.astimezone().strftime("%Y-%m-%d %H:%M") if due_at else "unknown"
            status = "OVERDUE" if due_at and due_at < now else assessment.status
            table.add_row(
                course.code or course.name,
                assessment.title,
                assessment.assessment_type,
                due,
                status,
            )
    console.print(table)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


if __name__ == "__main__":
    app()
