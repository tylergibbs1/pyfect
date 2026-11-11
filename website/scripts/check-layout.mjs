// Every docs page uses one frame: the title, description, body and table of contents
// sit at the same place on a guide, a guide with tabs and diagrams, and an API reference
// page, at every width, and nothing shifts while a page loads or after a client-side
// navigation.
//
// Runs against the production build (`bun run build` first). Uses the installed
// Google Chrome, so no browser download is needed (GitHub's Ubuntu runners have it).
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { chromium } from 'playwright-core';

const PORT = 3199;
const BASE = `http://localhost:${PORT}`;
const PAGES = {
  guide: '/docs/effects',
  richGuide: '/docs/streams',
  reference: '/docs/reference/stream',
};
const WIDTHS = [1512, 1280, 1024, 390];
/** How late the fonts arrive in the late-font pass, in ms: well after the first paint. */
const FONT_DELAY = 1000;
/**
 * The streamed pass sends each page's HTML in chunks this size with a pause between them, so
 * the browser paints it part-parsed, as it does on a slow connection. These pages are large
 * (up to a few MB), and something laid out by an element that comes later in the document
 * moves when that element arrives; without the pauses that happened only on some runs.
 */
const STREAM_CHUNK = 32 * 1024;
const STREAM_PAUSE = 40;

/** Positions that must match across page types. */
function measure() {
  const box = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return null;
    return { x: Math.round(r.x * 10) / 10, y: Math.round(r.y * 10) / 10 };
  };
  const article = document.querySelector('[data-docs-article]');
  return {
    h1: box(article?.querySelector('h1')),
    // its y follows the title, which wraps on phones when it is long
    description: box(article?.querySelector(':scope > div:first-child > p'))?.x ?? null,
    body: box(article?.querySelector('.typeset'))?.x ?? null,
    tocRail: box(document.querySelector('[data-docs-toc-rail] p'))?.x ?? null,
    // its y follows the description, whose length varies by page
    tocBox: box(article?.querySelector('[data-docs-toc-box] button'))?.x ?? null,
    scrollWidth: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  };
}

function recordShifts() {
  window.__shifts = [];
  new PerformanceObserver((list) => {
    for (const entry of list.getEntries()) {
      window.__shifts.push({
        value: entry.value,
        sources: entry.sources.map((s) => {
          const n = s.node;
          return n instanceof Element ? `${n.tagName.toLowerCase()}.${n.className}`.slice(0, 80) : String(n);
        }),
      });
    }
  }).observe({ type: 'layout-shift', buffered: true });
}

const settle = (page) => page.waitForTimeout(800);

async function startServer() {
  const server = spawn('npx', ['next', 'start', '-p', String(PORT)], { stdio: 'ignore' });
  for (let i = 0; i < 100; i++) {
    try {
      if ((await fetch(`${BASE}/docs`)).ok) return server;
    } catch {}
    await new Promise((r) => setTimeout(r, 200));
  }
  server.kill();
  throw new Error('next start did not come up; run `bun run build` first');
}

/** A proxy to the site that streams HTML documents slowly (see STREAM_CHUNK). */
async function startStreamingProxy() {
  const proxy = createServer(async (req, res) => {
    const headers = { ...req.headers };
    delete headers.host;
    delete headers['accept-encoding'];
    const upstream = await fetch(BASE + req.url, { headers });
    const type = upstream.headers.get('content-type') ?? '';
    const body = Buffer.from(await upstream.arrayBuffer());
    res.writeHead(upstream.status, { 'content-type': type, 'cache-control': 'no-store' });
    // only the page itself; the router's prefetches and assets come at full speed
    if (req.headers['sec-fetch-dest'] !== 'document') {
      res.end(body);
      return;
    }
    for (let at = 0; at < body.length; at += STREAM_CHUNK) {
      res.write(body.subarray(at, at + STREAM_CHUNK));
      await new Promise((r) => setTimeout(r, STREAM_PAUSE));
    }
    res.end();
  });
  await new Promise((r) => proxy.listen(0, r));
  return { proxy, base: `http://localhost:${proxy.address().port}` };
}

const failures = [];
const same = (what, a, b) => {
  if (JSON.stringify(a) !== JSON.stringify(b)) {
    failures.push(`${what}: ${JSON.stringify(a)} vs ${JSON.stringify(b)}`);
  }
};

