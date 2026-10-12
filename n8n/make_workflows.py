"""Write the Study Agent workflows for n8n into workflows/, one JSON file each.

Import them with:  docker compose exec n8n n8n import:workflow --separate --input=/workflows
They read STUDY_AGENT_URL, STUDY_AGENT_TOKEN, STUDY_AGENT_PAGE, NTFY_SERVER and NTFY_TOPIC
from n8n's environment (compose.yaml and .env), so no secret is stored in a workflow.
"""

import json
import uuid
from pathlib import Path
from typing import Any

OUT = Path(__file__).parent / "workflows"
TZ = "America/Toronto"
Node = dict[str, Any]


def _id(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"study-agent-n8n/{name}"))


def schedule(name: str, cron: str, x: int) -> Node:
    return {
        "id": _id(name),
        "name": name,
        "type": "n8n-nodes-base.scheduleTrigger",
        "typeVersion": 1.2,
        "position": [x, 300],
        "parameters": {"rule": {"interval": [{"field": "cronExpression", "expression": cron}]}},
    }


def study_agent(
    name: str,
    method: str,
    path: str,
    x: int,
    y: int = 300,
    once: bool = True,
    never_error: bool = False,
) -> Node:
    """A call to the Study Agent API with the automation token."""
    options: dict[str, Any] = {"timeout": 30000}
    if never_error:  # e.g. 409 "another task is running" is fine
        options["response"] = {"response": {"neverError": True}}
    return {
        "id": _id(name),
        "name": name,
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [x, y],
        "executeOnce": once,
        # An empty list (no changes, nothing due) must not stop the workflow.
        "alwaysOutputData": True,
        "parameters": {
            "method": method,
            "url": "={{ $env.STUDY_AGENT_URL }}" + path,
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [
                    {"name": "Authorization", "value": "=Bearer {{ $env.STUDY_AGENT_TOKEN }}"}
                ]
            },
            "options": options,
        },
    }


def code(name: str, js: str, x: int, y: int = 300) -> Node:
    return {
        "id": _id(name),
        "name": name,
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [x, y],
        "parameters": {"mode": "runOnceForAllItems", "language": "javaScript", "jsCode": js},
    }


def push(name: str, x: int, y: int = 300) -> Node:
    """Send each incoming item ({title, message, priority, tags, click}) to the phone."""
    return {
        "id": _id(name),
        "name": name,
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [x, y],
        "parameters": {
            "method": "POST",
            "url": "={{ $env.NTFY_SERVER }}",
            "sendBody": True,
            "contentType": "json",
            "specifyBody": "json",
            "jsonBody": "={{ JSON.stringify({ ...$json, topic: $env.NTFY_TOPIC }) }}",
            "options": {"timeout": 15000},
        },
    }


def wait(name: str, minutes: int, x: int, y: int = 300) -> Node:
    return {
        "id": _id(name),
        "name": name,
        "type": "n8n-nodes-base.wait",
        "typeVersion": 1.1,
        "position": [x, y],
        "webhookId": _id(name + "/hook"),
        "parameters": {"amount": minutes, "unit": "minutes"},
    }


def condition(name: str, expression: str, x: int, y: int = 300) -> Node:
    """True/false on a JavaScript expression. Output 0 is true, output 1 is false."""
    return {
        "id": _id(name),
        "name": name,
        "type": "n8n-nodes-base.if",
        "typeVersion": 2.2,
        "position": [x, y],
        "parameters": {
            "conditions": {
                "options": {
                    "caseSensitive": True,
                    "leftValue": "",
                    "typeValidation": "loose",
                    "version": 2,
                },
                "conditions": [
                    {
                        "id": _id(name + "/c"),
                        "leftValue": "={{ " + expression + " }}",
                        "rightValue": "",
                        "operator": {"type": "boolean", "operation": "true", "singleValue": True},
                    }
                ],
                "combinator": "and",
            },
            "options": {},
        },
    }


def chain(*names: str) -> dict[str, Any]:
    return {
        a: {"main": [[{"node": b, "type": "main", "index": 0}]]}
        for a, b in zip(names, names[1:], strict=False)
    }


def workflow(name: str, nodes: list[Node], connections: dict[str, Any], about: str) -> dict:
    # A "Run it now" trigger beside the schedule, for the editor's test button and the CLI.
    manual = "Run it now"
    nodes = [
        {
            "id": _id(f"{name}/{manual}"),
            "name": manual,
            "type": "n8n-nodes-base.manualTrigger",
            "typeVersion": 1,
            "position": [0, 500],
            "parameters": {},
        },
        *nodes,
    ]
    connections = {manual: connections[nodes[1]["name"]], **connections}
    return {
        "id": _id(name).replace("-", "")[:16],
        "name": name,
        "active": True,
        "nodes": nodes,
        "connections": connections,
        "pinData": {},
        "meta": {"notes": about},
        "settings": {
            "executionOrder": "v1",
            "timezone": TZ,
            "saveManualExecutions": True,
            "saveDataSuccessExecution": "all",
            "saveDataErrorExecution": "all",
        },
        "tags": [],
    }


