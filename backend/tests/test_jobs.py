import threading
from collections.abc import Callable

import pytest
from app import main
from app.config import Settings
from app.services import refresh
from app.services.jobs import MAX_LINES, JobRunner
from app.services.refresh import sync_learn
from fastapi.testclient import TestClient


def _wait(runner: JobRunner) -> None:
    for thread in threading.enumerate():
        if thread.name.startswith("job-"):
            thread.join(timeout=5)
    assert runner.status().state != "running"


def test_a_task_reports_its_progress_and_result() -> None:
    runner = JobRunner()
    assert runner.status().state == "idle"

    def work(progress: Callable[[str], None]) -> str:
        for number in range(MAX_LINES + 3):
            progress(f"step {number}")
        return "All done."

    assert runner.start("index", work)
    _wait(runner)

    status = runner.status()
    assert (status.name, status.state, status.message) == ("index", "done", "All done.")
    assert status.started_at is not None and status.finished_at is not None
    # Only the latest lines are kept, each with the time it was reported.
    assert status.lines[-1].text == f"step {MAX_LINES + 2}" and len(status.lines) == MAX_LINES
    assert status.started_at <= status.lines[0].at <= status.lines[-1].at <= status.finished_at


def test_only_one_task_runs_at_a_time() -> None:
    runner = JobRunner()
    release = threading.Event()

    def slow(progress: Callable[[str], None]) -> str:
        release.wait(timeout=5)
        return "finished"

    assert runner.start("sync", slow)
    assert not runner.start("index", lambda progress: "never runs")
    assert runner.status().name == "sync"
    release.set()
    _wait(runner)

    # Once it is over, the next one may start.
    assert runner.start("index", lambda progress: "ran")
    _wait(runner)
    assert runner.status().message == "ran"


def test_a_failed_task_says_why_without_leaking_secrets() -> None:
    runner = JobRunner()

    def work(progress: Callable[[str], None]) -> str:
        raise RuntimeError("LEARN said no, token=abc123secret")

    runner.start("sync", work)
    _wait(runner)

    status = runner.status()
    assert status.state == "failed"
    assert "LEARN said no" in status.message and "abc123secret" not in status.message


def test_the_dashboard_starts_tasks_and_reports_them(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None, learn_signin_url="http://server:6080/vnc.html")
    runner = JobRunner()
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "_jobs", runner)
    release = threading.Event()

    def held(progress: Callable[[str], None]) -> str:
        progress("Scanning SYDE 212...")
        release.wait(timeout=5)
        return "Synced 6 courses."

    monkeypatch.setattr(main, "sync_learn", held)
    monkeypatch.setattr(main, "rebuild_index", lambda progress: "Indexed 2 new or changed files.")
    client = TestClient(main.app)

    assert client.get("/jobs").json()["state"] == "idle"
    assert client.post("/jobs/sync").json()["state"] == "running"
    busy = client.post("/jobs/index")
    assert (busy.status_code, busy.json()) == (409, {"detail": "Another task is still running."})
    release.set()
    _wait(runner)

    done = client.get("/jobs").json()
    assert (done["name"], done["state"], done["message"]) == ("sync", "done", "Synced 6 courses.")
    assert [line["text"] for line in done["lines"]] == ["Scanning SYDE 212..."]
    assert done["lines"][0]["at"] and done["started_at"] and done["finished_at"]
    # The page links to the server's sign-in window when there is one.
    assert done["signin_url"] == "http://server:6080/vnc.html"

    assert client.post("/jobs/index").status_code == 200
    _wait(runner)
    assert client.get("/jobs").json()["message"] == "Indexed 2 new or changed files."


def test_a_sync_that_meets_the_sign_in_page_says_where_to_sign_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(_env_file=None, learn_signin_url="http://server:6080/vnc.html")
    monkeypatch.setattr(refresh, "get_settings", lambda: settings)

    class SignedOut:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def run(self) -> None:
            raise RuntimeError(
                "The browser is connected, but Waterloo LEARN is not authenticated or reachable."
            )

    monkeypatch.setattr(refresh, "SyncService", SignedOut)

    with pytest.raises(RuntimeError, match="LEARN sign-in window"):
        sync_learn(lambda line: None)
