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

`OPENAI_API_KEY` is required for RAG indexing and chat. Keep it only in `.env`; it is never printed or sent to the browser.

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

`sync` uses the authenticated Chrome session to discover active LEARN course shells, inspect each course, traverse every visible Content module and its discovered Content items, collect PDF/document/slide/page resources, save readable resources locally through authenticated GET requests, capture read-only Dropbox/submission notes from HTML pages, open recent LEARN announcement details, check its Outline page, and persist the extracted records in SQLite. Outline rows without dates (for example, a final listed as `TBD`) are retained as `UNKNOWN`; announced dates are merged with calendar and Outline records when they describe the same assessment. It never clicks Submit or changes LMS data. Authentication remains browser-managed; complete any sign-in or Duo prompt in Chrome.

## Try it without LEARN

Mock mode syncs a made-up copy of the six Fall 2026 courses: dated assignments and tests relative to today, short lecture notes, and announcements. Use it to work on the app without Chrome:

```powershell
$env:BROWSER_MODE = "mock"
uv run study-agent sync
uv run study-agent dashboard
```

Demo data goes to `data/demo.db` and `data/demo-downloads/`, never to your real `data/study_agent.db`, even if `.env` names that database. Remove the variable (`Remove-Item Env:BROWSER_MODE`) to go back to your real courses.

## Course-material chatbot

After a sync, build/update the persistent OpenAI vector store:

```powershell
uv run study-agent rag-index
```

Start the dashboard and ask questions in the “Ask your course materials” box, or call `POST /chat` with `{"question":"Get me up to speed for SYDE 252 tomorrow.","course_code":"SYDE 252"}`. Answers are grounded in your course files and list the files they cite. Re-run `rag-index` after future syncs; unchanged files are skipped.

The index is persistent: each file is uploaded and embedded once, and only new or changed files are processed again. Each question then costs:

- **One search, no repeats.** The app searches the index once, drops duplicate and overlapping passages, keeps at most three per file, and sends the best ones up to `RAG_CONTEXT_TOKENS` (default 3,000). The model never runs its own file searches.
- **Small chunks.** Files are indexed in 400-token chunks overlapping by 100, not OpenAI's default 800/400, so the budget holds more distinct passages.
- **A cached prefix.** The teaching and figure guides are one fixed prompt prefix that OpenAI caches after the first question (cached input is billed at a discount).
- **Nothing for repeats.** A question already asked with the same course, settings and index is answered from `data/answer_cache.json`; the dashboard says "saved answer" and offers "ask fresh".

Each answer shows its token count, e.g. "9.3k tokens (5.7k cached)". For fewer tokens still, lower `RAG_CONTEXT_TOKENS`, or set `RAG_WEB_SEARCH=false` (web search adds a few thousand tokens when the model uses it).

Chat answers use the lighter `OPENAI_CHAT_MODEL` (default `gpt-6-luna`) with low reasoning effort and a 3,000-token output cap; handwritten-PDF transcription keeps `OPENAI_MODEL`. The tutor is built around study techniques with strong evidence:

- **Concept by concept:** "Explain ..." questions get an Overview, one subsection per key concept in the chapter, a Worked example, and Common mistakes.
- **Practice testing:** every explanation ends with "Check yourself" questions whose answers stay hidden until clicked.
- **Spacing:** the Study checklist says when to revisit the topic.
- **No answer-copying:** questions that look like graded assignment or lab problems get concepts and a first-step hint, not a full solution.
- **Any lecture:** naming "Lecture 7", "week 3", "chapter 5" or "tutorial 4" narrows the search to the matching course files.
- **Online context:** web search adds intuition and real-world examples the course files lack. Those sentences are marked "(online)", the sources are linked, and course notation always wins. Set `RAG_WEB_SEARCH=false` to use course files only.

To check that live answers are readable, run the built-in question set: seven SYDE 286 shear-force questions, plus a core topic and a "what did Lecture 1 cover" question for each course. You can also pass your own with `-q`:

```powershell
uv run study-agent rag-eval --rounds 3
uv run study-agent rag-eval -q "Explain bending stress." --course "SYDE 286"
```