# Shared JavaScript: dates in Toronto time, and a short line for one deadline.
JS_HELPERS = r"""
const tz = 'America/Toronto';
const when = (iso) => new Date(iso).toLocaleString('en-CA', {
  timeZone: tz, weekday: 'short', hour: 'numeric', minute: '2-digit' });
const line = (a) => `• ${when(a.due_at)} · ${a.course} · ${a.title}`;
const list = (node) => $(node).all().map((item) => item.json)
  .filter((x) => x && Object.keys(x).length);
const page = $env.STUDY_AGENT_PAGE;
"""

# ---- 1. Morning brief ---------------------------------------------------------------------

BRIEF_JS = (
    JS_HELPERS
    + r"""
const now = Date.now();
const day = 24 * 60 * 60 * 1000;
const open = list('Deadlines').filter((a) => a.due_at && a.status !== 'COMPLETED');
const ahead = (a) => Date.parse(a.due_at) - now;
const week = open.filter((a) => ahead(a) >= 0 && ahead(a) <= 7 * day);
const overdue = open.filter((a) => ahead(a) < 0 && ahead(a) >= -7 * day);
const fresh = list('New on LEARN')
  .filter((c) => c.detected_at && now - Date.parse(c.detected_at) <= day);
const practice = list('Practice due').filter((q) => q.id || q.question);
const job = $('Last sync').first().json;

const parts = [];
if (week.length) {
  parts.push(`Due in the next 7 days:\n${week.slice(0, 8).map(line).join('\n')}` +
             (week.length > 8 ? `\n…and ${week.length - 8} more` : ''));
} else {
  const later = open.filter((a) => ahead(a) > 7 * day).slice(0, 3);
  parts.push('Nothing due in the next 7 days.' +
             (later.length ? `\nComing up after that:\n${later.map(line).join('\n')}` : ''));
}
if (overdue.length) {
  parts.push(`Past due and not marked done:\n${overdue.slice(0, 4).map(line).join('\n')}` +
             '\n(Mark them done in Study Agent if you handed them in.)');
}
if (fresh.length) {
  parts.push(`New on LEARN since yesterday (${fresh.length}):\n` +
             fresh.slice(0, 4).map((c) => `• ${c.description}`).join('\n'));
}
if (practice.length) {
  parts.push(`🧠 ${practice.length === 10 ? '10+' : practice.length} practice question` +
             `${practice.length === 1 ? ' is' : 's are'} due for review.`);
}
if (job.name === 'sync' && job.state === 'failed') {
  parts.push("⚠️ Last night's LEARN sync failed, so this may be missing new things.");
} else if (job.name === 'sync' && job.state === 'done' && job.finished_at &&
           now - Date.parse(job.finished_at) <= day) {
  parts.push(`✓ LEARN checked at ${new Date(job.finished_at).toLocaleTimeString('en-CA', {
    timeZone: tz, hour: 'numeric', minute: '2-digit' })}.`);
}

const next = week[0];
const title = next
  ? `📚 ${week.length} due this week · next: ${next.course} ${next.title}`.slice(0, 120)
  : open.some((a) => ahead(a) > 7 * day)
    ? (() => {
        const soonest = open.find((a) => ahead(a) > 7 * day);
        const days = Math.round(ahead(soonest) / day);
        return `📚 Clear week · next: ${soonest.course} ${soonest.title} in ${days} days`
          .slice(0, 120);
      })()
    : '📚 Nothing due this week';
const message = parts.join('\n\n');
return [{ json: { title, message, priority: 3, tags: ['books'], click: page } }];
"""
)


def morning_brief() -> dict:
    names = [
        "Every morning at 7:30",
        "Deadlines",
        "New on LEARN",
        "Practice due",
        "Last sync",
        "Write the brief",
        "Send to phone",
    ]
    nodes = [
        schedule(names[0], "30 7 * * *", 0),
        study_agent(names[1], "GET", "/assessments", 220),
        study_agent(names[2], "GET", "/changes", 440),
        study_agent(names[3], "GET", "/practice/due?limit=10", 660),
        study_agent(names[4], "GET", "/jobs", 880),
        code(names[5], BRIEF_JS, 1100),
        push(names[6], 1320),
    ]
    return workflow(
        "Study Agent: morning brief",
        nodes,
        chain(*names),
        "One push at 7:30 AM: what's due this week, anything past due, what's new on "
        "LEARN, practice questions due, and whether last night's sync worked.",
    )


# ---- 2. Due tomorrow ----------------------------------------------------------------------

