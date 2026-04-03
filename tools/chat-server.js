import 'dotenv/config';
import express from 'express';
import cors from 'cors';
import Anthropic from '@anthropic-ai/sdk';
import nodemailer from 'nodemailer';

// ── Validate environment ──────────────────────────────────────────────────────
const required = ['ANTHROPIC_API_KEY', 'GMAIL_USER', 'GMAIL_APP_PASS', 'LEAD_EMAIL_TO'];
for (const key of required) {
  if (!process.env[key]) {
    console.error(`Missing required env var: ${key}`);
    process.exit(1);
  }
}

const PORT = process.env.PORT || 3001;

// ── Clients ───────────────────────────────────────────────────────────────────
const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

const mailer = nodemailer.createTransport({
  service: 'gmail',
  auth: {
    user: process.env.GMAIL_USER,
    pass: process.env.GMAIL_APP_PASS,
  },
});

// ── Aria system prompt ────────────────────────────────────────────────────────
// Edit this to change Aria's behavior, tone, or qualification questions.
const ARIA_SYSTEM_PROMPT = `You are Aria, the AI assistant for Broadhead Automations. Broadhead Automations builds custom AI automation systems that eliminate busywork and scale operations for small and mid-size businesses.

Your job is to qualify website visitors as potential leads. Be warm, direct, and conversational — no fluff, no corporate-speak. You're curious and genuinely interested in their business.

Follow this exact qualification flow, one question at a time. Do NOT ask multiple questions at once:

1. Ask what type of business they run.
2. Ask what the most time-consuming task their team handles manually is.
3. Ask roughly how many hours per week that takes.
4. Ask how big their team is.
5. Ask for the best name and email to reach them.

Rules:
- Ask one question at a time. Wait for their answer before moving on.
- Keep responses short — 1-3 sentences max.
- If they ask about pricing, services, or what Broadhead does, give a brief honest answer then redirect back to the qualification question.
- If they give a vague answer, ask a gentle follow-up to clarify before moving on.
- Once you have their name AND email (step 5), close with exactly this message (replace [Name] with their actual name): "Perfect, [Name]. Sean will follow up within 24 hours. Talk soon."
- After closing, do not ask any more questions. If they message again, just say you've passed along their info and Sean will be in touch.

When you have collected all five pieces of information (business type, pain point, hours/week, team size, name + email), include this exact JSON block at the very end of your closing message — on its own line, nothing after it:

LEAD_CAPTURED:{"name":"[name]","email":"[email]","businessType":"[type]","painPoint":"[task]","hoursPerWeek":"[hours]","teamSize":"[size]"}

Do not include the JSON until you have all five answers AND the visitor's name and email.`;

// ── Notion CRM ────────────────────────────────────────────────────────────────
async function saveLeadToNotion(lead) {
  if (!process.env.NOTION_API_KEY || !process.env.NOTION_LEADS_DB_ID) return;
  await fetch('https://api.notion.com/v1/pages', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${process.env.NOTION_API_KEY}`,
      'Content-Type': 'application/json',
      'Notion-Version': '2022-06-28',
    },
    body: JSON.stringify({
      parent: { database_id: process.env.NOTION_LEADS_DB_ID },
      properties: {
        Name: { title: [{ text: { content: lead.name || 'Unknown' } }] },
        Email: { email: lead.email || null },
        Phone: { phone_number: lead.phone || null },
        'Business Type': { rich_text: [{ text: { content: lead.businessType || '' } }] },
        'Pain Point': { rich_text: [{ text: { content: lead.painPoint || '' } }] },
        'Hours/Week': { rich_text: [{ text: { content: lead.hoursPerWeek || '' } }] },
        'Team Size': { rich_text: [{ text: { content: lead.teamSize || '' } }] },
        Status: { select: { name: 'New' } },
        'Captured At': { date: { start: new Date().toISOString() } },
      },
    }),
  });
  console.log(`[lead] Notion CRM updated for ${lead.name}`);
}

// ── Email sender ──────────────────────────────────────────────────────────────
async function sendLeadEmail(lead) {
  const timestamp = new Date().toLocaleString('en-US', { timeZone: 'America/Los_Angeles' });
  const subject = `New Lead: ${lead.businessType} — ${lead.name}`;
  const text = [
    'New lead from Broadhead Automations website',
    '',
    `Name:          ${lead.name}`,
    `Email:         ${lead.email}`,
    `Business Type: ${lead.businessType}`,
    `Pain Point:    ${lead.painPoint}`,
    `Hours/Week:    ${lead.hoursPerWeek}`,
    `Team Size:     ${lead.teamSize}`,
    '',
    `Captured: ${timestamp} PT`,
  ].join('\n');

  await mailer.sendMail({
    from: `"Broadhead Automations" <${process.env.GMAIL_USER}>`,
    to: process.env.LEAD_EMAIL_TO,
    subject,
    text,
  });

  console.log(`[lead] Email sent for ${lead.name} <${lead.email}>`);
}

// ── Express app ───────────────────────────────────────────────────────────────
const app = express();
app.use(cors());
app.use(express.json());

// Health check
app.get('/health', (_req, res) => res.json({ status: 'ok' }));

// Chat endpoint — accepts full message history from client (stateless, matches Lambda)
app.post('/chat', async (req, res) => {
  const { messages } = req.body;

  if (!Array.isArray(messages) || messages.length === 0) {
    return res.status(400).json({ error: 'messages array is required' });
  }

  try {
    const response = await anthropic.messages.create({
      model: 'claude-haiku-4-5',
      max_tokens: 512,
      system: ARIA_SYSTEM_PROMPT,
      messages,
    });

    const assistantText = response.content[0].text;

    // Check for lead capture signal
    const leadMatch = assistantText.match(/LEAD_CAPTURED:(\{.+\})/);
    let leadCaptured = false;
    if (leadMatch) {
      try {
        const lead = JSON.parse(leadMatch[1]);
        await sendLeadEmail(lead);
        await saveLeadToNotion(lead).catch(err => console.error('Notion save failed:', err.message));
        leadCaptured = true;
      } catch (err) {
        console.error('[lead] Failed to parse or send lead email:', err.message);
      }
    }

    const cleanText = assistantText.replace(/\nLEAD_CAPTURED:\{.+\}/, '').trim();

    return res.json({ reply: cleanText, leadCaptured });
  } catch (err) {
    console.error('[chat] Claude API error:', err.message);
    return res.status(500).json({
      reply: "I'm having trouble connecting right now — try again in a moment.",
      error: true,
    });
  }
});

app.listen(PORT, () => {
  console.log(`Aria chat server running on http://localhost:${PORT}`);
});
