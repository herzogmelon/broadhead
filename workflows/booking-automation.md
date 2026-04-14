# Broadhead Automations — Booking Automation

## Objective
Convert every inbound contact (website chat, inbound SMS, inbound phone call) into a qualified lead on a 30-minute consultation on Sean's Google Calendar — automatically, in the caller's own language, with confirmation sent by email and SMS.

## Business Context
- **Client / operator**: Sean Belknap (also the service provider)
- **Inbound channels**: website chat widget on broadheadautomations.com, inbound SMS to the Broadhead Twilio number, inbound voice to the Vapi-hosted number
- **Bookable hours**: Wed/Fri, **10:00–12:00 and 13:00–14:30 America/Los_Angeles**, 30-minute slots
- **Assistant name**: Fletcher (the craftsman who builds arrows — pairs with the broadhead brand)

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
- **n8n ID**: `saHWTOp2soVZu6lT` (9 nodes) — deployed and **active** 2026-04-13; tested end-to-end (real calendar events created in PT)
- **Purpose**: two webhooks called by Fletcher during a live voice call so the caller can book before hanging up.
- **Endpoints**:
  - `POST /webhook/broadhead-vapi-check-availability` — returns up to 5 open 30-min slots in Sean's Wed/Fri 10–12 + 1–2:30 PT windows
  - `POST /webhook/broadhead-vapi-book-consultation` — creates the Calendar event, returns Vapi-shaped confirmation
- **Node graph**:
  ```
  Webhook: Check Availability → Get Calendar Events → Filter to Broadhead Windows → Respond: Slots
  Webhook: Book Consultation → Extract Booking Args → Create Calendar Event → Build Confirmation → Respond: Confirmation
  ```
- **All Vapi responses shape**: `{results: [{toolCallId, result: "<spoken-aloud string>"}]}` (Goody's pattern — Vapi's LLM speaks `result` back to caller naturally).
- **Empty email handling**: Vapi is voice-only, so `book_consultation` does NOT require `email`. Extract Booking Args builds `attendeesArr = email ? [email] : []`; Create Calendar Event uses `attendees: "={{ $json.attendeesArr }}"` so no attendee is added when email is missing.
- **No Telegram here** — all notifications consolidated to WF3 at end-of-call to avoid duplicate pings.

---

## Confirmations (shared sub-flow used by WF1 and WF2)

Fire only **after** `Book Consultation` has returned an `eventId`. Both branches run in parallel; merge downstream via "Merge — Append".

```
IF email present → Gmail Send
  to: {lead.email}
  subject: Your Broadhead Automations consultation — {dayShort} at {timePT} PT
  body:   greeting, confirmed slot in PT, 30-min duration, Meet/phone link from the
          calendar event, "reply to this email if anything changes", signed Sean.
  (The Google Calendar invite is sent separately by Google — this email is a
   warmer human-tone follow-up, not a replacement.)

IF phone present AND channel != "sms"  → Twilio Send SMS
  from: BROADHEAD_TWILIO_PHONE_NUMBER
  body: "Hey {firstName}, Sean here — you're booked for {dayShort} at {timePT} PT
         for a 30-min Broadhead Automations consult. Reply here if anything changes."
  (Skip when channel=sms: the booking confirmation already went out on the same
   thread in the AI Agent's reply.)
```

---

## AI Agent — system prompt outline (identical across WF1 & WF2)

- Identity: **"Fletcher, Sean's AI assistant at Broadhead Automations."**
- 5-question qualification (one at a time, in order):
  1. What type of business do you run?
  2. What's the most time-consuming task your team handles manually right now?
  3. How many hours a week does that eat?
  4. How big is your team?
  5. What's the best **name, email, and phone** to reach you at? *(both contacts; hard-require at least one of email/phone before booking, politely ask once for the other)*
