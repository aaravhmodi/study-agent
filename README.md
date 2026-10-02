# StudyAgent

StudyAgent is a local-first academic workload assistant for University of Waterloo LEARN / D2L Brightspace. Milestone 1 and 2 provide the Python/FastAPI/SQLite foundation, mock fixtures, and a read-only Browser Use connection test.

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
```

The command runs a read-only Browser Use probe against `https://learn.uwaterloo.ca`, reports whether the local Chrome session is connected and whether LEARN is reachable, and leaves navigation/extraction for the next milestones.

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

Milestone 1 includes the repository structure, SQLAlchemy models, Alembic migration, Typer CLI, FastAPI health endpoint, mock LEARN fixtures, and tests. Milestone 2 adds Browser Use detection and the read-only Chrome/LEARN connection probe. Course discovery and course scanning begin in Milestone 3.
