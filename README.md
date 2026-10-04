# StudyAgent

StudyAgent is a local-first academic workload assistant for University of Waterloo LEARN / D2L Brightspace. It discovers active course shells, reads announcements, calendar due items, content resources, and checks Outline.uwaterloo.ca without changing LMS data.

## Prerequisites

- Windows with Google Chrome installed.
- Python 3.12 (or let `uv` provision it).
- [`uv`](https://docs.astral.sh/uv/) for environment and dependency management.
- A Chrome session already signed in to Waterloo LEARN.
- The current Browser Use CLI. Install it into the project-local environment with:

```powershell
uv venv --python 3.12 .browser-use-venv
uv pip install --python .browser-use-venv\Scripts\python.exe "browser-use @ git+https://github.com/browser-use/browser-use.git"
```

Browser Use local mode attaches to the running Chrome session over CDP. It may ask once for remote-debugging permission. The app never asks for or stores a Waterloo password or MFA code. If LEARN shows a sign-in or verification step, complete it yourself in Chrome and rerun the browser test.

## Setup

From the repository root:

```powershell
uv sync --dev
Copy-Item .env.example .env
uv run study-agent setup
```

`OPENAI_API_KEY` is not required by the Milestone 1/2 smoke tests. It will be required when semantic extraction is added.

## Browser connection test

Keep Chrome open and signed in to LEARN, then run:

```powershell
uv run study-agent browser test
uv run study-agent sync
uv run study-agent courses
uv run study-agent assessments
uv run study-agent resources
uv run study-agent submissions
```

`sync` uses the authenticated Chrome session to discover active LEARN course shells, inspect each course, traverse every visible Content module and its discovered Content items, collect PDF/document/slide/page resources, capture read-only Dropbox/submission notes from HTML pages, open recent LEARN announcement details, check its Outline page, and persist the extracted records in SQLite. Outline rows without dates (for example, a final listed as `TBD`) are retained as `UNKNOWN`; announced dates are merged with calendar and Outline records when they describe the same assessment. It never clicks Submit or changes LMS data. Authentication remains browser-managed; complete any sign-in or Duo prompt in Chrome.

## Keep it running in the background

With Chrome open and signed in, run this in a separate PowerShell window:

```powershell
uv run study-agent daemon --interval-minutes 60
```

It performs one full sync immediately and repeats every hour. Leave that window running; press `Ctrl+C` to stop it. Because local Chrome mode uses your existing interactive browser session, Chrome must remain open and signed in for background scans to succeed.

## Dashboard

Start the local read-only dashboard from the repository root:

```powershell
uv run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/dashboard>. Click a course to see its assessments, collected coursework, announcements, and locally marked completion count. Click an assessment to see ranked relevant coursework and study instructions tailored to quizzes/tests versus assignments/labs/projects. The assessment panel lets you mark work completed or reopen it; this is stored locally and survives future syncs. The JSON API is available at `/api/dashboard`, `/courses/{id}`, `/assessments/{id}`, `/resources`, and `/changes`.

Completion is deliberately explicit: StudyAgent does not claim that an assessment is complete just because you opened a page or viewed a file. Resources are shown as collected coursework; actual assessment completion is marked by you from the dashboard.

`submissions` shows the Dropbox/submission wording captured from readable LEARN Content pages:

```powershell
uv run study-agent submissions
```

## Daily workflow

From the repository root, keep Chrome open with LEARN and Outline signed in:

```powershell
uv run study-agent browser test
uv run study-agent sync
uv run study-agent courses
uv run study-agent assessments
```

`browser test` verifies the connection. `sync` rescans all six enrolled Fall 2026 SYDE courses and checks each course's Outline page on every run. `courses` confirms the active course list, `assessments` shows upcoming work from LEARN, announcement details, and Outline rows (including undated `UNKNOWN` rows), and `resources` lists the collected study material.

If Waterloo asks for a password or Duo verification, complete it in Chrome, then rerun `browser test` and `sync`. The application does not store Waterloo credentials, MFA codes, or browser cookies.

Use the underlying diagnostic when needed:

```powershell
browser-use --doctor
```

## Tests and checks

```powershell
uv run ruff format .
uv run ruff check .
uv run mypy backend
uv run pytest
```

## Current scope

Milestones 1–3 include the repository structure, SQLAlchemy models, Alembic migration, Typer CLI, FastAPI health endpoint, mock LEARN fixtures, Browser Use detection, active-course discovery, read-only course scanning, announcement/resource persistence, calendar assessment extraction, and Outline checks. Topic extraction, change detection, planning, and conversational queries remain later milestones.
