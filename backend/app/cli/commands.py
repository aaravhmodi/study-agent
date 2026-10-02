import asyncio
import shutil

import typer
from rich.console import Console

from app.browser.client import BrowserClientError, BrowserUseClient, MockBrowserClient
from app.config import get_settings
from app.db.database import Base, engine
from app.logging import configure_logging

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
    console.print("[green]✓[/green] Local directories ready")
    console.print("[green]✓[/green] SQLite database initialized")
    console.print(f"[green]✓[/green] Browser mode: {settings.browser_mode}")
    if settings.openai_api_key:
        console.print("[green]✓[/green] OpenAI API key configured")
    else:
        console.print(
            "[yellow]⚠[/yellow] OPENAI_API_KEY is not set (not required for Milestones 1–2)"
        )
    if settings.browser_mode == "mock":
        console.print("[green]✓[/green] Mock browser mode selected")
    elif shutil.which("browser-use"):
        console.print("[green]✓[/green] Browser Use CLI detected")
    else:
        console.print("[yellow]⚠[/yellow] Browser Use CLI not found on PATH")
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
        console.print(f"[red]✗ Browser test failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print("[green]✓[/green] Browser session connected")
    if result.learn_reachable:
        console.print("[green]✓[/green] Waterloo LEARN reachable")
    else:
        console.print(
            "[yellow]⚠[/yellow] Browser connected, but the current page did not confirm LEARN"
        )
    if result.url:
        console.print(f"  URL: {result.url}")
    if result.title:
        console.print(f"  Title: {result.title}")


@app.command()
def sync() -> None:
    """Synchronize LMS data (course discovery begins in Milestone 3)."""
    console.print(
        "[yellow]Sync is scheduled for Milestone 3; run `study-agent browser test` "
        "for now.[/yellow]"
    )


@app.command()
def courses() -> None:
    """List stored courses."""
    console.print("Course listing begins in Milestone 3.")


if __name__ == "__main__":
    app()
