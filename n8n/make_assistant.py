"""Write the home server assistant for n8n into workflows/assistant.json.

A chat agent you can ask "what's due this week?", "what's my plan today?" or "who replied to
my emails?". It answers from Study Agent and the internship tracker through the tools below
and can do nothing else: every tool is a fixed request, so the model chooses which to call
but never the address, the method or what is sent.

It reads STUDY_AGENT_URL, STUDY_AGENT_TOKEN, STUDY_AGENT_PAGE and INTERN_AGENT_URL from
n8n's environment. The OpenAI key is a credential saved in n8n (add-openai-key.sh), never
part of this file.
"""

import json
from typing import Any

from make_workflows import OUT, Node, _id, code, workflow

NAME = "Home server assistant"
# The cheapest model that calls tools well; it only looks things up and sums them up.
MODEL = "gpt-5-mini"
# The credential add-openai-key.sh saves in n8n. It reads these two from assistant.json.
OPENAI_KEY_ID = "homeAssistantKey"
OPENAI_KEY_NAME = "OpenAI (home server assistant)"

AGENT = "Assistant"

INSTRUCTIONS = """\
You are the assistant for Aarav's home server. It is \
{{ $now.setZone('America/Toronto').toFormat("cccc d LLLL yyyy, h:mm a") }} in Toronto.

Answer only from what the tools return in this conversation. Never guess a date, a name, a \
status or a number. If a tool fails or returns nothing, say which one in plain words and what \
Aarav can do about it. If a question is not about his coursework or his internship search, \
say that is all you can look up.

Study Agent holds his University of Waterloo coursework:
- Deadlines lists every piece of coursework. due_local is already Toronto time; use it as \
written and do not convert it. A status of COMPLETED means he marked it done, and OVERDUE \
means the time has passed and he has not.
- Today's study plan says how many minutes to spend on what today.
- Today's check-up says whether today's questions are ready and how many he has answered.
- Last sync says whether the last read of LEARN worked. If it failed because LEARN signed \
the browser out, give him the sign-in link it returns.
- Start a LEARN sync starts a new read of LEARN. Call it only when he asks for a sync in his \
latest message, never on your own, and tell him it takes several minutes.

The internship tracker holds the people and postings he is following for a Winter 2027 \
internship:
- Internship leads lists them. A status of contacted means his first email was sent; \
replied_at is set once they answered.
- Follow-ups preview shows who would get an automatic follow-up next, who has replied and \
whose address bounced. It is a preview and sends nothing.

Times other than due_local are UTC; Toronto is UTC\
{{ $now.setZone('America/Toronto').toFormat('ZZ') }} today.

You cannot send email, message anyone, apply to anything, or change or delete data, and no \
tool here does. If he asks for one of those, say it is done from Study Agent \
({{ $env.STUDY_AGENT_PAGE }}) or the tracker ({{ $env.INTERN_AGENT_URL }}).

Keep answers short: a few lines or a short list, most urgent first, with the day and time."""


def tool(
    name: str,
    about: str,
    method: str,
    url: str,
    x: int,
    token: bool = False,
    body: dict[str, Any] | None = None,
    inside: str = "",
    keep: tuple[str, ...] = (),
    never_error: bool = False,
) -> Node:
    """One fixed request the agent may make. `keep` names the only fields it gets back."""
    options: dict[str, Any] = {"timeout": 60000}
    if never_error:  # e.g. 409 "another task is running" is an answer, not a failure
        options["response"] = {"response": {"neverError": True}}
    parameters: dict[str, Any] = {
        "toolDescription": about,
        "method": method,
        "url": url,
        "options": options,
    }
    if token:
        parameters["sendHeaders"] = True
        parameters["headerParameters"] = {
            "parameters": [
                {"name": "Authorization", "value": "=Bearer {{ $env.STUDY_AGENT_TOKEN }}"}
            ]
        }
    if body is not None:
        parameters |= {
            "sendBody": True,
            "contentType": "json",
            "specifyBody": "json",
            "jsonBody": json.dumps(body),
        }
    if keep:
        # Without this the model is sent whole pages of text it never needs (and you pay
        # for): the tracker's lead list alone is about 800 KB.
        parameters |= {
            "optimizeResponse": True,
            "responseType": "json",
            "dataField": inside,
            "fieldsToInclude": "selected",
            "fields": ",".join(keep),
        }
    return {
        "id": _id(f"{NAME}/{name}"),
        "name": name,
        "type": "n8n-nodes-base.httpRequestTool",
        "typeVersion": 4.2,
        "position": [x, 540],
        "parameters": parameters,
    }


