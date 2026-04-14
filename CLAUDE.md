# Broadhead Automations — Project Instructions

## Client
Broadhead Automations — Sean's AI workflow automation business website and client-facing presence.

## What We're Building
End-to-end inbound booking funnel across three channels — website chat, inbound SMS, Vapi voice — that qualifies every lead and books 30-minute consultations on Sean's Google Calendar (Wed–Fri, 10–12 and 1–2:30 PT).

See `workflows/booking-automation.md` for the master SOP (WF1 chat / WF2 SMS / WF3 Vapi call-end, Vapi + Twilio setup, confirmation email/SMS flow). **Always read that file first.**

The chat bot is named **Fletcher** (the craftsman who builds arrows).

## Current State
- **Website**: [index.html](index.html) — Fletcher chat UI live; points at the n8n webhook `/webhook/broadhead-chat/chat`. Signal-routing canvas network replaces the old wireframe SVG. Twilio number `208-623-9442` shown in the Contact section.
- **`.env`**: dedicated `BROADHEAD_*` block for Twilio/Vapi/Calendar wiring.
- **n8n + Vapi**: **voice stack fully live 2026-04-13**.
  - **WF1** (Chat Booking Agent, `hEsEEtfYEldhP8Eb`) — Fletcher chat widget, books on Sean's calendar, Telegram ping via `@BroadheadAutomationsBot`.
  - **WF3** (Vapi Call Ended, `3WnYo3El2EYQ6zr8`) — single Telegram ping per call at end-of-call.
  - **WF4** (Vapi Booking Backend, `saHWTOp2soVZu6lT`) — `check_availability` + `book_consultation` called by Fletcher during the live call.
  - **Fletcher Vapi assistant** `30843d88-531d-4f6f-a086-dda77d7cc205` on Vapi number `+12087389168` — calls book directly in-call (not just intent capture). `serverMessages:["end-of-call-report"]` (critical — default firehose spams WF3).
  - Pending: Sean to point Twilio `+12086239442` voice webhook at the Vapi number, and fix Google Calendar display timezone back to Pacific (events store correctly, UI displays in ET).
  - **WF2** (SMS Booking Agent) still blocked on Twilio A2P 10DLC clearance.
- **Legacy**: `tools/chat-server.js` + AWS Lambda endpoint still exist as dormant fallback; decommission after two weeks of clean n8n operation. `workflows/chatbot-lead-capture.md` documents that old Aria-on-Lambda setup — **superseded by `booking-automation.md`** once WF1 is live.

## Key Files
- `workflows/booking-automation.md` — Master SOP (WF1/WF2/WF3 build guide, Vapi + Twilio config, testing checklist)
- `workflows/chatbot-lead-capture.md` — **Superseded**; still describes the Lambda fallback path
- `index.html` — Main website (Fletcher chat widget + signal-routing network visual)
- `brand_assets/` — Logo, colors, brand guide
- `tools/` — Project-specific tooling (`chat-server.js` is the dormant Lambda backend)
- `context/ideas-log.md` — Strategic ideas and decisions
- `prompts/` — Business prompts (also mirrored in root `workflows/ai-business/`)

## Frontend
- Uses `serve.mjs` for local dev server (port 3000)
- Uses `screenshot.mjs` + `record.mjs` for visual QA
- Invoke the `frontend-design` skill before writing frontend code
