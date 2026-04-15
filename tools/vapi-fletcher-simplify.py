#!/usr/bin/env python3
"""
Simplify Fletcher (Broadhead Vapi assistant) to the 5-turn script.

Drops qualification (business_type, pain_point, hours_per_week, team_size).
Drops "Pacific Time" wording. Switches to 1-hour slots at 10am/11am/1pm/2pm.
Keeps off-window pending path. Simplifies referral to raw-only capture.

Snapshots the current assistant to clients/broadhead/context/fletcher-assistant-{ts}.json
before PATCHing. Uses curl-style UA (Vapi behind Cloudflare 403s default Python UA).
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2].parent  # /home/belkn
ENV_PATH = REPO_ROOT / ".env"
SNAPSHOT_DIR = Path(__file__).resolve().parents[1] / "context"

VAPI_BASE = "https://api.vapi.ai"
UA = "curl/8.4.0"

NEW_FIRST_MESSAGE = (
    "Thanks for calling Broadhead — this is Fletcher, Sean's AI assistant. "
    "Would you like to schedule a discovery call with Sean?"
)

NEW_SYSTEM_PROMPT = """You are Fletcher, Sean Belknap's AI assistant at Broadhead. Sean builds custom AI workflow automations for small businesses. Tone: friendly, direct, no fluff. Speak like a real person on Sean's team, not a call-center bot. Short sentences, plain words.

GOAL: Book a 1-hour discovery call with Sean on his Google Calendar. Nothing else. Qualification happens on the live call — not here.

TIMEZONE RULE: NEVER say "Pacific", "Pacific Time", or "PT" on the call. Just the day and clock time (e.g. "Wednesday at ten AM"). All slot ISOs internally use America/Los_Angeles, but the caller never hears the zone name.

THE FLOW — exactly 5 spoken turns, in order. Simplicity scales: ONE question per turn.

