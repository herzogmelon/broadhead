# Workflow: Website Lead-Capture Chatbot

## Objective
Run Aria — an AI-powered chat widget on the Broadhead Automations website — to qualify visitors and deliver lead summaries to Sean via email. Every visitor who completes the flow is a warm lead with context already captured.

---

## Required Inputs

| Input | Source | Notes |
|-------|--------|-------|
| `ANTHROPIC_API_KEY` | `.env` | Claude haiku-4-5 powers Aria |
| `GMAIL_USER` | `.env` | Gmail address used to send email |
| `GMAIL_APP_PASS` | `.env` | Gmail App Password (not your login password) |
| `LEAD_EMAIL_TO` | `.env` | Where lead notifications are delivered |
| `PORT` | `.env` | Default: 3001 |
| `NOTION_API_KEY` | `.env` | Notion integration token (for CRM) |
| `NOTION_LEADS_DB_ID` | `.env` | Notion database ID for lead storage |

> `NOTION_API_KEY` and `NOTION_LEADS_DB_ID` are optional. If missing, leads are emailed only.

---

## How to Run

### Start the chatbot backend
```bash
cd "My Workflows/Broadhead"
node tools/chat-server.js
```
Server starts on `http://localhost:3001`. Keep this running while the site is live.

### Start the website (local dev)
```bash
node serve.mjs
```
Opens at `http://localhost:3000`. The chat widget appears in the bottom-right corner.

### For production
Deploy `chat-server.js` to a VPS or serverless platform (Railway, Render, Fly.io). Update the `API_BASE` constant in the `index.html` chat widget from `http://localhost:3001` to your live server URL.

---

## Qualification Flow

Aria guides the visitor through 5 questions in order. She does not skip steps.

```
1. "What type of business do you run?"
2. "What's the most time-consuming task your team handles manually right now?"
3. "Roughly how many hours a week does that take?"
4. "How big is your team?"
5. "What's the best name and email to reach you?"
```

Once name + email are collected, Aria closes the conversation and an email is sent to Sean automatically.

---

## Expected Output

### Chat widget behavior
- Floating button (bottom-right, cyan pulse) opens a chat drawer
- Aria greets the visitor immediately on open
- Conversation history persists for the session
- Typing indicator shows while Aria is generating a response

### Lead email (sent to `LEAD_EMAIL_TO`)
```
Subject: New Lead: [Business Type] — [Name]

New lead from Broadhead Automations website

Name:          [name]
Email:         [email]
Business Type: [type]
Pain Point:    [manual task described]
Hours/Week:    [estimate]
Team Size:     [size]

Captured: [timestamp]
```

---

## Edge Cases & Known Behavior

| Situation | Behavior |
|-----------|----------|
| User closes chat mid-flow | Session state is lost on page reload — they start over |
| User provides vague answers | Aria gently re-asks without repeating the same phrasing |
| Email fails to send | Server logs the error; lead info is still logged to console |
| Claude API down | Aria responds with a fallback: "I'm having trouble connecting — try again in a moment." |
| User doesn't provide email | Aria holds at step 5 until a valid-looking email is given |

---

## Updating Aria's Behavior

Aria's personality and question flow are defined in the system prompt inside `tools/chat-server.js` — look for `ARIA_SYSTEM_PROMPT`. Edit that string to:
- Change her tone or name
- Add/remove qualification questions
- Adjust the closing message

After editing, restart the server (`Ctrl+C` then `node tools/chat-server.js`).

---

## CRM Setup (Notion)

Leads are saved to a Notion database automatically when `NOTION_API_KEY` and `NOTION_LEADS_DB_ID` are set. Run this once to create the database:

### Step 1 — Create a Notion integration
1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Click **New integration** → name it "Broadhead CRM"
3. Copy the **Internal Integration Token** → paste into `.env` as `NOTION_API_KEY`

### Step 2 — Create a parent page in Notion
1. In Notion, create a new page (e.g. "Broadhead CRM")
2. Share it with your integration: click **...** → **Connections** → select "Broadhead CRM"
3. Copy the page ID from the URL: `notion.so/Your-Page-{PAGE_ID}`

### Step 3 — Run the setup script
```bash
cd "My Workflows/Broadhead"
node tools/setup-notion-crm.js <PAGE_ID>
```
The script creates the leads database with all fields and prints the database ID.

### Step 4 — Add the database ID to .env
```
NOTION_LEADS_DB_ID=<printed id>
```

### Step 5 — Redeploy (production only)
```bash
bash tools/deploy.sh
```

### What a lead entry looks like in Notion
Each captured lead creates a row with: Name, Email, Phone, Business Type, Pain Point, Hours/Week, Team Size, Status (default: **New**), Captured At, and a Notes field for follow-up.

Change **Status** as you work the lead: New → Contacted → Qualified → Closed / Not a Fit.

---

## Iterating & Improving

After each real conversation, note:
- Where did visitors drop off?
- Did any answers surprise you?
- Did the email arrive with the right info?

Update this workflow with findings. Update `ARIA_SYSTEM_PROMPT` in the tool if the flow needs adjusting.

---

## Self-Improvement Loop

1. Identify drop-off or failure point
2. Edit `ARIA_SYSTEM_PROMPT` in `tools/chat-server.js`
3. Restart server and test locally
4. Verify email arrives with correct lead data
5. Update this workflow with what changed and why