Each answer is scored for structure, concept coverage, balanced LaTeX, paragraph and sentence length, cited sources, and (for questions about a shape) whether a figure came back; the full report is written to `data/rag_eval.json`.

### Conversations and follow-ups

Every question starts a chat that is saved locally (`data/chat_sessions.json`). Ask a follow-up ("why is that?", "show me an example") and the tutor answers it in context: the last three exchanges go with the question, and a short follow-up is searched together with the question it follows. "Recent chats" in the dashboard reopens any conversation with its answers, figures and sources; "New chat" starts over. The API is `POST /chat` with the returned `session_id`, plus `GET /chat/sessions`, `GET /chat/sessions/{id}` and `DELETE /chat/sessions/{id}`.

### Sources and links

Answers cite course files inline, with the page for PDFs (`[course text.pdf, p. 87]`). Every cited file links to its LEARN page, and the Sources list names it by its LEARN title.

### Course notes

Some things the instructor says never reach LEARN, or not where sync reads them, such as what a midterm covers. Add them once per course, in the course's panel on the dashboard or from the terminal:

```powershell
uv run study-agent course-note "SYDE 212" --file midterm.txt   # or --text "...", --clear
```

The tutor reads a course's notes with every question about it. It says whether a topic is in scope, and writes practice questions in the exam's format (for example multiple choice).

### Files too large to sync

Sync skips LEARN files over 15 MB, such as a whole course textbook. Download the file from LEARN yourself, then attach it to its LEARN item:

```powershell
uv run study-agent import-file "$HOME\Downloads\course-text.pdf" --link "https://learn.uwaterloo.ca/d2l/le/content/1299242/viewContent/6617316/View"
```

This saves it with the item, extracts the PDF text page by page and indexes it. The tutor then searches it and cites it with its LEARN title, link and page numbers. Later syncs keep the imported copy.

### Figures in answers

When a topic has a shape or a picture, the tutor draws it next to the text it explains:

| Figure | Used for | Drawn by |
| --- | --- | --- |
| Graph | functions, distributions, shear and moment diagrams, signals; stems for x[n], PMFs and cash flows | Chart.js |
| Free-body diagram | beams with supports and distributed loads, blocks on inclines, particles, disks | the server |
| Circuit | schematics with sources, R, L, C, switches, diodes, meters | schemdraw |
| Concept diagram | processes, cause and effect, proof outlines | Mermaid |
| Sketch | anything else (a molecule, a geometric construction, a timeline) | the model's own SVG |

The model only describes a figure as data; nothing it writes is run. The server checks every description with Pydantic. It evaluates formulas with a parser that accepts only arithmetic and math functions, and lays out free-body diagrams and circuits itself. Every SVG is rebuilt from an allow-list of drawing elements, and the browser sanitizes it again. A figure that can't be drawn is left out of the answer, never shown as raw JSON. Chart.js and Mermaid load only when an answer needs them.

## Keep it running in the background

With Chrome open and signed in, run this in a separate PowerShell window:

```powershell
uv run study-agent daemon --interval-minutes 60
```

It performs one full sync immediately and repeats every hour. Leave that window running; press `Ctrl+C` to stop it. Because local Chrome mode uses your existing interactive browser session, Chrome must remain open and signed in for background scans to succeed.

## Dashboard

Start the local read-only dashboard from the repository root:

```powershell
uv run study-agent dashboard
```

It opens <http://127.0.0.1:8000/dashboard> in your browser; press `Ctrl+C` to stop it. Use `--port 8001` if 8000 is taken, or `--no-open` to skip opening the browser. Click a course to see its assessments, collected coursework, announcements, and locally marked completion count. Click an assessment to see ranked relevant coursework and study instructions tailored to quizzes/tests versus assignments/labs/projects. The assessment panel lets you mark work completed or reopen it; this is stored locally and survives future syncs. The JSON API is available at `/api/dashboard`, `/courses/{id}`, `/assessments/{id}`, `/resources`, and `/changes`.

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
uv run study-agent rag-index
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
