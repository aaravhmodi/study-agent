# Claude harness

Lets n8n start Claude Code on a fixed job and get back a branch to review. It runs on the
home server in its own container, at http://100.76.57.23:8790 (Tailscale only).

```
n8n workflow ──POST /jobs/<name> (token + context)──▶ harness
   harness: fresh claude/<job>-<time> branch from origin/main in its own copy of the repo
            claude -p "<jobs/<name>.md> + context"   (file and test tools only)
            tests, commit, push the branch           (never main: nothing deploys)
            push to your phone with a link to open the pull request
```

| Job | Started by | What Claude does |
| --- | --- | --- |
| `study-agent-data-check` | n8n's 5 AM data check, for new problems a misread page could cause | Compares each problem with the page the sync saved under `data/pages/`, fixes the parser with a test if the page was misread, and says why it left the rest alone. |

## What it can and can't do

- A caller only picks a job; the prompt is the job's file here. What n8n sends is wrapped as
  data, never instructions.
- Claude can read and edit files in its copy of the repo and run `uv run python -m pytest`,
  `uv run ruff` and read-only git commands. Anything else is refused. It can't push, deploy,
  or see the live app's `.env`, database or the browser signed in to LEARN; it sees only the
  saved page text, read-only.
- The harness pushes `claude/*` branches with a deploy key that works on this repo only
  (GitHub → Settings → Deploy keys, "claude-harness on home server"). Deleting that key
  turns pushing off.
- One job at a time, three a day (`MAX_RUNS_PER_DAY`).

## Setup on the server (done once)

`~/homelab/claude-harness/` holds `.env` (`HARNESS_TOKEN`, `NTFY_TOPIC`,
`CLAUDE_CODE_OAUTH_TOKEN`) and `deploy_key`. To sign Claude in, run `claude setup-token`
on your own computer, put the token after `CLAUDE_CODE_OAUTH_TOKEN=` in that `.env`, then:

```bash
cd ~/projects/study-agent/claude-harness && docker compose up -d --build
curl -s http://100.76.57.23:8790/health
```

## Adding a job

Write `jobs/<name>.md` (what to look at, what to change, what to leave alone, and how to
summarise), add it to `JOB_REPO` in `server.py`, and call it from an n8n workflow with the
`ask_claude` helper in `n8n/make_workflows.py`.