- After qualification → pitch a 30-minute consult with Sean.
- Booking window: **Wed / Fri, 10:00–12:00 and 13:00–14:30 America/Los_Angeles, 30-min slots** (no Thursday). Always offer two concrete times.
- Tool-use order: `Check Availability` → offer slots → `Validate Slot` → `Book Consultation`.
- If user asks for a time outside the window → call `Validate Slot`, use its `nearest_valid` list, and offer the two closest valid alternatives.
- **Step 6 (post-booking) — Referral question**: immediately after `Book Consultation` succeeds, Fletcher asks "how did you hear about us?" exactly once. If the answer names a person/friend → ONE follow-up for the referrer's name. Normalize the raw answer into one of: `referral | google | social | podcast | event | other | unknown`. Store caller's verbatim words in `referral_raw`; populate `referrer_name` only when `referral_source=referral`. Never re-ask. If booking did not happen, skip the question and set `referral_source="unknown"`.
- End-of-conversation marker (last turn only): `<<<CAPTURE>>>{"name","email","phone","business_type","pain_point","hours_per_week","team_size","booking_id","slot_iso","referral_source","referrer_name","referral_raw","source":"chat|sms|voice"}<<<END>>>`

### Prepare Context (Set node, both WF1 & WF2)

Inject as system-level context before the AI Agent runs:

