#!/usr/bin/env node
/**
 * setup-notion-crm.js
 *
 * One-time setup: creates the Broadhead Leads database in Notion.
 *
 * Usage:
 *   node tools/setup-notion-crm.js <NOTION_PAGE_ID>
 *
 * Where NOTION_PAGE_ID is the ID of the Notion page that will contain
 * the database. Find it in the page URL:
 *   https://www.notion.so/Your-Page-Title-{PAGE_ID}
 *
 * After running, copy the printed database ID into your .env:
 *   NOTION_LEADS_DB_ID=<printed id>
 */

import 'dotenv/config';

const NOTION_VERSION = '2022-06-28';

const parentPageId = process.argv[2];
if (!parentPageId) {
  console.error('Usage: node tools/setup-notion-crm.js <NOTION_PAGE_ID>');
  process.exit(1);
}

const apiKey = process.env.NOTION_API_KEY;
if (!apiKey) {
  console.error('Missing NOTION_API_KEY in .env');
  process.exit(1);
}

async function notionPost(path, body) {
  const res = await fetch(`https://api.notion.com/v1${path}`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
      'Notion-Version': NOTION_VERSION,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Notion API ${res.status}: ${err}`);
  }
  return res.json();
}

async function setup() {
  console.log('Creating Broadhead Leads database in Notion...');

  const db = await notionPost('/databases', {
    parent: { type: 'page_id', page_id: parentPageId },
    title: [{ type: 'text', text: { content: 'Broadhead Leads' } }],
    properties: {
      Name: { title: {} },
      Email: { email: {} },
      Phone: { phone_number: {} },
      'Business Type': { rich_text: {} },
      'Pain Point': { rich_text: {} },
      'Hours/Week': { rich_text: {} },
      'Team Size': { rich_text: {} },
      Status: {
        select: {
          options: [
            { name: 'New', color: 'blue' },
            { name: 'Contacted', color: 'yellow' },
            { name: 'Qualified', color: 'green' },
            { name: 'Closed', color: 'purple' },
            { name: 'Not a Fit', color: 'gray' },
          ],
        },
      },
      'Captured At': { date: {} },
      Notes: { rich_text: {} },
    },
  });

  console.log('\n✓ Database created successfully.');
  console.log('\nAdd this to your Broadhead .env file:');
  console.log(`\n  NOTION_LEADS_DB_ID=${db.id}\n`);
  console.log('Then redeploy Lambda: bash tools/deploy.sh');
}

setup().catch((err) => {
  console.error('Setup failed:', err.message);
  process.exit(1);
});
