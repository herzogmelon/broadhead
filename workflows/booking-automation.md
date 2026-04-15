# Broadhead Automations — Booking Automation

## Objective
Convert every inbound contact (website chat, inbound SMS, inbound phone call) into a booked lead on a 1-hour discovery call on Sean's Google Calendar — automatically, in the caller's own language, with confirmation sent by email and SMS. **Simplicity scales, complexity fails**: Fletcher collects name/phone/email, a day, a time, and a referral source. Nothing else. Qualification happens on the call.

## Business Context
- **Client / operator**: Sean Belknap (also the service provider)
- **Inbound channels**: website chat widget on broadheadautomations.com, inbound SMS to the Broadhead Twilio number, inbound voice to the Vapi-hosted number
- **Bookable hours**: Wed/Fri, **10:00–12:00 and 13:00–15:00 America/Los_Angeles**, 60-minute slots at the top of the hour (10am, 11am, 1pm, 2pm)
- **Assistant name**: Fletcher (the craftsman who builds arrows — pairs with the broadhead brand)
- **TZ language**: Fletcher NEVER says "Pacific Time" / "PT" / "Pacific" in speech, confirmations, or UI copy. Calendar still stores events in `America/Los_Angeles` — we just don't verbalize the zone.

---

## Architecture

```
Website (broadheadautomations.com)
  └─ Fletcher chat widget (index.html:867+) ──► n8n WF1 (Chat Booking Agent)
                                                 └─ Google Calendar (book)
                                                 └─ Gmail + Twilio (confirm lead)
                                                 └─ Notion + Telegram (notify Sean)

Broadhead Twilio number (+12086239442)
  ├─ Inbound SMS ──► n8n WF2 (SMS Booking Agent)   [same tools as WF1]
  └─ Inbound voice ──► Vapi AI assistant
                         └─ End-of-call webhook ──► n8n WF3 (Vapi Call Ended)
                                                       ├─ booked?  → Telegram Sean + Notion
                                                       └─ no-book → Twilio SMS caller
                                                                      (caller's reply re-enters WF2)
```