const server = await startServer();
const { proxy, base: STREAMED_BASE } = await startStreamingProxy();
const browser = await chromium.launch({ channel: 'chrome' });
try {
  for (const width of WIDTHS) {
    const context = await browser.newContext({ viewport: { width, height: 900 } });
    await context.addInitScript(recordShifts);
    const page = await context.newPage();

    const loaded = {};
    for (const [kind, path] of Object.entries(PAGES)) {
      await page.goto(BASE + path, { waitUntil: 'networkidle' });
      await page.evaluate(() => document.fonts.ready);
      await settle(page);
      loaded[kind] = await page.evaluate(measure);
      const shifts = await page.evaluate(() => window.__shifts);
      if (shifts.length > 0) failures.push(`${width}px ${path}: layout shift on load ${JSON.stringify(shifts)}`);
      if (loaded[kind].scrollWidth > loaded[kind].viewport) {
        failures.push(`${width}px ${path}: scrolls sideways (${loaded[kind].scrollWidth}px)`);
      }
      if (!loaded[kind].h1) failures.push(`${width}px ${path}: no h1`);
    }

    const [first, ...rest] = Object.keys(PAGES);
    for (const kind of rest) {
      for (const key of ['h1', 'description', 'body', 'tocRail', 'tocBox']) {
        same(`${width}px ${key} ${first} vs ${kind}`, loaded[first][key], loaded[kind][key]);
      }
    }

    // Client-side navigation between page types: same positions, no shifts.
    await page.goto(BASE + PAGES.guide, { waitUntil: 'networkidle' });
    await settle(page);
    for (const [kind, path] of Object.entries(PAGES).filter(([k]) => k !== 'guide')) {
      await page.evaluate(() => {
        window.__shifts = [];
      });
      // a synthetic click (not user input), so the observer counts any shift it causes
      await page.evaluate((href) => {
        const link = document.querySelector(`a[href="${href}"]`);
        if (!link) throw new Error(`no link to ${href}`);
        link.click();
      }, path);
      await page.waitForURL(BASE + path);
      await settle(page);
      const shifts = await page.evaluate(() => window.__shifts);
      if (shifts.length > 0) {
        failures.push(`${width}px client nav to ${path}: layout shift ${JSON.stringify(shifts)}`);
      }
      const navigated = await page.evaluate(measure);
      for (const key of ['h1', 'description', 'body', 'tocRail', 'tocBox']) {
        same(`${width}px ${key} after client nav to ${kind}`, loaded[kind][key], navigated[key]);
      }
      await page.goBack();
      await page.waitForURL(BASE + PAGES.guide);
      await settle(page);
    }
    await context.close();

    // Fonts arriving after the first paint (a slow runner): nothing may move when they do.
    const late = await browser.newContext({ viewport: { width, height: 900 } });
    await late.addInitScript(recordShifts);
    await late.route(/\.woff2(\?|$)/, async (route) => {
      await new Promise((r) => setTimeout(r, FONT_DELAY));
      await route.continue();
    });
    const latePage = await late.newPage();
    for (const path of Object.values(PAGES)) {
      await latePage.goto(BASE + path, { waitUntil: 'networkidle' });
      await latePage.evaluate(() => document.fonts.ready);
      await settle(latePage);
      const shifts = await latePage.evaluate(() => window.__shifts);
      if (shifts.length > 0) {
        failures.push(`${width}px ${path}: layout shift when fonts load late ${JSON.stringify(shifts)}`);
      }
    }
    await late.close();

    // Each page painted while its HTML is still arriving: nothing already painted may move.
    const streamed = await browser.newContext({ viewport: { width, height: 900 } });
    await streamed.addInitScript(recordShifts);
    const streamedPage = await streamed.newPage();
    for (const path of Object.values(PAGES)) {
      await streamedPage.goto(STREAMED_BASE + path, { waitUntil: 'networkidle' });
      await streamedPage.evaluate(() => document.fonts.ready);
      await settle(streamedPage);
      const shifts = await streamedPage.evaluate(() => window.__shifts);
      if (shifts.length > 0) {
        failures.push(`${width}px ${path}: layout shift while the page streams in ${JSON.stringify(shifts)}`);
      }
    }
    await streamed.close();
  }
} finally {
  await browser.close();
  proxy.close();
  server.kill();
}

if (failures.length > 0) {
  console.error(`Layout differs between pages:\n${failures.join('\n')}`);
  process.exit(1);
}
console.log(`layout ok: ${Object.keys(PAGES).length} page types at ${WIDTHS.join(', ')}px`);
