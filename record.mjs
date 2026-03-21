import puppeteer from 'puppeteer';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

process.env.LD_LIBRARY_PATH = '/tmp/chrome-deps/extracted/usr/lib/x86_64-linux-gnu' + (process.env.LD_LIBRARY_PATH ? ':' + process.env.LD_LIBRARY_PATH : '');

const dir = path.join(__dirname, 'temporary screenshots');
if (!fs.existsSync(dir)) fs.mkdirSync(dir);

(async () => {
  const browser = await puppeteer.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--disable-setuid-sandbox'],
    executablePath: '/home/belkn/.cache/puppeteer/chrome/linux-146.0.7680.76/chrome-linux64/chrome',
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });

  // Load HTML directly — use file:// protocol
  const filePath = path.join(__dirname, 'index.html');
  await page.goto('file://' + filePath, { waitUntil: 'load', timeout: 30000 });

  // Wait for rendering + animations to start
  await new Promise(r => setTimeout(r, 2000));

  // Take a few screenshots at intervals to show animation state
  for (let i = 0; i < 5; i++) {
    await page.screenshot({ path: path.join(dir, `recording-frame-${i}.png`) });
    await new Promise(r => setTimeout(r, 1000));
  }

  console.log('Saved 5 frames');
  await browser.close();
})();
