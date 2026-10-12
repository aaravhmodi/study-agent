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
            # Only ntfy's fields: an item can carry more (the data check's report for Claude).
            "jsonBody": "={{ JSON.stringify({ topic: $env.NTFY_TOPIC, title: $json.title, "
            "message: $json.message, priority: $json.priority, tags: $json.tags, "
            "click: $json.click }) }}",
            "options": {"timeout": 15000},
        },
    }


def ask_claude(name: str, job: str, x: int, y: int = 300) -> Node:
    """Start a claude-harness job with the item's report as its context."""
    return {
        "id": _id(name),
        "name": name,
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [x, y],
        "parameters": {
            "method": "POST",
            "url": "={{ $env.HARNESS_URL }}/jobs/" + job,
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [
                    {"name": "Authorization", "value": "=Bearer {{ $env.HARNESS_TOKEN }}"}
                ]
            },
            "sendBody": True,
            "contentType": "json",
            "specifyBody": "json",
            "jsonBody": "={{ JSON.stringify({ context: $json.report }) }}",
            # Busy, over its daily limit or down: the push already went out, so carry on.
            "options": {"timeout": 15000, "response": {"response": {"neverError": True}}},
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


# ---- 4. Data check ------------------------------------------------------------------------

CHECK_JS = r"""
const now = Date.now();
const day = 24 * 60 * 60 * 1000;
const items = $('Deadlines').all().map((i) => i.json).filter((a) => a && a.title);
const courses = $('Courses').all().map((i) => i.json).filter((c) => c && c.id);
const job = $('Last sync').first().json;
const problems = [];
// Problems a misread page could cause; Claude is asked to look at new ones.
const forClaude = new Set();
const readingBug = (text) => { problems.push(text); forClaude.add(text); };

// 1. Titles that are page furniture, not work ("Reem Roufail posted").
for (const a of items) {
  if (/\b(posted|edited|published|updated)$/i.test(a.title) || a.title.length > 90) {
    readingBug(`${a.course}: "${a.title.slice(0, 60)}" doesn't look like real coursework.`);
  }
}

// 2. A course with nothing dated at all was probably not read properly.
for (const c of courses) {
  const dated = items.filter((a) => a.course_id === c.id && a.due_at);
  if (!dated.length) readingBug(`${c.code || c.name}: no deadlines with dates were found.`);
}

// 3. Gaps in a numbered series: Assignment 1, 2 and 4 means 3 was missed.
const numbered = new RegExp(
  '^(Assignment|Quiz|Lab|Phase|Homework|Problem Set|Tutorial|TM|Test)\\s*#?\\s*(\\d{1,2})\\b', 'i');
const series = {};
for (const a of items) {
  const m = a.title.match(numbered);
  if (!m) continue;
  const key = `${a.course}|${m[1].toLowerCase()}`;
  series[key] = series[key] || { course: a.course, kind: m[1], numbers: new Set() };
  series[key].numbers.add(+m[2]);
}
for (const { course, kind, numbers } of Object.values(series)) {
  const top = Math.max(...numbers);
  const missing = [];
  for (let n = 1; n < top; n++) if (!numbers.has(n)) missing.push(n);
  if (missing.length && missing.length <= 5) {
    const verb = missing.length === 1 ? 'is' : 'are';
    readingBug(`${course}: ${kind} ${missing.join(', ')} ${verb} missing ` +
                  `(found up to ${kind} ${top}).`);
  }
}

// 4. Exams without a date.
for (const a of items) {
  if (!a.due_at && /\b(midterm|final)\b/i.test(a.title)) {
    problems.push(`${a.course}: "${a.title}" has no date yet.`);
  }
}

// 5. The same thing saved twice.
const byKey = {};
for (const a of items) {
  if (!a.due_at) continue;
  const key = `${a.course}|${a.title.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()}`;
  (byKey[key] = byKey[key] || []).push(Date.parse(a.due_at));
}
for (const [key, times] of Object.entries(byKey)) {
  const sorted = times.sort((x, y) => x - y);
  if (sorted.some((t, i) => i && t - sorted[i - 1] < 2 * day)) {
    const [course, title] = key.split('|');
    readingBug(`${course}: "${title}" is saved more than once.`);
  }
}

// 6. Stale or failed sync.
const scanned = courses.map((c) => Date.parse(c.last_scanned_at)).filter(Boolean);
if (scanned.length && now - Math.max(...scanned) > 36 * 60 * 60 * 1000) {
  problems.push('LEARN hasn\'t been read in over a day and a half.');
}
if (job.name === 'sync' && job.state === 'failed') {
  problems.push(`Last sync failed: ${job.message}`);
}

// Push only what's new since the last check, so the same list doesn't arrive every day.
// (n8n keeps this between scheduled runs; a manual test run always reports everything.)
const memory = $getWorkflowStaticData('global');
const before = new Set(memory.reported || []);
memory.reported = problems;
const fresh = problems.filter((p) => !before.has(p));
if (!fresh.length) return [];
const shown = fresh.slice(0, 12);
const still = problems.length - fresh.length;
return [{ json: {
  title: `🧐 Study Agent: ${fresh.length} new thing${fresh.length === 1 ? '' : 's'} to check`,
  message: shown.map((p) => `• ${p}`).join('\n') +
    (fresh.length > shown.length ? `\n…and ${fresh.length - shown.length} more` : '') +
    (still ? `\n(${still} from earlier still open.)` : '') +
    '\n\n👉 Check these against LEARN or the Outline, and ask Claude to fix how they\'re read.',
  priority: 3, tags: ['mag'], click: $env.STUDY_AGENT_PAGE,
  report: fresh.filter((p) => forClaude.has(p)).join('\n'),
} }];
"""


def data_check() -> dict:
    names = [
        "Every morning at 5",
        "Deadlines",
        "Courses",
        "Last sync",
        "Look for anything wrong",
        "Send to phone",
    ]
    nodes = [
        schedule(names[0], "0 5 * * *", 0),
        study_agent(names[1], "GET", "/assessments", 220),
        study_agent(names[2], "GET", "/courses", 440),
        study_agent(names[3], "GET", "/jobs", 660),
        code(names[4], CHECK_JS, 880),
        push(names[5], 1100),
        condition("Could a page be misread?", "$json.report !== ''", 1100, 500),
        ask_claude("Ask Claude to look", "study-agent-data-check", 1320, 500),
    ]
    connections = chain(*names)
    connections[names[4]]["main"][0].append(
        {"node": "Could a page be misread?", "type": "main", "index": 0}
    )
    connections["Could a page be misread?"] = {
        "main": [[{"node": "Ask Claude to look", "type": "main", "index": 0}], []]
    }
    return workflow(
        "Study Agent: data check",
        nodes,
        connections,
        "After the nightly sync, checks what was read from LEARN and the Outlines: junk "
        "titles, courses with no dated deadlines, gaps like Assignment 1, 2, 4, exams with no "
        "date, duplicates, and a stale or failed sync. Pushes only when something looks off, "
        "and asks Claude (claude-harness) to look at new problems a misread page could cause.",
    )


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for build, file in (
        (morning_brief, "morning-brief.json"),
        (due_tomorrow, "due-tomorrow.json"),
        (nightly_sync, "nightly-sync.json"),
        (data_check, "data-check.json"),
    ):
        flow = build()
        (OUT / file).write_text(
            json.dumps(flow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )
        print(f"{file:<20} {flow['name']:<34} {len(flow['nodes'])} nodes")
