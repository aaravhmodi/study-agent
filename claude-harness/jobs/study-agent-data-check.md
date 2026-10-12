# Job: check what the data check reported, and fix how pages are read if that's the cause

You're working in a copy of Study Agent (read AGENTS.md first). Each morning a check looks
at the deadlines Study Agent read from LEARN, the course Outlines and UWaterloo's exam
schedule, and reports anything that looks misread. Its report is at the end of this
message.

The pages the last sync read are saved as text under /pages/<course>/ (for example
/pages/SYDE-252/), one file per page with its URL on the first line. The exam schedule is
under /pages/exam-schedule/. The parsing code is mostly backend/app/agents/course_agent.py
and backend/app/services/exam_schedule.py.

For each reported problem:

1. Find the page it came from and decide which it is:
   - a reading bug: the page has the information and Study Agent missed or misread it, or
   - real: the page doesn't have it (an exam the school hasn't dated yet, a quiz that
     isn't posted, an old item LEARN no longer shows). Leave those alone.
2. For a reading bug, write a failing test first in backend/tests/, using a short copy of
   the real page text, then fix the parser so it passes without breaking the other tests.
   Keep the change small and in the style of the code around it.
3. Run `uv run python -m pytest -q` and `uv run ruff check backend` and
   `uv run ruff format --check backend` before you finish.

Don't change anything under data/, n8n/, claude-harness/, scripts/, .env files, the
Dockerfile or compose.yaml. Don't commit; the harness commits and pushes a branch for
review.

Finish with a short plain-English summary for a phone notification. Its first line is the
commit title (under 70 characters, saying what changed, e.g. "Read quiz numbers from the
SYDE 286 Outline"). Then, for each reported problem, one line saying whether it was a
reading bug you fixed or real and left alone, and why.
