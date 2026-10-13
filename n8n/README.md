# n8n workflows

Six [n8n](https://n8n.io) workflows that run Study Agent on a schedule and push to your phone
through ntfy. n8n runs on the home server (http://100.76.57.23:5678, Tailscale only) and calls
the API with `AUTOMATION_TOKEN` as a bearer token, so it never needs the dashboard password.

| Workflow | When | What it does |
| --- | --- | --- |
| Study Agent: nightly LEARN sync | 3:30 AM | Starts a sync (which also indexes new files), checks every 5 minutes until it ends, and pushes only if it didn't work. If LEARN signed the server's browser out, the push opens the sign-in window. |
| Study Agent: daily check-up | 7 AM | Has Study Agent prepare the day's check-up: a few questions for the courses with a test coming, one you missed before plus new ones the tutor writes from the course files. Pushes only if it couldn't. |
| Study Agent: morning brief | 7:30 AM | One push: today's check-up and study plan (how long for what, from the deadlines and your answers), then what's due in the next 7 days (or what's next if the week is clear), anything past due and not marked done, what's new on LEARN, practice questions due, and whether the sync worked. |
| Study Agent: check-up reminder | 4 PM | A push if the day's check-up isn't finished. |
| Study Agent: due tomorrow | 7 PM | Pushes only when something not marked done is due by the end of tomorrow. |
| Study Agent: data check | 5 AM | Looks over what the sync read: junk titles (like an announcement's "posted on" line), courses with no dated deadlines, gaps such as Assignment 1, 2, 4, exams with no date, duplicates, and a stale or failed sync. Pushes only problems it hasn't reported before, and hands new ones a misread page could cause to Claude through `claude-harness/`, which pushes back a branch to review. |

They read no secrets from the workflow files: n8n's `compose.yaml` on the server passes
`STUDY_AGENT_URL`, `STUDY_AGENT_TOKEN` (the same value as this app's `AUTOMATION_TOKEN`),
`STUDY_AGENT_PAGE`, `NTFY_SERVER`, `NTFY_TOPIC`, `HARNESS_URL` and `HARNESS_TOKEN`.

## Changing them

Edit `make_workflows.py`, then:

```bash
python n8n/make_workflows.py      # rewrites n8n/workflows/*.json
git commit -am "..." && git push  # the server pulls it within a minute
ssh aaravmodi@100.76.57.23 'bash ~/projects/study-agent/n8n/install.sh'
```

Importing replaces a workflow with the same id, so edits made in the n8n editor to these
are overwritten; copy one first (Duplicate) if you want to experiment in the editor. Each has a
"Run it now" trigger for the editor's test button.
