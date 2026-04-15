#!/usr/bin/env python3
"""
Patch Fletcher (Broadhead Vapi assistant).

Current state (2026-04-14 evening):
  - Phone-number readback REMOVED (SSML pacing didn't land cleanly on calls;
    Sean opted to drop the readback entirely rather than keep tuning).
  - Date/time readback still uses <break time="0.3s" /> SSML between units.
  - "30-minute consultation" wording dropped → just "consultation"
    (firstMessage + systemMessage).
  - voice.stability=0.45, voice.enableSsmlParsing=true (SSML parsing must be
    explicit — defaults to false on Vapi or tags get spoken literally).

Does NOT touch serverMessages, backgroundSound, transcriber, or function tools.
Uses curl-style User-Agent (Vapi behind Cloudflare 403s default Python UA).
"""

from __future__ import annotations

import json
import re
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

NEW_STABILITY = 0.45

NEW_FIRST_MESSAGE = (
    "Thanks for calling Broadhead — this is Fletcher, Sean's AI assistant. "
    "Sean keeps Wednesday through Friday open for 30-minute consults. "
    "Want me to get you booked in, or is there something else first?"
)

OPENING_LINE_OLD_PATTERNS = [
    r"OPENING: The greeting already asked if they want to schedule a consult\.",
    r"OPENING: The greeting already offered a consult with Sean\.",
]
OPENING_LINE_NEW = (
    "OPENING: The greeting already offered a 30-minute consult on Wednesday "
    "or Friday with Sean."
)

READBACK_INSTRUCTIONS = """

## CRITICAL: Phone, date, and time handling

PHONE NUMBERS — capture silently. After the caller gives their callback
number, just acknowledge with a short "got it" and move on. Do NOT read the
number back, do NOT confirm digit-by-digit, do NOT say "let me make sure I
have that right." The structured-data capture handles correctness; reading
phone numbers back over the phone consistently mangles them and frustrates
callers.

DATE / TIME — when confirming a booked slot back to the caller, insert a
`<break time="0.3s" />` SSML tag between each unit. The voice engine ignores
ellipses and dashes — only the `<break>` tag produces audible pauses.

Required date/time format:
  `Booked you for Wednesday <break time="0.3s" /> April fifteenth <break time="0.3s" /> at one PM Pacific — correct?`
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


def upgrade_system_prompt(prompt: str) -> str:
    """Apply current edits idempotently."""
    # Strip any prior readback section we previously appended.
    prompt = re.sub(
        r"\n+## CRITICAL:[^\n]*readback[^\n]*\n.*?(?=\n## |\Z)",
        "",
        prompt,
        flags=re.DOTALL | re.IGNORECASE,
    )
    prompt = re.sub(
        r"\n+## CRITICAL:[^\n]*Phone, date[^\n]*\n.*?(?=\n## |\Z)",
        "",
        prompt,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # Strip leftover ellipsis-style example lines from older prompt edits.
    prompt = re.sub(
        r"^.*\b\d(\.\.\.\s*\d){2,}.*$\n?",
        "",
        prompt,
        flags=re.MULTILINE,
    )
    # Drop "30-minute" wording in the system prompt body — Sean wants just
    # "consultation" there. (The firstMessage DOES say "30-minute consults"
    # intentionally, as the opener anchor on cadence + length.)
    prompt = re.sub(r"\b30[- ]minute\s+consultation\b", "consultation", prompt, flags=re.IGNORECASE)
    prompt = re.sub(r"\b30[- ]minute\s+slots?\b", "open slots", prompt, flags=re.IGNORECASE)
    # Rewrite the OPENING line so Fletcher's internal mental model matches the
    # new greeting wording (Wed–Fri, 30-min consult anchor).
    for pat in OPENING_LINE_OLD_PATTERNS:
        prompt = re.sub(pat, OPENING_LINE_NEW, prompt)
    # Tidy trailing whitespace before re-appending the new section.
    return prompt.rstrip() + READBACK_INSTRUCTIONS


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

    voice = current.get("voice") or {}
    old_stability = voice.get("stability")
    old_ssml = voice.get("enableSsmlParsing")
    old_first = current.get("firstMessage", "")
    messages = (current.get("model") or {}).get("messages") or []
    sys_msg_idx = next(
        (i for i, m in enumerate(messages) if m.get("role") == "system"),
        None,
    )
    if sys_msg_idx is None:
        sys.stderr.write("No system message found on assistant.model.messages\n")
        return 2

    old_prompt = messages[sys_msg_idx].get("content", "")
    new_prompt = upgrade_system_prompt(old_prompt)

    target_state = (
        old_prompt == new_prompt
        and old_stability == NEW_STABILITY
        and old_ssml is True
        and old_first == NEW_FIRST_MESSAGE
    )
    if target_state:
        print("No changes needed — assistant already in target state.")
        return 0

    patch = {
        "firstMessage": NEW_FIRST_MESSAGE,
        "voice": {**voice, "stability": NEW_STABILITY, "enableSsmlParsing": True},
        "model": {
            **current.get("model", {}),
            "messages": [
                *messages[:sys_msg_idx],
                {**messages[sys_msg_idx], "content": new_prompt},
                *messages[sys_msg_idx + 1:],
            ],
        },
    }

    print(f"PATCH /assistant/{assistant_id}")
    print(f"  firstMessage:    {'changed' if old_first != NEW_FIRST_MESSAGE else 'unchanged'}")
    print(f"  voice.stability: {old_stability} -> {NEW_STABILITY}")
    print(f"  enableSsmlParsing: {old_ssml} -> True")
    print(f"  systemMessage:   {len(old_prompt)} -> {len(new_prompt)} chars")
    updated = http("PATCH", f"/assistant/{assistant_id}", api_key, patch)

    final_voice = updated.get("voice") or {}
    final_msgs = (updated.get("model") or {}).get("messages") or []
    final_prompt = next(
        (m.get("content", "") for m in final_msgs if m.get("role") == "system"),
        "",
    )
    has_phone_readback = bool(
        re.search(r"phone[\s\S]{0,80}readback", final_prompt, flags=re.IGNORECASE)
        and "Got it — that's 2 <break" in final_prompt
    )
    # Caller-facing "30-minute consultation/slots" must be gone. Internal rule
    # ("Appointments are exactly 30 minutes") stays — Fletcher needs the slot length.
    has_30min = bool(
        re.search(r"30[- ]minute\s+(consultation|slots?)", updated.get("firstMessage", "") + final_prompt, flags=re.IGNORECASE)
    )
    ok = (
        final_voice.get("stability") == NEW_STABILITY
        and final_voice.get("enableSsmlParsing") is True
        and updated.get("firstMessage") == NEW_FIRST_MESSAGE
        and not has_phone_readback
        and not has_30min
    )
    print(
        f"verify: stability={final_voice.get('stability')}, "
        f"enableSsmlParsing={final_voice.get('enableSsmlParsing')}, "
        f"firstMessage_ok={updated.get('firstMessage') == NEW_FIRST_MESSAGE}, "
        f"phone_readback_present={has_phone_readback}, "
        f"30-minute_present={has_30min}"
    )
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
