import Anthropic from '@anthropic-ai/sdk';
import nodemailer from 'nodemailer';

// ── Validate environment (checked at cold-start) ──────────────────────────────
const required = ['ANTHROPIC_API_KEY', 'GMAIL_USER', 'GMAIL_APP_PASS', 'LEAD_EMAIL_TO'];
for (const key of required) {
  if (!process.env[key]) throw new Error(`Missing required env var: ${key}`);
}

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

const mailer = nodemailer.createTransport({
  service: 'gmail',
  auth: { user: process.env.GMAIL_USER, pass: process.env.GMAIL_APP_PASS },
});

// ── Aria system prompt ────────────────────────────────────────────────────────
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

// ── CORS headers ──────────────────────────────────────────────────────────────
const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

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
}

// ── Lambda handler ────────────────────────────────────────────────────────────
export const handler = async (event) => {
  // CORS preflight
  if (event.requestContext?.http?.method === 'OPTIONS') {
    return { statusCode: 200, headers: CORS, body: '' };
  }

  // Health check
  if (event.rawPath === '/health') {
    return { statusCode: 200, headers: CORS, body: JSON.stringify({ status: 'ok' }) };
  }

  try {
    const body = JSON.parse(event.body || '{}');
    const { messages } = body;

    if (!Array.isArray(messages) || messages.length === 0) {
      return {
        statusCode: 400,
        headers: CORS,
        body: JSON.stringify({ error: 'messages array is required' }),
      };
    }

    const response = await anthropic.messages.create({
      model: 'claude-haiku-4-5',
      max_tokens: 512,
      system: ARIA_SYSTEM_PROMPT,
      messages,
    });

    const assistantText = response.content[0].text;

    // Check for lead capture signal
    let leadCaptured = false;
    const leadMatch = assistantText.match(/LEAD_CAPTURED:(\{.+\})/);
    if (leadMatch) {
      try {
        const lead = JSON.parse(leadMatch[1]);
        await sendLeadEmail(lead);
        leadCaptured = true;
      } catch (err) {
        console.error('Lead email failed:', err.message);
      }
    }

    const cleanText = assistantText.replace(/\nLEAD_CAPTURED:\{.+\}/, '').trim();

    return {
      statusCode: 200,
      headers: { ...CORS, 'Content-Type': 'application/json' },
      body: JSON.stringify({ reply: cleanText, leadCaptured }),
    };
  } catch (err) {
    console.error('Handler error:', err.message);
    return {
      statusCode: 500,
      headers: CORS,
      body: JSON.stringify({
        reply: "I'm having trouble connecting right now — try again in a moment.",
        error: true,
      }),
    };
  }
};