All three workflows share the same **booking window**, the same **Data Table** (`broadhead_conversations`), the same **Google Calendar** (Sean's primary), and the same **confirmation template**.

---

## n8n Integration

**Instance**: `broadheadautomations.app.n8n.cloud`

### Workflow 1: Broadhead — Chat Booking Agent
- **n8n ID**: `hEsEEtfYEldhP8Eb` (13 nodes) — deployed and **active** 2026-04-13; end-to-end test passed (Fletcher booked, calendar event in PT, Telegram ping from `@BroadheadAutomationsBot`)
- **Webhook URL**: `https://broadheadautomations.app.n8n.cloud/webhook/broadhead-chat/chat`
- **Trigger**: Chat Trigger (`@n8n/n8n-nodes-langchain.chatTrigger`), webhook path `broadhead-chat` → public URL `POST /webhook/broadhead-chat/chat`
- **Memory**: in-process `Window Buffer Memory` sub-node connected *directly to the Chat Trigger* AND to the AI Agent (20-message window, keyed on `sessionId`). Do **not** set `loadPreviousSession: "memory"` without this (Goody's lesson).
- **Embed**: already wired — [index.html:870](../index.html#L870) points `CHAT_WEBHOOK` at this URL.
- **CORS**: `allowedOrigins: "https://broadheadautomations.com"` (use `"*"` only for local dev, tighten before launch).
- **Node graph**:
  ```
  Chat Trigger ─┬─► Window Buffer Memory
                └─► Prepare Context (Set: today's date, booking-window JSON, channel="chat")
                        │
                        ▼
                    AI Agent ◄── OpenRouter Chat Model (Gemini 2.5 Flash)
                             ◄── Window Buffer Memory
                             ◄── Google Calendar tool: Check Availability
                             ◄── Google Calendar tool: Book Consultation
                             ◄── Code tool: Validate Slot
                        │
                        ▼
              Process Response (Code: extract <<<CAPTURE>>>{...}<<<END>>> marker, strip from reply)
                        │
              ┌─────────┴────────┐
              ▼                  ▼
         Captured? (IF)     Respond to Chat
              │
    ┌─────────┼──────────┐
    ▼         ▼          ▼
  Notion   Telegram   Send Confirmations (see §Confirmations)
  ```

### Workflow 2: Broadhead — SMS Booking Agent
- **Trigger**: Webhook (`n8n-nodes-base.webhook`), path `broadhead-sms-in`, method POST, response mode `onReceived` (ack Twilio fast, reply async)
- **Memory**: Data Table `broadhead_conversations` keyed on `phone_number` (Twilio `From`)
- **Twilio config**: Messaging → "A message comes in" → `POST https://broadheadautomations.app.n8n.cloud/webhook/broadhead-sms-in`
- **Loop prevention**: IF node — skip reply when `From === BROADHEAD_OWNER_PHONE` (hardcode the value; `$env` is blocked on n8n Cloud)
- **Node graph**:
  ```
  Webhook → Is Sean? (IF From == owner) → stop
         ↓ no
    Load Conversation (Data Table: get row by phone_number)
         ↓
    Prepare Context (Set: today's date, booking-window JSON, channel="sms", prior history)
         ↓
    AI Agent ◄── same model + same 3 tools as WF1 (share credentials)
         ↓
    Process Response (Code: extract marker, strip)
         ↓
    Send SMS Reply (Twilio node)
         ↓
    Update Conversation (Data Table upsert)
         ↓
    Captured? (IF) ─► Notion + Telegram + Send Confirmations
  ```

### Workflow 3: Broadhead — Vapi Call Ended
- **n8n ID**: `3WnYo3El2EYQ6zr8` (3 nodes) — deployed and **active** 2026-04-13; tested end-to-end with real inbound voice call
- **Trigger**: Webhook, path `broadhead-vapi-callend`, POST, onReceived
- **Purpose**: single Telegram ping to Sean at end-of-call (booked or missed).
- **Node graph**:
  ```
  Vapi Webhook → Parse Vapi Data (Code) → Notify Sean (Telegram @BroadheadAutomationsBot)
  ```
- Parse Vapi Data extracts `message.analysis.structuredData.booked` + fields; branches the Telegram message between "Broadhead voice booking" (booked) and "missed voice booking" (transcript snippet).
- **Gotcha**: Vapi defaults `serverMessages` to a firehose (speech-update, status-update, transcript, tool-calls, end-of-call-report — dozens per call). MUST PATCH `serverMessages: ["end-of-call-report"]` on the assistant or Sean gets 50–100 Telegram pings per call.

### Workflow 4: Broadhead — Vapi Booking Backend
- **n8n ID**: `saHWTOp2soVZu6lT` (19 nodes) — deployed and **active** 2026-04-13; Vapi voice paths tested end-to-end; web paths added 2026-04-14.
- **Purpose**: Four webhooks — two for Vapi (in-call voice booking) and two for the website's inline calendar popup.
- **Endpoints**:
  - `POST /webhook/broadhead-vapi-check-availability` — Vapi: returns up to 5 open 30-min slots, Vapi-shaped string
  - `POST /webhook/broadhead-vapi-book-consultation` — Vapi: creates Calendar event, Vapi-shaped confirmation
  - `POST /webhook/broadhead-web-availability` — Web: returns structured JSON of open slots grouped by day (14-day lookahead)
  - `POST /webhook/broadhead-web-book` — Web: creates Calendar event, returns plain JSON `{ok, slot_iso, calendar_event_id, when_display, email}` and Telegram-pings Sean
- **Node graph** (4 parallel chains):
  ```
  Webhook: Check Availability (Vapi) → Get Calendar Events → Filter to Broadhead Windows → Respond: Slots
  Webhook: Book Consultation (Vapi) → Extract Booking Args → Create Calendar Event → Build Confirmation → Respond: Confirmation
  Webhook: Web Availability → Get Calendar Events Web → Format Web Slots → Respond: Web Slots
  Webhook: Web Book → Extract Web Args → Create Calendar Event Web → Build Web Confirmation → Notify Sean Web (Telegram) → Respond: Web Booking
  ```
- **Vapi response shape**: `{results: [{toolCallId, result: "<spoken-aloud string>"}]}` (Goody's pattern — Vapi's LLM speaks `result` back to caller).
- **Web response shapes**:
  - Availability: `{timezone: "America/Los_Angeles", days: [{date: "2026-04-15", label: "Wed, Apr 15", slots: [{iso, display}]}]}`
  - Booking: `{ok: true, slot_iso, calendar_event_id, when_display, email}`
- **Web CORS**: Site client sends `Content-Type: text/plain` (JSON body as string) to avoid OPTIONS preflight. Extract Web Args parses with `JSON.parse(wh.body)`. Both web Respond nodes include `Access-Control-Allow-Origin: *` header. `broadheadautomations.com` + `localhost:3000` both work.
- **Email handling**:
  - Vapi `book_consultation` does NOT require email (audio too error-prone). `attendeesArr = email ? [email] : []`.
  - Web `/broadhead-web-book` REQUIRES a valid email — that's the only contact channel we collect on the website, and `sendUpdates: "all"` depends on it to fire the calendar invite.
- **Telegram**: WF4's Vapi branches have NO Telegram node — those pings come from WF3 at end-of-call. WF4's Web branch fires its own Telegram ping (via Notify Sean Web) at booking time, since web bookings don't trigger WF3.

---

## Confirmations (shared sub-flow used by WF1 and WF2)

Fire only **after** `Book Consultation` has returned an `eventId`. Both branches run in parallel; merge downstream via "Merge — Append". **No "PT" / "Pacific" anywhere in the copy** — just the day and time.

```
IF email present → Gmail Send
  to: {lead.email}
  subject: Your Broadhead Automations discovery call — {dayShort} at {timeClock}
  body:   greeting, confirmed slot (e.g. "Wednesday at 10am"), 1-hour duration,
          Meet/phone link from the calendar event, "reply to this email if anything
          changes", signed Sean.
  (The Google Calendar invite is sent separately by Google — this email is a
   warmer human-tone follow-up, not a replacement.)

IF phone present AND channel != "sms"  → Twilio Send SMS
  from: BROADHEAD_TWILIO_PHONE_NUMBER
  body: "Hey {firstName}, Sean here — you're booked for {dayShort} at {timeClock}
         for a 1-hour Broadhead Automations discovery call. Reply here if anything
         changes."
  (Skip when channel=sms: the booking confirmation already went out on the same
   thread in the AI Agent's reply.)
```

---

## AI Agent — system prompt outline (identical across WF1 & WF2)

**Design principle: simplicity scales, complexity fails.** 5 bot turns, 5 visitor turns, no quiz. Qualification happens on the call with Sean.

- Identity: **"Fletcher, Sean's AI assistant at Broadhead."**
- **Opener** (first assistant turn, identical for chat + voice modulo the verb):
  - Chat: *"Hey, this is Fletcher, Sean's AI assistant at Broadhead. Would you like to schedule a discovery call with Sean?"*
  - Voice: *"Thanks for calling Broadhead — this is Fletcher, Sean's AI assistant. Would you like to schedule a discovery call with Sean?"*
  - If the visitor has a question first, answer briefly then re-offer once. Never re-pitch on every turn.
- **5-turn flow** (in order, no branching mid-flow except the off-window escape hatch):
  1. **Opener** → yes/no to schedule a discovery call.
  2. **Contact**: *"Great. What's your name, phone number, and email?"* — collect all three in one turn. If they volunteer only two, ask once for the missing one; if they decline, book with what you have (require at least email for web path, at least phone for voice path).
  3. **Day**: *"Is Wednesday or Friday better for you?"* — call `Check Availability` after they pick a day.
  4. **Time**: *"Can you do Wednesday the 22nd at 10am, 11am, 1pm, or 2pm?"* — always include the calendar date (not just the weekday — today may also be a Wed or Fri). Default to the next upcoming Wed/Fri matching their pick; if the visitor asks about a specific date, name dates explicitly. List only the open times returned by `Check Availability`. After they pick, call `Validate Slot` then `Book Consultation`.
  5. **Referral**: *"And how did you hear about Broadhead?"* — ask once, capture verbatim into `referral_raw`. No follow-up, no normalization, no skip-on-name logic. Sean reviews raw.
  6. **Confirm**: *"Got it. Sean will speak with you on Wednesday the 22nd at 10am."* — always include the calendar date, not just the weekday. No "Pacific", no "PT".
- **Booking window — two tracks:**
  - **Default offer:** Wed / Fri, 10:00–12:00 and 13:00–15:00 America/Los_Angeles, **60-min slots at the top of the hour** (10am, 11am, 1pm, 2pm). No Thursday.
  - **Off-window pending path:** if the visitor specifically asks for Mon/Tue/Thu/Sat/Sun or evenings, do NOT call `Book Consultation`. Reply: *"Let me check with Sean about [day/time] and have him confirm directly — he can usually make it work with a little heads-up. In the meantime, let me grab a few details so he can reach out."* Capture the request verbatim into `pending_slot_request` and set `booking_status="pending"`. Collect name/phone/email + referral, then end. Sean follows up manually via the Telegram ping.
- **Tool-use order** (default path only): `Check Availability` → offer slots → `Validate Slot` → `Book Consultation`. Off-window asks bypass all three tools.
- **TZ language**: never say "Pacific", "Pacific Time", or "PT". Just "Wednesday at 10am".
- **End-of-conversation marker** (last turn only): `<<<CAPTURE>>>{"name","email","phone","booking_id","slot_iso","booking_status","pending_slot_request","referral_raw","source":"chat|sms|voice"}<<<END>>>`
  - `booking_status` values: `confirmed` (Book Consultation succeeded — `booking_id` + `slot_iso` populated) | `pending` (off-window ask — `pending_slot_request` populated, Sean confirms manually) | `declined` (visitor opted out).
  - Dropped fields (2026-04-15 late): `business_type`, `pain_point`, `hours_per_week`, `team_size`, `referral_source`, `referrer_name`. Qualification moved to the live call; referral is raw-only for Sean's audit.

### Prepare Context (Set node, both WF1 & WF2)

Inject as system-level context before the AI Agent runs:

```json
{
  "today":   "{{ $now.setZone('America/Los_Angeles').toISODate() }}",
  "now_pt":  "{{ $now.setZone('America/Los_Angeles').toISO() }}",
  "booking_window": {
    "days": ["Wednesday", "Friday"],
    "windows_pt": [["10:00","12:00"], ["13:00","15:00"]],
    "slot_times_pt": ["10:00", "11:00", "13:00", "14:00"],
    "timezone": "America/Los_Angeles",
    "duration_minutes": 60
  }
}
```

### Code tool — `Validate Slot`

Exposed to the AI Agent as a tool (AI-connected Code node). Returns `{valid, reason, nearest_valid}`.

```js
// Input: { slot_iso: "2026-04-15T11:00:00-07:00" }
// NOTE: n8n Cloud sandbox disallows require('luxon') — use Date + Intl.DateTimeFormat.
// See the deployed version in WF1 (hEsEEtfYEldhP8Eb) for the full Intl-based implementation.
const W = {
  days: [3, 5],                                       // Wed, Fri (no Thursday)
  windows: [['10:00','12:00'], ['13:00','15:00']],
  allowedStarts: ['10:00', '11:00', '13:00', '14:00'], // 60-min slots, top of hour
  tz: 'America/Los_Angeles',
  duration: 60,
};

function inWindow(d) {
  const t = d.toFormat('HH:mm');
  return W.allowedStarts.includes(t);
}

function nextValid(from, n = 2) {
  const out = [];
  let c = from.set({ minute: 0, second: 0, millisecond: 0 }).plus({ hours: 1 });
  for (let i = 0; i < 14 * 24 && out.length < n; i++) {
    if ([3,5].includes(c.weekday) && inWindow(c) && c > DateTime.now().setZone(W.tz))
      out.push(c.toISO());
    c = c.plus({ hours: 1 });
  }
  return out;
}

// (full Intl-based validator body lives in the deployed WF1 Validate Slot tool node)
```

> Ship it this way: `const result = {...}; return [{ json: result }];`. Consecutive `}}` inside a Code node string trip `validate_workflow` as false-positive "Unmatched expression brackets" (Goody's lesson).

### Google Calendar tools

Both are AI-tool-connected Google Calendar nodes using Sean's OAuth2 credential.

| Tool name (as seen by AI) | Operation | Key params |
|---|---|---|
| `Check Availability` | `getAll` | `calendar=BROADHEAD_CONSULT_CALENDAR_ID`, `timeMin={{ $now.toISO() }}`, `timeMax={{ $now.plus({ days: 14 }).toISO() }}`, `singleEvents=true` |
| `Book Consultation` | `create` | `calendar=BROADHEAD_CONSULT_CALENDAR_ID`, `summary=Broadhead Discovery Call — {{name}}`, `description=Booked via Fletcher ({{channel}}) — {{phone}} / {{email}}`, `attendees=[{{email}}]`, `start={{slot_iso}}`, `duration=60`, `timezone=America/Los_Angeles`, `sendUpdates=all` |

---

## Vapi assistant (dashboard config, not n8n)

**Shipped** 2026-04-13.
- **Assistant ID**: `30843d88-531d-4f6f-a086-dda77d7cc205` (saved to `.env` as `BROADHEAD_VAPI_ASSISTANT_ID`)
- **Phone number**: `+12087389168` (Vapi-provisioned, ID `dc1e01e3-5596-47ee-9ad7-0584855128d5`, saved to `.env` as `BROADHEAD_VAPI_INBOUND_NUMBER`)
- **Name**: "Broadhead — Fletcher"
- **Model**: gpt-4o (OpenAI)
- **Voice**: Sean's cloned ElevenLabs voice (`lrw4QA6yLWwXQobivuRe`, professional clone in Sean's 11labs account), model `eleven_turbo_v2_5`, stability **0.45** (was 0.75 — lowered 2026-04-14 so prosody follows `<break>` tags), similarityBoost 0.85, style 0.2, speakerBoost on. **`enableSsmlParsing: true`** (CRITICAL — defaults to false on Vapi, which makes ElevenLabs read `<break time="0.4s" />` literally instead of pausing). Requires a Vapi credential registered for provider `11labs` using a full-scope key (`user_read` + `text_to_speech` + `voices_read`) — the restricted `ELEVENLABS_API_KEY` used by social-media-team lacks `user_read` and fails Vapi's credential validator. Full-scope key lives in `.env` as `ELEVENLABS_API_KEY_VAPI`.
- **Transcriber**: Deepgram flux-general-en
- **backgroundSound**: `"off"` (explicit, else default "office" ambience plays)
- **backgroundDenoisingEnabled**: true
- **serverMessages**: `["end-of-call-report"]` — MUST be set explicitly or WF3 gets flooded with every transcript/speech/status event
- **firstMessage** (updated 2026-04-15 late): *"Thanks for calling Broadhead — this is Fletcher, Sean's AI assistant. Would you like to schedule a discovery call with Sean?"* Simple yes/no opener; on a live call the caller already chose to engage, so we don't re-sell them.
- **Custom function tools** (v2 — in-call booking, not just intent capture):
  - `check_availability` → `POST /webhook/broadhead-vapi-check-availability` (no args; returns open 1-hour slots: 10am / 11am / 1pm / 2pm on Wed + Fri)
  - `book_consultation` → `POST /webhook/broadhead-vapi-book-consultation` (required: `name`, `phone`, `slot_iso`; optional: `notes`, `referral_raw`; **no email required** — audio too noisy. `business_type`, `pain_point`, `hours_per_week`, `team_size` all deprecated 2026-04-15 late — qualification moved to the live call.)
- **Server URL** (for end-of-call report): `https://broadheadautomations.app.n8n.cloud/webhook/broadhead-vapi-callend`
- **System prompt shape** (updated 2026-04-15 late): 5 turns, no quiz.
  1. Greeting → would you like to book a discovery call?
  2. Name + callback number (phone only on voice; email too noisy) → silent capture, short "got it".
  3. Wednesday or Friday? → call `check_availability` after they pick.
  4. Time? (offer only returned slots from: 10am / 11am / 1pm / 2pm) → call `book_consultation`.
  5. "How did you hear about Broadhead?" → capture verbatim into `referral_raw`, no follow-up.
  6. Date/time readback + close: *"Booked you for Wednesday `<break time="0.3s" />` at ten AM — talk soon!"* (no "Pacific" anywhere).
  **Off-window escape hatch** (Mon/Tue/Thu/Sat/Sun/evenings): bypass tools. *"Let me check with Sean about [day/time] and have him confirm directly — he can usually make it work with a little heads-up."* Capture `pending_slot_request` + `booking_status="pending"`. Sean confirms manually via the Telegram ping.
- **Structured data schema** (updated 2026-04-15 late): `{name, email, phone, booked, booking_status, pending_slot_request, booked_slot_iso, notes, referral_raw}`
  - `booking_status`: `confirmed | pending | declined | none`
  - `pending_slot_request` = caller's verbatim requested day/time when off-window (e.g. "Tuesday at 2pm"); empty otherwise
  - `booked` is true only when `booking_status="confirmed"`
  - `referral_raw` = caller's verbatim words; Sean reviews raw (no normalization, no `referrer_name`)

### Tested end-to-end 2026-04-13
Sean called `+12087389168` from his cell → Fletcher booked a real 30-min slot on Sean's calendar → Telegram ping landed via `@BroadheadAutomationsBot` at end-of-call. Only the timezone display issue remains (Google Calendar UI showing ET instead of PT — see Edge Cases).

---

## Twilio setup

- **Phone number**: `+12086239442` (already in `BROADHEAD_TWILIO_PHONE_NUMBER`)
- **Messaging → A message comes in**: `POST https://broadheadautomations.app.n8n.cloud/webhook/broadhead-sms-in`
- **Voice → A call comes in**: route directly to the Vapi inbound number (no ring-Sean-first pattern — the whole point is AI-qualifies-first). If Sean later wants missed-call-to-SMS, add a TwiML Bin mirroring Goody's WF2.
- **A2P 10DLC**: register the brand + campaign before launch (1–2 day delay); Twilio will block SMS to US numbers without it.
- Set `BROADHEAD_OWNER_PHONE` to Sean's cell so WF2's loop-prevention IF can match it.

---

## Tech Stack

| Layer | Tool |
|---|---|
| Automation | n8n Cloud (`broadheadautomations.app.n8n.cloud`) |
| AI routing | OpenRouter → Gemini 2.5 Flash (chat + SMS), gpt-4o (Vapi voice) |
| Voice | Vapi.ai + ElevenLabs (Sean's cloned voice) |
| SMS / telephony | Twilio (208 area code, `+12086239442`) |
| Scheduling | Google Calendar (Sean's primary) |
| Confirmation email | Gmail node (Sean's Google OAuth, same creds as Calendar) |
| Lead CRM | Notion (existing `NOTION_DATABASE_ID`) |
| Ops alerts | Telegram (existing `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`) |
| Conversation state | n8n Data Table (`broadhead_conversations`) |

---

## n8n Credentials

| # | Credential | Notes |
|---|---|---|
| 1 | OpenRouter API | Can reuse Goody's credential `a8xhL4SSkNK0ka5y` if shared; otherwise create new from `OPENROUTER_API_KEY` |
| 2 | Twilio API (Broadhead main) | From `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN`; set default from-number to `+12086239442` |
| 3 | **Google OAuth2 (Sean)** | **Blocker — must log into n8n UI to authorize**. Same credential backs both Google Calendar AND Gmail nodes |
| 4 | Notion API | From `NOTION_API_KEY` |
| 5 | Telegram Bot | From `TELEGRAM_BOT_TOKEN` |

---

## Data Table — `broadhead_conversations`

**n8n ID**: `ExmaC6ZorwN97NCa` (Personal project `gOgNbL5uhgtCBJsm`)

### Schema

| Column | Type | Purpose |
|---|---|---|
| key | string | `sessionId` for chat, `phone_number` for SMS |
| channel | string | `chat` / `sms` / `voice` |
| conversation_history | string | JSON array of `{role, content, ts}` |
| state | string | `qualifying` / `negotiating` / `booked` / `stale` |
| lead_name | string | Captured name |
| lead_email | string | Captured email |
| lead_phone | string | Captured phone (always populated for SMS from Twilio `From`) |
| business_type | string | From qualification |
| pain_point | string | From qualification |
| hours_per_week | string | From qualification |
| team_size | string | From qualification |
| calendar_event_id | string | For rescheduling |
| slot_iso | string | Confirmed booking time (ISO) |
| updated_at | string | Stale-detection timestamp |

### Referral fields (currently stored inside `conversation_history` JSON)

`referral_source`, `referrer_name`, and `referral_raw` (added 2026-04-13 for referral bonus attribution) are **not** dedicated columns because n8n's public Data Table API rejects schema edits after creation (`schema is immutable after creation via public API`). They ride along inside the `conversation_history` column for WF1 — the Log Lead node stringifies the full `lead` object, which now includes the three referral keys, so data is preserved.

For voice (WF3), referral fields live only in the Telegram ping + Vapi's end-of-call `analysis.structuredData` (queryable via Vapi API). WF3 does not currently write to the Data Table.

**If Sean wants first-class queryable columns**: add `referral_source` and `referrer_name` columns manually via the n8n UI (`Data Tables → broadhead_conversations → + Add column`), then update the WF1 Log Lead mapping to populate them directly. UI-side schema edits ARE allowed; only the API blocks them.

---

## Setup Checklist

- [x] `.env` — Broadhead block added (`BROADHEAD_TWILIO_PHONE_NUMBER=+12086239442`)
- [x] Site — Fletcher name live, chat endpoint pointed at `/webhook/broadhead-chat/chat`
- [x] Site — signal-routing network visual replaces the wireframe SVG
- [x] Site — Twilio number visible on the Contact section
- [ ] n8n credential: OpenRouter (reuse `a8xhL4SSkNK0ka5y` or create new)
- [ ] n8n credential: Twilio (Broadhead main)
- [ ] n8n credential: Google OAuth2 (Sean) — **blocker — log into n8n UI**
- [ ] n8n credential: Notion
- [ ] n8n credential: Telegram
- [ ] n8n Data Table `broadhead_conversations` created
- [x] Vapi assistant `30843d88-531d-4f6f-a086-dda77d7cc205` configured (gpt-4o + Sean's cloned ElevenLabs voice, `backgroundSound:"off"`, `serverMessages:["end-of-call-report"]`), assistant ID in `.env`
- [x] Vapi inbound phone number provisioned: `+12087389168`, saved to `.env` as `BROADHEAD_VAPI_INBOUND_NUMBER`
- [ ] Twilio A2P 10DLC registration submitted
- [ ] Twilio messaging webhook pointed at `/webhook/broadhead-sms-in`
- [ ] Twilio voice webhook (`+12086239442`) pointed at Vapi number `+12087389168` — **pending; Sean doesn't want ring-cell-first behavior, direct-to-Vapi is fine**
- [x] WF1 built + activated (Chat Booking Agent, `hEsEEtfYEldhP8Eb`) — tested 2026-04-13
- [ ] WF2 built + activated (SMS Booking Agent) — blocked on A2P
- [x] WF3 built + activated (Vapi Call Ended, `3WnYo3El2EYQ6zr8`) — tested 2026-04-13
- [x] WF4 built + activated (Vapi Booking Backend, `saHWTOp2soVZu6lT`) — tested 2026-04-13
- [ ] End-to-end test: chat booking → calendar event + confirmation email + confirmation SMS + Telegram ping
- [ ] End-to-end test: SMS booking → same outputs (SMS confirmation suppressed on sms channel)
- [ ] End-to-end test: voice call that doesn't finish booking → follow-up SMS lands, caller's reply re-enters WF2
- [ ] Decommission AWS Lambda chat endpoint (after 2 weeks of clean n8n operation)

---

## Testing Checklist

- [ ] Chat: visit site, complete 5 Q's, accept a valid slot → calendar event + email + SMS + Notion + Telegram
- [ ] Chat: ask for a Tuesday 3pm slot → agent refuses and offers the 2 nearest valid slots
- [ ] Chat: provide only an email → agent asks once for phone; if declined, books anyway
- [ ] SMS: text the number from a non-owner phone → full flow, confirmation email lands (SMS confirmation suppressed)
- [ ] SMS: text from `BROADHEAD_OWNER_PHONE` → no reply (loop prevention)
- [ ] SMS: carrier-replied STOP → workflow should not continue the conversation (Twilio handles opt-out)
- [ ] Voice: call, hang up mid-book → WF3 sends follow-up SMS; reply re-enters WF2 and books
- [ ] Double-book: two testers target the same slot → second gets `nearest_valid` alternatives
- [ ] Reduced motion: OS toggle → hero network freezes to one frame

---

## Edge Cases & Lessons Learned

- **Vapi `serverMessages` defaults to a firehose** — unset, Vapi POSTs the server URL for every transcript, speech-update, status-update, tool-calls, and end-of-call-report. One real test call produced ~60 POSTs to WF3 before Sean's phone stopped buzzing. ALWAYS PATCH `serverMessages: ["end-of-call-report"]` on the assistant. (Goody's happens to only SMS Nick on `structuredData` presence, which masks the same flood — we just happen to fire Telegram on every hit.)
- **n8n Google Calendar `getAll` emits empty array when no events exist** — downstream nodes in WF4 never fired on a clean calendar until we set `alwaysOutputData: true` on the Get Calendar Events node. Without it, an empty calendar breaks availability lookup for Vapi with no error (just empty 200 response, content-length 0).
- **Respond: Confirmation in WF4 must reference Build Confirmation explicitly** — when a notification node (Telegram/Twilio) sits between the Code node and the Respond node, the Respond node's `$json` resolves to the notification's API response, not the Vapi-shaped payload. Fix: `responseBody: "={{ { results: $('Build Confirmation').first().json.results } }}"`. (We also just removed the intermediate Telegram from WF4 entirely to consolidate pings in WF3.)
- **n8n API `PUT /workflows/{id}` rejects extra settings keys** — WF1's settings had `callerPolicy`, `availableInMCP`, `binaryMode` (all valid in the UI) but the PUT endpoint returns 400 `"settings must NOT have additional properties"`. Strip to the API-allowed subset (`executionOrder`, `saveDataErrorExecution`, `saveDataSuccessExecution`, `saveManualExecutions`, `saveExecutionProgress`, `timezone`, `executionTimeout`, `errorWorkflow`, `callerPolicy`) before PUT.
- **Google Calendar display timezone reverts** — Sean's Google Calendar kept reverting to Eastern Time display even after we fixed it last session. Events are stored correctly with `"timeZone": "America/Los_Angeles"`, but the UI renders them offset by +3h. Fix (display-only): calendar.google.com → ⚙️ Settings → General → Time zone → Pacific. Re-check after any Google Account setting change.
- **Voice agent — phone only, no email** — email addresses are too error-prone over the phone. `book_consultation` does NOT require `email`; Fletcher is prompted to collect only the callback number and silently read it back after the caller answers (no "I'll repeat that back" preamble). Chat agent still accepts phone OR email (either works; no both-required pressure).
- **Phone-number readback dropped entirely; date/time readback uses `<break>` SSML** — three live-call iterations on 2026-04-13/14:
  1. First call: Fletcher chunked the number ("two-oh-eight, five-fifty-five") — caller couldn't verify
  2. Patched to `2... 0... 8...` ellipsis pauses → second call still ran digits together (`eleven_turbo_v2_5` at stability 0.75 ignores ellipses)
  3. Patched to `<break time="0.4s" />` SSML → third call read the tags out loud literally ("less than break time…") because `voice.enableSsmlParsing` defaults to `false`. PATCHed to `true` → fourth call still mangled the digits
  4. Sean called it: drop the readback. Phones are too lossy over voice — capture-and-trust beats capture-and-confirm. Structured-data extraction handles correctness; if the number is wrong, the SMS confirmation bounces and we follow up
  - Final state (2026-04-14 evening, deployed via `tools/vapi-fletcher-update.py`):
    - `voice.stability: 0.45` (was 0.75)
    - `voice.enableSsmlParsing: true` (Vapi default is false — without this, any SSML in messages is read literally)
    - SystemMessage instructs Fletcher to **acknowledge the phone with a short "got it" and move on — no readback, no digit-by-digit confirmation**
    - Date/time readback DOES use `<break time="0.3s" />` between units: `Booked you for Wednesday <break time="0.3s" /> April fifteenth <break time="0.3s" /> at one PM Pacific — correct?` (date readback works fine since it's only ~3 units, not 10 digits)
  - Pre-edit snapshots of the assistant config live in `context/fletcher-assistant-{ts}.json` for rollback / drift audits
- **Chat opener reverted to a soft booking CTA** (2026-04-15 late) — earlier (2026-04-13) we stripped the yes/no booking gate on chat and dove straight into qualification Q1 to cut one bubble before capture. Downside: warm visitors who arrived ready to book had to navigate a quiz first. Reverted to a value-first CTA that names the consult cadence (Wed–Fri, 30 min) and offers an opt-out ("…or is there something you'd rather ask first?"). Leads with value, respects Type-5 hesitation, matches voice opener intent. Chat opener must lead with the consult offer — a value-first greeting captures ready-to-book visitors without pushing hesitant ones. The Q1 qualification wording is unchanged; it now fires on turn two when the visitor says yes.
- **Wed–Fri framing pulled out of openers; off-window asks routed through a pending path** (2026-04-15 evening) — earlier same-day note said "both openers name the 30-minute Wed–Fri cadence" to prime calendar thinking. In live use that primed visitors that other days were OFF-limits and made the screenshot conversation feel rigid. Sean's real constraint: Mon/Tue/Thu he's at his other Loan Officer role at a bank, but he can step out for a coordinated call with heads-up. Also, Fletcher previously volunteered the cadence in turn 1 — Type-5 trust-sales lens is "lead with the hook, not the constraint."
  - **Chat opener** (WF1 + index.html fallback) now leads with the visitor's blind spot: *"Most owners are buried in repetitive tasks they don't even notice anymore — until someone points them out. Open to a free 30-minute consult with Sean to find yours?"*
  - **Vapi firstMessage** drops the cadence entirely: *"Want me to get you booked in with Sean, or is there something else first?"* — caller already chose to engage, no need to re-sell.
  - **Off-window asks** (Mon/Tue/Thu/Sat/Sun/evenings) bypass `Book Consultation` / `book_consultation`. Fletcher says: *"Let me check with Sean about [day/time] and have him confirm directly — he can usually make it work with a little heads-up. In the meantime, let me grab a few details so he can reach out."* Captures the request as `pending_slot_request`, sets `booking_status="pending"`. Sean confirms manually via the Telegram ping (WF1 Notify Sean + WF3 Parse Vapi Data both render a `[PENDING off-window request]` message with the requested day/time). Never mention the bank/LO role or "calendar isn't current" — keep it clean and in control.
  - **Why this won't drift back:** the previous openers cited "anchors on cadence so the slot offer lands naturally" as justification. That logic still holds for *flexible* visitors — but anchoring on the constraint costs us the rigid-day visitors who would have been a yes if Fletcher hadn't framed Wed/Fri as a wall. The pending path resolves the tradeoff: Wed/Fri remain the default Fletcher offers; off-window stays bookable, just async.
- **Referral follow-up gates on missing-name, not on referral-flavor** (2026-04-15 evening) — original logic asked "who should I thank?" any time the answer mentioned a person, friend, or referral, even when the answer already gave the name. In Sean's screenshot, visitor said "Nick Goodsen" — Fletcher still asked. Updated logic in both WF1 systemMessage and Vapi systemMessage: if the answer **contains a person's name** (any tokens that look like a name — single first name, full name, "buddy John"), capture as `referrer_name`, set `referral_source="referral"`, and skip the follow-up. Only ask the follow-up when the answer is vague ("a friend", "someone I know", "word of mouth") with no name attached. Channel answers (Google, social, podcast, event) skip the follow-up as before. Captured in both `referrer_name` (the name) and `referral_raw` (verbatim words) for Sean's audit.
- **Validate Slot toolCode description must ask for a bare string, not a JSON object** (2026-04-15) — `@n8n/n8n-nodes-langchain.toolCode` with no explicit input schema defaults to a single-string input. If the description says *"Input: { slot_iso: '...' }"*, Gemini 2.5 Flash dutifully calls the tool with `{slot_iso: "..."}` and LangChain rejects it with *"Expected string, received object → at input"* before the jsCode runs. The execution errors silently, the Chat Trigger emits no output, and the HTML widget falls back to *"I'm back — can you say that again?"* — which looks like a response glitch, not a tool-schema bug. Fix: description must explicitly request a bare ISO string. The jsCode was already defensive for both shapes (`typeof query === 'string' ? query : query.slot_iso`) — only the description was lying to the LLM.
- **Small-biz-first qualification rewrite** (2026-04-15) — the original five questions ("type of business", "time-consuming task your team does", "hours/week", "team size", contact) were mid-market framing: "team" presumed structure, "hours/week × wage" presumed payroll-cost ROI math. Sean's actual ICP is solos + micro (1–5 people) where the owner *is* the team. Rewrote to 3 questions that map to the three pains Sean actually sells against (missed follow-up, growth ceiling, personal bandwidth):
  1. *"What do you do, and how are customers finding you today?"* — double-duty: business type + acquisition channel in one turn.
  2. *"Where are you stuck right now — leads slipping through, no time to keep up, or hitting a ceiling?"* — pick-one frame so small operators self-diagnose instead of inventing an answer.
  3. *"Best name, email, and number to get you booked with Sean?"*
  Deprecated `hours_per_week` and `team_size` fields across the CAPTURE marker, WF1 Book Consultation description, Vapi `book_consultation` tool schema, and WF4 Extract/Create/Confirm nodes. Q1's richer answer now lives entirely in `business_type`. Old 5-question list preserved in the Archived Variants section below for rollback.

### Archived Variants

**2026-04-15 (morning) small-biz-first 3-question qualification (deprecated late same day — simplicity rewrite):**
1. What do you do, and how are customers finding you today?
2. Where are you stuck right now — leads slipping through, no time to keep up, or hitting a ceiling?
3. What's the best name, email, and number to get you booked with Sean?

Plus a referral follow-up with skip-on-name logic ("who should I thank?" only when the answer was vague) and a "blind spot" chat opener: *"Most owners are buried in repetitive tasks they don't even notice anymore — until someone points them out. Open to a free 30-minute consult with Sean to find yours?"*

**Pre-2026-04-15 5-question qualification (mid-market framing, deprecated):**
1. What type of business do you run?
2. What's the most time-consuming task your team handles manually right now?
3. How many hours a week does that eat?
4. How big is your team?
5. What's the best name, email, and phone to reach you at?

Roll back only if the current 5-turn script measurably underperforms on booking rate AND Sean's ICP shifts toward needing pre-call qualification.
- **Google Calendar node `calendar` field** — use `{"__rl": true, "value": "sean@broadheadautomations.com", "mode": "list", "cachedResultName": "sean@broadheadautomations.com"}`. The `"primary"` string with `mode: "id"` is rejected by the UI validator with "Not a valid google calendar id". Deploy with the actual email.
- **n8n API activation is blocked on `googleCalendarTool` nodes that use `$fromAI` in their required dateTime fields** (`timeMin`/`timeMax` for availability, `start`/`end` for create). The activation endpoint returns `"Missing or invalid required parameters"` even though the node config is structurally valid. Goody's `AMMOTrhbDAAi77Xh` hits the same error (identical node pattern). Workaround: **activate via the n8n UI toggle**, which appears to use a looser validator. If UI activation also fails, options are (a) wrap the Calendar calls in a sub-workflow that the AI Agent invokes via `Call n8n Workflow Tool`, or (b) skip the tool variant and make the AI Agent emit structured JSON that a downstream Google Calendar node consumes with static expressions.


- **n8n Cloud blocks `$env.*`** — hardcode the booking window and `BROADHEAD_OWNER_PHONE` / `BROADHEAD_CONSULT_CALENDAR_ID` directly in the relevant nodes. Same plan lift as Goody's.
- **Chat Trigger needs a Memory sub-node on the trigger itself** when `loadPreviousSession: "memory"`. Without it the webhook returns 500. For Fletcher we use `loadPreviousSession: "notSupported"` and accept that a tab-reload starts a fresh conversation — good enough for MVP; SMS handoff is the durable thread anyway.
- **Chat Trigger webhook path ends in `/chat`** — full URL is `/webhook/broadhead-chat/chat`, not `/webhook/broadhead-chat`. The 404 if you miss it is silent from the browser's perspective.
- **`validate_workflow` false-positives on `}}`** inside Code node `jsCode` strings. Write `const result = {...}; return [{ json: result }];` — never let two `}` characters touch.
- **Notion env var mismatch** — the old `chat-server.js` uses `NOTION_LEADS_DB_ID`; `.env` stores `NOTION_DATABASE_ID`. They are the same database; pick one name going forward (`NOTION_DATABASE_ID` is canonical) and drop the alias once the Lambda flow is decommissioned.
- **Gmail + Calendar share one OAuth credential** on Sean's account — one authorization step unlocks both.
- **Twilio `onReceived` response mode** is mandatory for the SMS webhook. Twilio times out fast; respond `<Response/>` immediately and send the reply asynchronously via the Twilio node downstream.
- **Vapi `backgroundSound` defaults to "office" ambience** and the field doesn't show up in GET responses when unset. Explicitly PATCH `{"backgroundSound":"off"}` or the call sounds like a call center. (Goody's lesson, carried over verbatim.)
- **`sendUpdates: "all"`** on the Book Consultation node — without it, Google does NOT email the attendee the calendar invite. This is separate from Fletcher's confirmation email (we want both).
- **Confirmation SMS suppressed on SMS channel** — the agent's booking-confirmation reply already went out on the same thread; a second SMS is noise.
- **Stateless SMS** — conversation state lives only in `broadhead_conversations`. If the row is deleted or the key changes, the next message starts fresh. Keep an eye on phone-number format normalization (always store E.164, never the raw `From`).
- **n8n Data Table schema is immutable via public API** — after a table is created, `POST/PATCH /data-tables/{id}/columns` returns 404 at every URL variant (project-scoped and non-project-scoped). You CAN add columns through the n8n UI; only the API blocks it. For referral fields we ride inside the existing `conversation_history` JSON blob (WF1 stringifies the whole lead object into that column) rather than request Sean add columns just to ship.
- **Referral question must come AFTER booking**, not before or during qualification. Asking up-front adds friction and tanks booking rates. Asking post-booking only captures data from booked leads — which is exactly the set that matters for paying referral bonuses. If `Book Consultation` never fires, Fletcher skips the question.
- **Always name the calendar date, never just the weekday** (2026-04-15 late) — first live test after the simplification: Fletcher offered "Can you do Wednesday at 10am, 11am, 1pm, or 2pm?" when today was also a Wednesday. Visitor came back with "Next Wednesday? The 22nd or today" — Fletcher just repeated the same line instead of disambiguating. Fix: Turn 4 wording (chat + voice) must include the actual date — "Can you do Wednesday the 22nd at 10am…" — and confirm with the date too — "Got it. Sean will speak with you on Wednesday the 22nd at 10am." Default to the next upcoming Wed/Fri with open slots; if the visitor asks about a specific date, name dates explicitly. Rule: when today could also match the weekday, date > weekday. Patched in WF1 systemMessage and Vapi systemPrompt via `tools/vapi-fletcher-simplify.py`.
- **Simplicity scales, complexity fails — drastic script simplification** (2026-04-15 late, supersedes the 2026-04-15 small-biz-first rewrite and the skip-on-name referral logic) — over three days the script grew from 3 turns to 5 qualification questions plus a referral-with-name-detection sub-flow plus a blind-spot soft-CTA opener. Sean's feedback after reviewing a live chat: it feels like a quiz, warm visitors bounce. Rewrote to 5 bot turns total: (1) open with a simple yes/no booking ask, (2) name + phone + email in one turn, (3) day (Wed/Fri), (4) time (10am / 11am / 1pm / 2pm), (5) how-did-you-hear raw capture, (6) confirm. **No qualification questions** — `business_type`, `pain_point`, `hours_per_week`, `team_size` all deprecated. **No referral normalization** — `referral_source` and `referrer_name` deprecated; `referral_raw` is the only surviving field, captured verbatim for Sean's audit. **No "Pacific" / "PT"** in any agent speech or confirmation copy — calendar still stores `America/Los_Angeles` but Fletcher never verbalizes the zone. **Slot duration 30min → 60min**, slot alignment `% 30 === 0` → top-of-hour only (10/11/13/14), afternoon window `14:30` → `15:00` to accommodate the 2pm hour. Off-window pending path retained verbatim (already built, no regression on flexibility). Old 3-question qualification moved to Archived Variants alongside the older 5-question version. **Rule of thumb**: if the flow has more than 5 turns before booking, it's too long — qualification is what the call itself is for.
- **Plain n8n Webhook node has no built-in CORS** (unlike Chat Trigger which exposes `allowedOrigins`). For browser-initiated JSON POSTs, either: (a) handle OPTIONS preflight manually with `multipleMethods: ["POST","OPTIONS"]` + an IF node routing OPTIONS to a Respond Preflight node, or (b) have the client send `Content-Type: text/plain` with a JSON body string — this is a CORS "simple request" so no preflight fires. WF4's web endpoints use (b): client sends `text/plain`, Extract Web Args runs `JSON.parse(wh.body)`, and both Respond nodes set `Access-Control-Allow-Origin: *` via responseHeaders so the browser exposes the response to JS. Added 2026-04-14.
- **Vapi requires a registered 11labs credential to use custom cloned voices** — without one, Vapi uses its own ElevenLabs account and returns `"Couldn't Find 11labs Voice"` for any non-stock voiceId. Register via `POST /credential` with provider `11labs`. The credential key must have `user_read` permission (Vapi's validator hits `/v1/user`); restricted keys scoped only to `voices_read` / `text_to_speech` fail validation with 401 → 400. Once a valid 11labs credential exists on the Vapi account, custom voices work without any `credentialId` field on the assistant — Vapi auto-uses the account credential. Attempting to PATCH `voice.credentialId` returns `"voice.property credentialId should not exist"`.

---

## Open Items

- [ ] Decide email sender: Gmail OAuth on Sean's Google account (recommended, one auth for Calendar + Gmail) vs nodemailer/SMTP (reuses `chat-server.js` creds) vs SendGrid/Resend (branded from `sean@broadheadautomations.com` with DMARC alignment). Default: Gmail OAuth; revisit if deliverability is an issue.
- [ ] Decide calendar ID to use for consultations — Sean's primary vs a dedicated "Broadhead Consults" calendar. A dedicated calendar keeps personal events off `getAll` queries and simplifies future delegation. Populate `BROADHEAD_CONSULT_CALENDAR_ID` once chosen.
- [ ] Decide whether to add Google Calendar **function tools inside Vapi** (v2) so the voice agent can book in-call. Current v1 defers booking to SMS handoff.
- [ ] Decommission `tools/chat-server.js` + AWS Lambda endpoint after two clean weeks of n8n operation. Leave the files in place but stop routing to them.
- [ ] Update `chatbot-lead-capture.md` — mark it as **superseded by `booking-automation.md`** once WF1 is live.