Turn 1 (opener — the assistant's firstMessage handles this automatically):
"Thanks for calling Broadhead — this is Fletcher, Sean's AI assistant. Would you like to schedule a discovery call with Sean?"
- If yes → Turn 2.
- If the caller asks a question first → answer briefly, then offer the call ONCE more and wait. Never re-pitch on every turn.
- If they decline → thank them, offer to take a callback number for Sean, capture whatever they give, end the call with booking_status="declined".

Turn 2 (contact):
"Great. Can I get your name and the best callback number?"
Email is NOT collected on voice — audio is too noisy for email addresses. Capture name + phone only. Acknowledge the phone with a short "got it" — do NOT read the digits back and do NOT confirm digit-by-digit. Structured-data extraction handles correctness.

Turn 3 (day):
"Is Wednesday or Friday better for you?"
After they pick, call check_availability (no args). The tool returns up to the next open 1-hour slots on Wed/Fri. An empty result means the range is FREE — never tell the caller "no availability" based on an empty list.

Turn 4 (time):
Candidate slots are 10am, 11am, 1pm, 2pm (America/Los_Angeles) on the next Wed or Fri matching their pick. Mark a candidate BLOCKED only if check_availability shows it overlapping an existing event. Everything else is OPEN.
Offer the open slots AND include the calendar date — "Wednesday" alone is ambiguous when today may also be a Wednesday or Friday:
"Can you do Wednesday the twenty-second at ten AM, eleven AM, one PM, or two PM?" (substitute the actual date of the next Wed/Fri matching their pick, list ONLY open times).
Default to the NEXT upcoming Wed or Fri that still has open slots. If the caller asks about a specific date ("this Wednesday or next Wednesday?"), name the dates explicitly.
When they pick, call book_consultation with name, phone, slot_iso, and optional notes.
On success, confirm aloud with the date: "Booked you for Wednesday <break time="0.3s" /> the twenty-second <break time="0.3s" /> at ten AM — talk soon!"
Always include the calendar date in the readback, never just the weekday. NEVER add "Pacific" after the time.

Turn 5 (referral — before saying goodbye):
"Oh, and how did you hear about Broadhead?"
Capture their verbatim answer into referral_raw. No follow-up, no normalization, no skip-on-name logic. Sean reviews raw. Move to the close.

Turn 6 (close):
"Thanks — appreciate it. Talk soon!"
(Referral question comes before the final goodbye so you don't cut them off.)

OFF-WINDOW ESCAPE HATCH (any turn):
If the caller specifically asks for a day outside Wed/Fri (Monday, Tuesday, Thursday, Saturday, Sunday) or a time other than 10am/11am/1pm/2pm (evenings, 11:30, 3pm, etc.), do NOT call check_availability or book_consultation. Say:
"Let me check with Sean about [their requested day/time] and have him confirm directly — he can usually make it work with a little heads-up. In the meantime, let me grab a few details so he can reach out."
Then continue through Turn 2 (name + phone) if you haven't already, then Turn 5 (referral), then close out. Capture the requested day/time verbatim in pending_slot_request. Set booking_status="pending". Sean confirms manually via Telegram.

BOOKING WINDOW:
- Days: Wednesday, Friday. No Thursday. No other days.
- Times: 10am, 11am, 1pm, 2pm. Top of the hour only. Never offer :30.
- Duration: 60 minutes.

SSML PACING (for booked-slot readback):
Insert `<break time="0.3s" />` between date/time units. Only the <break> tag produces audible pauses — ellipses and dashes are ignored by the voice engine. Phone numbers are NOT read back.

DO NOT:
- Ask any qualification questions (business type, pain, team size, hours per week, tools, etc.). Sean asks on the live call.
- Invent pricing, deliverables, or promises Sean hasn't made.
- Offer any slot outside Wed/Fri at 10am/11am/1pm/2pm. Off-window asks go through the pending path.
- Book before you have a name and a phone number.
- Say "Pacific", "Pacific Time", or "PT" — ever.
- Read phone numbers back digit-by-digit.
- Re-pitch the call on every turn.

STRUCTURED DATA (end-of-call capture):
Populate name, phone, slot_iso (if booked), booking_status (confirmed | pending | declined | none), pending_slot_request (verbatim off-window ask, or empty), booked (true only if booking_status="confirmed"), notes, referral_raw (caller's verbatim words about how they heard of Broadhead).
Do NOT populate email (not collected on voice). Do NOT populate business_type, pain_point, referral_source, referrer_name — those fields are deprecated.
"""


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def http(method: str, path: str, api_key: str, body: dict | None = None) -> dict:
    url = f"{VAPI_BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("User-Agent", UA)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"HTTP {e.code} on {method} {path}: {e.read().decode()}\n")
        raise


def simplify_tool_params(tool: dict) -> dict | None:
    """Drop business_type + pain_point from book_consultation's parameter schema."""
    func = tool.get("function") or {}
    if func.get("name") != "book_consultation":
        return None
    params = func.get("parameters") or {}
    props = dict(params.get("properties") or {})
    removed = []
    for k in ("business_type", "pain_point", "hours_per_week", "team_size"):
        if k in props:
            props.pop(k)
            removed.append(k)
    required = [r for r in (params.get("required") or []) if r not in removed]
    new_params = {**params, "properties": props, "required": required}
    new_func = {**func, "parameters": new_params}
    return {**tool, "function": new_func}


def simplify_structured_schema(schema: dict) -> dict:
    """Drop deprecated keys from analysisPlan.structuredDataPlan.schema."""
    if not isinstance(schema, dict):
        return schema
    props = dict(schema.get("properties") or {})
    removed = []
    for k in ("business_type", "pain_point", "hours_per_week", "team_size",
             "referral_source", "referrer_name"):
        if k in props:
            props.pop(k)
            removed.append(k)
    required = [r for r in (schema.get("required") or []) if r not in removed]
    return {**schema, "properties": props, "required": required}


def main() -> int:
    env = load_env()
    api_key = env.get("VAPI_API_KEY")
    assistant_id = env.get("BROADHEAD_VAPI_ASSISTANT_ID")
    if not api_key or not assistant_id:
        sys.stderr.write("Missing VAPI_API_KEY or BROADHEAD_VAPI_ASSISTANT_ID in .env\n")
        return 1

    print(f"GET /assistant/{assistant_id}")
    current = http("GET", f"/assistant/{assistant_id}", api_key)

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    snapshot = SNAPSHOT_DIR / f"fletcher-assistant-{ts}.json"
    snapshot.write_text(json.dumps(current, indent=2))
    print(f"  snapshot saved -> {snapshot.relative_to(REPO_ROOT)}")

    model = current.get("model") or {}
    messages = model.get("messages") or []
    sys_msg_idx = next(
        (i for i, m in enumerate(messages) if m.get("role") == "system"),
        None,
    )
    if sys_msg_idx is None:
        sys.stderr.write("No system message found on assistant.model.messages\n")
        return 2

    # Build new tools: simplify book_consultation params.
    old_tools = model.get("tools") or []
    new_tools = []
    tool_changes = []
    for t in old_tools:
        simplified = simplify_tool_params(t)
        if simplified is not None:
            new_tools.append(simplified)
            tool_changes.append(t.get("function", {}).get("name", "<unknown>"))
        else:
            new_tools.append(t)

    # Build new messages: swap system prompt.
    new_messages = [
        *messages[:sys_msg_idx],
        {**messages[sys_msg_idx], "content": NEW_SYSTEM_PROMPT},
        *messages[sys_msg_idx + 1:],
    ]

    patch = {
        "firstMessage": NEW_FIRST_MESSAGE,
        "model": {**model, "messages": new_messages, "tools": new_tools},
    }

    # Analysis plan: simplify structured data schema if present.
    analysis = current.get("analysisPlan") or {}
    sd_plan = analysis.get("structuredDataPlan") or {}
    sd_schema = sd_plan.get("schema")
    if sd_schema:
        new_schema = simplify_structured_schema(sd_schema)
        if new_schema != sd_schema:
            patch["analysisPlan"] = {
                **analysis,
                "structuredDataPlan": {**sd_plan, "schema": new_schema},
            }

    print(f"PATCH /assistant/{assistant_id}")
    print(f"  firstMessage:       changed -> simplified yes/no opener")
    print(f"  systemPrompt:       {len(messages[sys_msg_idx].get('content',''))} -> {len(NEW_SYSTEM_PROMPT)} chars")
    print(f"  tools simplified:   {tool_changes or 'none'}")
    print(f"  structuredData:     {'simplified' if 'analysisPlan' in patch else 'unchanged'}")

    updated = http("PATCH", f"/assistant/{assistant_id}", api_key, patch)

    final_msgs = (updated.get("model") or {}).get("messages") or []
    final_prompt = next(
        (m.get("content", "") for m in final_msgs if m.get("role") == "system"),
        "",
    )
    has_pacific = "Pacific" in final_prompt or "Pacific" in updated.get("firstMessage", "")
    has_business_type = any(
        "business_type" in ((t.get("function") or {}).get("parameters", {}).get("properties") or {})
        for t in (updated.get("model") or {}).get("tools") or []
    )
    ok = (
        updated.get("firstMessage") == NEW_FIRST_MESSAGE
        and not has_pacific
        and not has_business_type
    )
    print(
        f"verify: firstMessage_ok={updated.get('firstMessage') == NEW_FIRST_MESSAGE}, "
        f"pacific_in_prompt={has_pacific}, "
        f"business_type_still_in_tools={has_business_type}"
    )
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
