# n8n workflows

Three [n8n](https://n8n.io) workflows that run Study Agent on a schedule and push to your phone
through ntfy. n8n runs on the home server (http://100.76.57.23:5678, Tailscale only) and calls
the API with `AUTOMATION_TOKEN` as a bearer token, so it never needs the dashboard password.

| Workflow | When | What it does |
| --- | --- | --- |
| Study Agent: nightly LEARN sync | 3:30 AM | Starts a sync (which also indexes new files), checks every 5 minutes until it ends, and pushes only if it didn't work. If LEARN signed the server's browser out, the push opens the sign-in window. |
| Study Agent: morning brief | 7:30 AM | One push: what's due in the next 7 days (or what's next if the week is clear), anything past due and not marked done, what's new on LEARN, practice questions due, and whether the sync worked. |
| Study Agent: due tomorrow | 7 PM | Pushes only when something not marked done is due by the end of tomorrow. |

They read no secrets from the workflow files: n8n's `compose.yaml` on the server passes
`STUDY_AGENT_URL`, `STUDY_AGENT_TOKEN` (the same value as this app's `AUTOMATION_TOKEN`),
`STUDY_AGENT_PAGE`, `NTFY_SERVER` and `NTFY_TOPIC`.

## Changing them

Edit `make_workflows.py`, then:

```bash
python n8n/make_workflows.py      # rewrites n8n/workflows/*.json
git commit -am "..." && git push  # the server pulls it within a minute
ssh aaravmodi@100.76.57.23 'bash ~/projects/study-agent/n8n/install.sh'
```

Importing replaces a workflow with the same id, so edits made in the n8n editor to these three
are overwritten; copy one first (Duplicate) if you want to experiment in the editor. Each has a
"Run it now" trigger for the editor's test button.