REMINDER_JS = (
    JS_HELPERS
    + r"""
const now = Date.now();
// Runs at 7 PM: everything due before the end of tomorrow.
const soon = list('Deadlines').filter((a) => {
  if (!a.due_at || a.status === 'COMPLETED') return false;
  const t = Date.parse(a.due_at);
  return t >= now && t - now <= 29 * 60 * 60 * 1000;
});
if (!soon.length) return [];
const title = soon.length === 1
  ? `⏰ Due soon: ${soon[0].course} ${soon[0].title}`.slice(0, 120)
  : `⏰ ${soon.length} things due by tomorrow night`;
const message = soon.map(line).join('\n') +
  '\n\n👉 Already handed in? Mark it done in Study Agent and it stops reminding you.';
return [{ json: { title, message, priority: 4, tags: ['alarm_clock'], click: page } }];
"""
)


def due_tomorrow() -> dict:
    names = ["Every evening at 7", "Deadlines", "Anything due by tomorrow?", "Send to phone"]
    nodes = [
        schedule(names[0], "0 19 * * *", 0),
        study_agent(names[1], "GET", "/assessments", 220),
        code(names[2], REMINDER_JS, 440),
        push(names[3], 660),
    ]
    return workflow(
        "Study Agent: due tomorrow",
        nodes,
        chain(*names),
        "A push at 7 PM only when something not marked done is due by the end of tomorrow.",
    )


# ---- 3. Nightly LEARN sync ----------------------------------------------------------------

SYNC_RESULT_JS = r"""
const job = $input.first().json;
const signin = job.signin_url || $env.STUDY_AGENT_PAGE;
if (job.state === 'done') return [];
let push;
if (job.state === 'failed' && /sign.?in|not authenticated/i.test(job.message || '')) {
  push = {
    title: '🔑 LEARN signed you out',
    message: "Last night's LEARN sync couldn't run because the server's browser is signed out " +
      "of LEARN. New files, announcements and deadlines won't show up until you sign in again." +
      '\n\n👉 Tap to open the sign-in window, log in to LEARN (password and Duo), then press ' +
      'Sync in Study Agent.',
    priority: 4, tags: ['key'], click: signin,
  };
} else if (job.state === 'running') {
  push = {
    title: "🐢 Last night's LEARN sync is still going",
    message: 'It started over 3 hours ago; a normal sync takes about 40 minutes. It may be stuck ' +
      'on a slow page.\n\n👉 Open Study Agent: if the sync button still shows it running, ' +
      'restart it with: cd ~/projects/study-agent && docker compose restart dashboard',
    priority: 3, tags: ['turtle'], click: $env.STUDY_AGENT_PAGE,
  };
} else if (job.state === 'failed') {
  push = {
    title: "⚠️ Last night's LEARN sync failed",
    message: `It stopped with: ${job.message}\n\n👉 Press Sync in Study Agent to try again. ` +
      'If it fails again, ask Claude to look.',
    priority: 3, tags: ['warning'], click: $env.STUDY_AGENT_PAGE,
  };
} else {
  push = {
    title: "⚠️ Last night's LEARN sync was cut off",
    message: 'Study Agent restarted in the middle of it (usually a deploy or a reboot), so ' +
      "some courses weren't checked.\n\n👉 Press Sync in Study Agent to run it again.",
    priority: 3, tags: ['warning'], click: $env.STUDY_AGENT_PAGE,
  };
}
return [{ json: push }];
"""


def nightly_sync() -> dict:
    names = [
        "Every night at 3:30",
        "Start the sync",
        "Wait 5 minutes",
        "Check on it",
        "Still running?",
        "Explain if it didn't work",
        "Send to phone",
    ]
    nodes = [
        schedule(names[0], "30 3 * * *", 0),
        study_agent(names[1], "POST", "/jobs/sync", 220, never_error=True),
        wait(names[2], 5, 440),
        study_agent(names[3], "GET", "/jobs", 660),
        # Keep checking every 5 minutes, for up to 3 hours.
        condition(names[4], "$json.state === 'running' && $runIndex < 36", 880),
        code(names[5], SYNC_RESULT_JS, 1100, 400),
        push(names[6], 1320, 400),
    ]
    connections = chain(names[0], names[1], names[2], names[3], names[4])
    connections[names[4]] = {
        "main": [
            [{"node": names[2], "type": "main", "index": 0}],
            [{"node": names[5], "type": "main", "index": 0}],
        ]
    }
    connections.update(chain(names[5], names[6]))
    return workflow(
        "Study Agent: nightly LEARN sync",
        nodes,
        connections,
        "Syncs LEARN at 3:30 AM (which also indexes new files), checks every 5 "
        "minutes until it finishes, and pushes only if it didn't work, e.g. when "
        "LEARN signed the server's browser out.",
    )


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for build, file in (
        (morning_brief, "morning-brief.json"),
        (due_tomorrow, "due-tomorrow.json"),
        (nightly_sync, "nightly-sync.json"),
    ):
        flow = build()
        (OUT / file).write_text(
            json.dumps(flow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )
        print(f"{file:<20} {flow['name']:<34} {len(flow['nodes'])} nodes")
