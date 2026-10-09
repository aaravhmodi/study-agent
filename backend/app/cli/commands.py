import asyncio
import json
import time
from datetime import UTC, datetime

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from app.browser.client import BrowserClientError, BrowserUseClient, MockBrowserClient
from app.config import get_settings
from app.db.database import SessionLocal, ensure_schema
from app.logging import configure_logging
from app.models import Assessment, Course, Resource
from app.services.rag import RagService
from app.services.rag_eval import EVAL_QUESTIONS, EvalQuestion, run_eval
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
    ensure_schema()
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
def daemon(
    interval_minutes: float = typer.Option(
        60.0,
        "--interval-minutes",
        min=1.0,
        help="Minutes between full read-only LEARN/Outline scans.",
    ),
) -> None:
    """Keep the agent running and periodically refresh the local database."""
    configure_logging()
    console.print(
        f"Background sync started; scanning every {interval_minutes:g} minutes. "
        "Press Ctrl+C to stop."
    )
    while True:
        try:
            service = SyncService(get_settings(), browser=_browser_client(), progress=console.print)
            summary = asyncio.run(service.run())
            console.print(
                f"[green][OK][/green] Background scan complete: "
                f"{summary.courses_found} courses, {summary.assessments_found} assessments, "
                f"{summary.resources_found} resources"
            )
        except KeyboardInterrupt:
            console.print("\nBackground sync stopped.")
            return
        except Exception as exc:
            console.print(f"[yellow][WARN][/yellow] Background scan failed: {exc}")
        time.sleep(interval_minutes * 60)


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
            status = (
                "OVERDUE"
                if due_at and due_at < now and assessment.status != "COMPLETED"
                else assessment.status
            )
            table.add_row(
                course.code or course.name,
                assessment.title,
                assessment.assessment_type,
                due,
                status,
            )
    console.print(table)


@app.command()
def resources() -> None:
    """List study resources collected from LEARN Content and course Outlines."""
    table = Table("Course", "Type", "Resource", "Source URL")
    with SessionLocal() as session:
        statement = (
            select(Resource, Course)
            .join(Course, Resource.course_id == Course.id)
            .where(Course.active.is_(True))
            .order_by(Course.code, Resource.resource_type, Resource.title)
        )
        for resource, course in session.execute(statement):
            table.add_row(
                course.code or course.name,
                resource.resource_type,
                resource.title,
                resource.url or "-",
            )
    console.print(table)


@app.command()
def submissions() -> None:
    """Show read-only submission and Dropbox notes found in Content pages."""
    table = Table("Course", "Resource", "Submission notes")
    with SessionLocal() as session:
        statement = (
            select(Resource, Course)
            .join(Course, Resource.course_id == Course.id)
            .where(Course.active.is_(True), Resource.description.is_not(None))
            .order_by(Course.code, Resource.title)
        )
        for resource, course in session.execute(statement):
            if resource.description:
                table.add_row(
                    course.code or course.name,
                    resource.title,
                    resource.description,
                )
    console.print(table)


@app.command("rag-index")
def rag_index() -> None:
    """Upload saved course documents into the persistent OpenAI vector store."""
    configure_logging()
    try:
        vector_store_id, indexed, skipped, failed = RagService(
            get_settings()
        ).index_database()
    except Exception as exc:
        console.print(f"[red][FAIL] RAG indexing failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(
        f"[green][OK][/green] Vector store {vector_store_id}: "
        f"{indexed} indexed, {skipped} skipped"
    )
    if failed:
        console.print(f"[yellow]WARNING[/yellow] {failed} documents could not be indexed")


_EVAL_QUESTION_OPTION = typer.Option(
    None, "--question", "-q", help="Ask these instead of the built-in shear-force set."
)


@app.command("rag-eval")
def rag_eval(
    question: list[str] | None = _EVAL_QUESTION_OPTION,
    course_code: str | None = typer.Option(None, "--course", help="Course for --question."),
    rounds: int = typer.Option(1, min=1, max=10, help="Repeat the set to check consistency."),
) -> None:
    """Ask tutor questions against the index and check each answer is readable."""
    configure_logging()
    questions = (
        [EvalQuestion(question=text, course_code=course_code) for text in question]
        if question
        else EVAL_QUESTIONS
    )
    try:
        service = RagService(get_settings())
    except RuntimeError as exc:
        console.print(f"[red][FAIL][/red] {exc}")
        raise typer.Exit(code=1) from exc
    results = [result for _ in range(rounds) for result in run_eval(service.ask, questions)]
    table = Table(title="Tutor answer readability")
    table.add_column("Result")
    table.add_column("Question")
    table.add_column("Words", justify="right")
    table.add_column("Concepts", justify="right")
    table.add_column("Issues")
    for result in results:
        quality = result.quality
        issues = result.error or "; ".join(
            (quality.issues if quality else [])
            + [f"missing term: {term}" for term in result.missing_terms]
            + ([] if result.citations else ["no cited sources"])
        )
        table.add_row(
            "[green]PASS[/green]" if result.passed else "[red]FAIL[/red]",
            result.question,
            str(quality.word_count) if quality else "-",
            str(len(quality.concepts)) if quality else "-",
            issues,
        )
    console.print(table)
    report = get_settings().data_dir / "rag_eval.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps([result.model_dump() for result in results], indent=2), encoding="utf-8"
    )
    passed = sum(result.passed for result in results)
    console.print(f"{passed}/{len(results)} answers readable. Report: {report}")
    if passed < len(results):
        raise typer.Exit(code=1)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


if __name__ == "__main__":
    app()