def tools() -> list[Node]:
    study = "={{ $env.STUDY_AGENT_URL }}"
    tracker = "={{ $env.INTERN_AGENT_URL }}"
    return [
        tool(
            "Deadlines",
            "Every assignment, quiz, test, lab, project and exam in his courses, with when it "
            "is due in Toronto time and whether it is done. Use for anything about what is "
            "due, overdue or coming up.",
            "GET",
            study + "/assessments",
            660,
            token=True,
            keep=("course", "title", "type", "due_local", "status"),
        ),
        tool(
            "Today's study plan",
            "How many minutes to spend on which coursework today, and why.",
            "GET",
            study + "/practice/plan",
            880,
            token=True,
        ),
        tool(
            "Today's check-up",
            "Whether today's practice questions are ready, how many are answered and how "
            "many were right.",
            "GET",
            study + "/practice/checkup",
            1100,
            token=True,
            keep=("day", "prepared", "answered", "right"),
        ),
        tool(
            "Last sync",
            "The last read of LEARN: whether it is running, worked or failed, when, and the "
            "link to sign the server's browser in to LEARN.",
            "GET",
            study + "/jobs",
            1320,
            token=True,
            keep=("name", "state", "message", "started_at", "finished_at", "signin_url"),
        ),
        tool(
            "Start a LEARN sync",
            "Starts a new read of LEARN, which takes several minutes. Only when he asks for a "
            "sync in his latest message.",
            "POST",
            study + "/jobs/sync",
            1540,
            token=True,
            keep=("name", "state", "message", "detail"),
            never_error=True,
        ),
        tool(
            "Internship leads",
            "Every founder and posting in the internship tracker: company, who, status, when "
            "the first email was sent and when they replied.",
            "GET",
            tracker + "/api/leads",
            1760,
            inside="leads",
            keep=(
                "company",
                "kind",
                "contact_name",
                "contact_role",
                "status",
                "sent_at",
                "replied_at",
                "followups_stopped",
                "round",
                "location",
                "posting_title",
                "deadline",
            ),
        ),
        tool(
            "Follow-ups preview",
            "Who would get an automatic follow-up email next, who has replied and whose "
            "address bounced. A preview: it sends nothing.",
            "POST",
            tracker + "/api/followups/run",
            1980,
            # Fixed here, so the model cannot ask for a real send.
            body={"dry_run": True},
        ),
    ]


def assistant() -> dict:
    chat = "Chat"
    test = "Test question"
    model = "OpenAI"
    memory = "This conversation"
    nodes: list[Node] = [
        {
            "id": _id(f"{NAME}/{chat}"),
            "name": chat,
            "type": "@n8n/n8n-nodes-langchain.chatTrigger",
            "typeVersion": 1.4,
            "position": [0, 300],
            "webhookId": _id(f"{NAME}/chat-page"),
            "parameters": {
                # A chat page at <n8n>/webhook/<webhookId>/chat, for people signed in to n8n.
                "public": True,
                "mode": "hostedChat",
                "authentication": "n8nUserAuth",
                "initialMessages": "Ask me what's due, what today's plan is, how the last "
                "LEARN sync went, or who has replied to your internship emails.",
                # Also listed under Chat inside n8n.
                "availableInChat": True,
                "agentName": NAME,
                "agentDescription": "Looks things up in Study Agent and the internship "
                "tracker. It cannot send, apply or change anything.",
                "options": {
                    "title": NAME,
                    "subtitle": "Study Agent and the internship tracker",
                    "inputPlaceholder": "What's due this week?",
                    "responseMode": "streaming",
                },
            },
        },
        # For "Run it now" and the CLI, which have no chat message to pass on.
        code(
            test,
            "return [{ json: { chatInput: 'What is due in the next 7 days?', "
            "sessionId: 'self-test' } }];",
            220,
            500,
        ),
        {
            "id": _id(f"{NAME}/{AGENT}"),
            "name": AGENT,
            "type": "@n8n/n8n-nodes-langchain.agent",
            "typeVersion": 3.1,
            "position": [440, 300],
            "parameters": {
                "promptType": "auto",
                "text": "={{ $json.chatInput }}",
                "options": {"systemMessage": "=" + INSTRUCTIONS, "maxIterations": 6},
            },
        },
        {
            "id": _id(f"{NAME}/Send answer to ntfy"),
            "name": "Send answer to ntfy",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [680, 300],
            "parameters": {
                "method": "POST",
                "url": "={{ $env.NTFY_SERVER }}",
                "sendBody": True,
                "contentType": "json",
                "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify({ topic: $env.NTFY_TOPIC, "
                "title: 'Home server assistant', message: $json.output }) }}",
                "options": {"timeout": 15000},
            },
        },
        {
            "id": _id(f"{NAME}/{model}"),
            "name": model,
            "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
            "typeVersion": 1.3,
            "position": [220, 540],
            "parameters": {"model": {"__rl": True, "mode": "id", "value": MODEL}, "options": {}},
            "credentials": {"openAiApi": {"id": OPENAI_KEY_ID, "name": OPENAI_KEY_NAME}},
        },
        {
            "id": _id(f"{NAME}/{memory}"),
            "name": memory,
            "type": "@n8n/n8n-nodes-langchain.memoryBufferWindow",
            "typeVersion": 1.3,
            "position": [440, 540],
            "parameters": {
                "sessionIdType": "fromInput",
                "sessionKey": "={{ $json.sessionId }}",
                # The last few questions and answers, kept only while n8n is running.
                "contextWindowLength": 6,
            },
        },
        *tools(),
    ]

    def into_agent(kind: str) -> dict[str, Any]:
        return {kind: [[{"node": AGENT, "type": kind, "index": 0}]]}

    connections: dict[str, Any] = {
        chat: into_agent("main"),
        test: into_agent("main"),
        model: into_agent("ai_languageModel"),
        memory: into_agent("ai_memory"),
        **{node["name"]: into_agent("ai_tool") for node in tools()},
    }
    connections[AGENT] = {
        "main": [[{"node": "Send answer to ntfy", "type": "main", "index": 0}]]
    }
    flow = workflow(
        NAME,
        nodes,
        connections,
        "A chat agent that answers from Study Agent and the internship tracker: deadlines, "
        "today's plan and check-up, the last LEARN sync, leads and who replied. It can start "
        "a LEARN sync when asked and preview follow-ups; it cannot send, apply, change or "
        "delete anything.",
    )
    flow["connections"]["Run it now"] = {"main": [[{"node": test, "type": "main", "index": 0}]]}
    return flow


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    flow = assistant()
    (OUT / "assistant.json").write_text(
        json.dumps(flow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"{'assistant.json':<20} {flow['name']:<34} {len(flow['nodes'])} nodes")
