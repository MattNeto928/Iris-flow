// Deterministic frame grabber: seeks the paused timeline through headless
// Chrome and writes one PNG per frame. No wall-clock anywhere in the loop.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import puppeteer from 'puppeteer-core';
import { serve } from './serve.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

// Override with CHROME_PATH if Chrome lives elsewhere (or use Chromium/Edge).
const CANDIDATES = [
  process.env.CHROME_PATH,
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Chromium.app/Contents/MacOS/Chromium',
  '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
  '/usr/bin/chromium-browser',
].filter(Boolean);

const probeOnly = process.argv.includes('--probe');
const arg = (n, d) => (process.argv.includes(n) ? process.argv[process.argv.indexOf(n) + 1] : d);
const PAGE = arg('--page', 'piece.html');
const OUTDIR = arg('--out', 'out/frames');
const CHROME_ENV = process.env.CHROME_PATH;

const only = process.argv.includes('--only')
  ? process.argv[process.argv.indexOf('--only') + 1].split(',').map(Number)
  : null;
// --stride N renders every Nth frame. Filenames keep their true frame numbers,
// so contact sheets and the gates still line up with the timeline.
const stride = Number(arg('--stride', 0)) || 0;   // --probe is declared above

const OUT = path.join(ROOT, OUTDIR);
fs.mkdirSync(OUT, { recursive: true });
// A full or strided render must not leave the previous render's frames behind:
// a glob would tile them into contact sheets and the gates would score a
// mixture. --only appends, and --probe renders nothing, so neither may clear --
// probing must never be able to destroy an existing render.
if (!only && !probeOnly) {
  for (const f of fs.readdirSync(OUT)) fs.unlinkSync(path.join(OUT, f));
}

const fsx = await import('node:fs');
const CHROME = CANDIDATES.find((p) => fsx.existsSync(p));
if (!CHROME) {
  console.error('No Chrome found. Set CHROME_PATH to a Chrome/Chromium binary.');
  process.exit(1);
}

const { port } = await serve(0);
const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: 'shell',
  args: [
    '--enable-unsafe-swiftshader',
    '--use-angle=metal',
    '--hide-scrollbars',
    '--force-color-profile=srgb',
    '--disable-lcd-text',
  ],
});

const page = await browser.newPage();
await page.setViewport({ width: 1080, height: 1920, deviceScaleFactor: 1 });

const errors = [];
page.on('pageerror', (e) => errors.push(String(e)));
page.on('console', (m) => {
  // The response handler below reports HTTP failures with their URL; this
  // generic console twin carries no URL, so it is noise.
  if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) {
    errors.push(m.text());
  }
});
page.on('response', (r) => {
  // favicon is requested by the browser, not by us -- not a real failure
  if (r.status() >= 400 && !r.url().endsWith('/favicon.ico')) {
    errors.push(`HTTP ${r.status()} ${r.url()}`);
  }
});

await page.goto(`http://localhost:${port}/${PAGE}?render=1`, { waitUntil: 'load' });
await page.waitForFunction('window.__ready === true', { timeout: 30000 }).catch(() => {});

if (errors.length) {
  console.error('page errors:\n  ' + errors.join('\n  '));
  await browser.close();
  process.exit(1);
}

const { frames } = await page.evaluate(() => ({ frames: window.__piece.frames }));
let list = only ?? Array.from({ length: frames }, (_, i) => i);
if (!only && stride > 1) list = list.filter((i) => i % stride === 0);

const det = await page.evaluate(() => window.__piece.determinismCheck());
console.log(`determinism (a frame rendered twice): ${det ? 'IDENTICAL' : 'DIFFERS'}`);
if (!det) console.error('  -> pose() is not pure in frame. See references/debugging.md');

// Camera-path clearance: catches "the camera flies through the subject" in a
// second, rather than after a full render.
if (probeOnly || stride > 1) {
  const hits = await page.evaluate(() =>
    (window.__piece.cameraClearance ? window.__piece.cameraClearance() : []));
  if (hits.length) {
    console.log(`camera clearance: ${hits.length} sampled frames closer than 1.5 units to geometry`);
    for (const h of hits.slice(0, 8)) {
      console.log(`  f${h.frame}  ${h.clearance} units from ${h.object}`);
    }
    if (hits.length > 8) console.log(`  ... and ${hits.length - 8} more`);
  } else {
    console.log('camera clearance: clear');
  }
}

if (probeOnly) { await browser.close(); process.exit(0); }

const t0 = Date.now();
for (const f of list) {
  const data = await page.evaluate((n) => {
    window.__piece.seek(n);
    return document.querySelector('canvas').toDataURL('image/png');
  }, f);
  fs.writeFileSync(
    path.join(OUT, `f${String(f).padStart(4, '0')}.png`),
    Buffer.from(data.split(',')[1], 'base64'),
  );
  if (f % 24 === 0) process.stdout.write(`\r  frame ${f}/${frames}`);
}
const secs = (Date.now() - t0) / 1000;
console.log(`\rrendered ${list.length} frames in ${secs.toFixed(1)}s`);

if (errors.length) console.error('page errors during render:\n  ' + errors.join('\n  '));
await browser.close();
process.exit(0);