```json
{
  "today":   "{{ $now.setZone('America/Los_Angeles').toISODate() }}",
  "now_pt":  "{{ $now.setZone('America/Los_Angeles').toISO() }}",
  "booking_window": {
    "days": ["Wednesday", "Friday"],
    "windows_pt": [["10:00","12:00"], ["13:00","14:30"]],
    "timezone": "America/Los_Angeles",
    "duration_minutes": 30
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
  windows: [['10:00','12:00'], ['13:00','14:30']],
  tz: 'America/Los_Angeles',
  duration: 30,
};

function inWindow(d) {
  const t = d.toFormat('HH:mm');
  return W.windows.some(([s, e]) => t >= s && t < e) && d.minute % 30 === 0;
}

function nextValid(from, n = 2) {
  const out = [];
  let c = from.set({ second: 0, millisecond: 0 });
  c = c.plus({ minutes: (30 - c.minute % 30) % 30 || 30 });
  for (let i = 0; i < 14 * 48 && out.length < n; i++) {
    if ([3,4,5].includes(c.weekday) && inWindow(c) && c > DateTime.now().setZone(W.tz))
      out.push(c.toISO());
    c = c.plus({ minutes: 30 });
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
| `Book Consultation` | `create` | `calendar=BROADHEAD_CONSULT_CALENDAR_ID`, `summary=Broadhead Consult — {{name}}`, `description={{business_type}} \| {{pain_point}} \| {{hours_per_week}} \| team {{team_size}}`, `attendees=[{{email}}]`, `start={{slot_iso}}`, `duration=30`, `timezone=America/Los_Angeles`, `sendUpdates=all` |

---

## Vapi assistant (dashboard config, not n8n)

**Shipped** 2026-04-13.
- **Assistant ID**: `30843d88-531d-4f6f-a086-dda77d7cc205` (saved to `.env` as `BROADHEAD_VAPI_ASSISTANT_ID`)
- **Phone number**: `+12087389168` (Vapi-provisioned, ID `dc1e01e3-5596-47ee-9ad7-0584855128d5`, saved to `.env` as `BROADHEAD_VAPI_INBOUND_NUMBER`)
- **Name**: "Broadhead — Fletcher"
- **Model**: gpt-4o (OpenAI)
- **Voice**: Sean's cloned ElevenLabs voice (`lrw4QA6yLWwXQobivuRe`, professional clone in Sean's 11labs account), model `eleven_turbo_v2_5`, stability 0.75, similarityBoost 0.85, style 0.2, speakerBoost on. Requires a Vapi credential registered for provider `11labs` using a full-scope key (`user_read` + `text_to_speech` + `voices_read`) — the restricted `ELEVENLABS_API_KEY` used by social-media-team lacks `user_read` and fails Vapi's credential validator. Full-scope key lives in `.env` as `ELEVENLABS_API_KEY_VAPI`.
- **Transcriber**: Deepgram flux-general-en
- **backgroundSound**: `"off"` (explicit, else default "office" ambience plays)
- **backgroundDenoisingEnabled**: true
- **serverMessages**: `["end-of-call-report"]` — MUST be set explicitly or WF3 gets flooded with every transcript/speech/status event
- **firstMessage**: *"Hey, thanks for calling Broadhead Automations! I'm Fletcher, Sean's AI assistant. Would you like to schedule a 30-minute consultation with Sean, or is there something else I can help with?"*
- **Custom function tools** (v2 — in-call booking, not just intent capture):
  - `check_availability` → `POST /webhook/broadhead-vapi-check-availability` (no args; returns 5 open slots)
  - `book_consultation` → `POST /webhook/broadhead-vapi-book-consultation` (required: name, phone, business_type, pain_point, slot_iso; optional: hours_per_week, team_size, notes; **no email required** — audio too noisy)
- **Server URL** (for end-of-call report): `https://broadheadautomations.app.n8n.cloud/webhook/broadhead-vapi-callend`
- **System prompt shape**: greeting asks if they want to book → only after yes, qualify (name → business → pain → hours/wk → team size → callback number + silent read-back for confirmation) → offer two concrete slots → book → **post-booking referral question ("how did you hear about us?") with follow-up for referrer's name** → "Talk soon!"
- **Structured data schema**: `{name, email, phone, business_type, pain_point, hours_per_week, team_size, booked, booked_slot_iso, notes, referral_source, referrer_name, referral_raw}`
  - `referral_source` normalized to one of: `referral | google | social | podcast | event | other | unknown`
  - `referrer_name` populated ONLY when `referral_source=referral`
  - `referral_raw` = caller's verbatim words, pre-normalization (for Sean to audit Fletcher's classification)

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
- **Phone-number readback must be digit-by-digit with ellipsis pauses** — first live test (2026-04-13) Fletcher chunked the number ("two-oh-eight, five-fifty-five, twelve thirty-four") and callers couldn't verify. The systemMessage now instructs an explicit format: `"Got it — that's 2... 0... 8... 5... 5... 5... 1... 2... 3... 4, correct?"` — ElevenLabs pauses on the `...` punctuation. Do NOT let the prompt drift back to grouped-digit phrasing.
- **Fletcher opens with a booking offer** — both voice firstMessage and WF1 chat system prompt ask "Would you like to schedule a 30-minute consultation?" before any qualification. Qualification only starts after the visitor/caller says yes.
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
- **Referral question must come AFTER booking**, not before or during qualification. Asking up-front adds friction and tanks booking rates. Asking post-booking only captures data from booked leads — which is exactly the set that matters for paying referral bonuses. If `Book Consultation` never fires, Fletcher skips the question and records `referral_source="unknown"`.
- **Vapi requires a registered 11labs credential to use custom cloned voices** — without one, Vapi uses its own ElevenLabs account and returns `"Couldn't Find 11labs Voice"` for any non-stock voiceId. Register via `POST /credential` with provider `11labs`. The credential key must have `user_read` permission (Vapi's validator hits `/v1/user`); restricted keys scoped only to `voices_read` / `text_to_speech` fail validation with 401 → 400. Once a valid 11labs credential exists on the Vapi account, custom voices work without any `credentialId` field on the assistant — Vapi auto-uses the account credential. Attempting to PATCH `voice.credentialId` returns `"voice.property credentialId should not exist"`.

---

## Open Items

- [ ] Decide email sender: Gmail OAuth on Sean's Google account (recommended, one auth for Calendar + Gmail) vs nodemailer/SMTP (reuses `chat-server.js` creds) vs SendGrid/Resend (branded from `sean@broadheadautomations.com` with DMARC alignment). Default: Gmail OAuth; revisit if deliverability is an issue.
- [ ] Decide calendar ID to use for consultations — Sean's primary vs a dedicated "Broadhead Consults" calendar. A dedicated calendar keeps personal events off `getAll` queries and simplifies future delegation. Populate `BROADHEAD_CONSULT_CALENDAR_ID` once chosen.
- [ ] Decide whether to add Google Calendar **function tools inside Vapi** (v2) so the voice agent can book in-call. Current v1 defers booking to SMS handoff.
- [ ] Decommission `tools/chat-server.js` + AWS Lambda endpoint after two clean weeks of n8n operation. Leave the files in place but stop routing to them.
- [ ] Update `chatbot-lead-capture.md` — mark it as **superseded by `booking-automation.md`** once WF1 is live.
