# Ideas Log

Track ideas we've explored, decisions made, and outcomes. This prevents re-hashing old ground and helps spot patterns in what works.

## Active Ideas

### Friend Call Outreach — Free AI Audits — 2026-03-21
- **Category:** AI business (go-to-market)
- **The idea:** Call friends who own businesses and offer a free AI workflow audit as a case study. Use Nate Herk's consultative/ROI-driven framework blended with Trust Sales. Position honestly — building the business, need real-world case studies. The free audit is both the value-add and the learning opportunity.
- **Why it fits:** Trust Sales at its core — lead with value, no pressure. Type 5 curiosity drives the discovery. Honest positioning ("I'm building this") instead of faking expertise. Friends are warm leads who already trust Sean. The audit itself builds the portfolio and skills simultaneously.
- **Approach:** Nate Herk style — discovery questions to surface pain points, calculate ROI (hours x cost = annual waste), offer free audit, book a 30-min screen share follow-up to present findings.
- **Script:** `prompts/ai-business-call-script.md`
- **Status:** implementing — script created, ready to start making calls
- **Outcome/Learning:** (pending)

## Parked Ideas

### Branch Growth Strategist Role — 2026-03-17 (parked 2026-03-23)
- **Category:** lending / AI business (convergence play)
- **The idea:** Pitch a new position at the branch — a growth/marketing strategist who builds content and strategy systems for all LOs. Keep origination pipeline. Salary + production. Work behind the scenes, remote, own schedule.
- **Why it was parked:** Production numbers need to be strong before this pitch has credibility. Talked to #2 in the office who pushed back — "focus on getting loans." Without results to point to, the role looks like an escape hatch, not a growth engine. Revisit when closing 3+/month consistently and have proof the systems work for own pipeline first.
- **What's still true:** The idea is sound. The bank is growth-minded. The convergence with the AI business is real. Timing is wrong — not the idea.

## Tried & Learned
<!-- Ideas we executed on — what happened, what we learned -->

### CRM for Aria Leads — 2026-04-03
- **Category:** AI business (Broadhead)
- **The idea:** Build a Notion CRM to store and manage leads captured by Aria. Replaces email-only notifications with a searchable database of leads including contact info, business type, pain point, and qualification data.
- **Outcome:** Built. `saveLeadToNotion()` added to both `lambda.js` and `chat-server.js`, called alongside `sendLeadEmail()`. Notion failure is caught and logged — never breaks email delivery. One-time setup script at `tools/setup-notion-crm.js` creates the database with full schema (Name, Email, Phone, Business Type, Pain Point, Hours/Week, Team Size, Status, Captured At, Notes). Requires `NOTION_API_KEY` + `NOTION_LEADS_DB_ID` in `.env`; graceful no-op if missing.
- **Setup:** See CRM Setup section in `workflows/chatbot-lead-capture.md`.

<!-- Template:

### [Idea Title] — [DATE]
- **Category:** (lending / AI business / trading / other)
- **The idea:**
- **Why it fits:** (how does it align with trust sales, Type 5 strengths, etc.)
- **Status:** (exploring / implementing / parked / tried)
- **Outcome/Learning:**

-->
