// Every docs page uses one frame: the title, description, body and table of contents
// sit at the same place on a guide, a guide with tabs and diagrams, and an API reference
// page, at every width, and nothing shifts while a page loads or after a client-side
// navigation.
//
// Runs against the production build (`bun run build` first). Uses the installed
// Google Chrome, so no browser download is needed (GitHub's Ubuntu runners have it).
import { spawn } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { chromium } from 'playwright-core';
import { OFFSET_HEADER, startStreamingProxy, streamedShifts, watchStreamedShifts } from './layout/streaming.mjs';

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
// `--sweep`: only the streamed pass, on every docs page, at every width and each `--offsets`
// (comma-separated bytes), `--jobs` pages at a time, `--pages` a comma-separated subset. Proves no
// page depends on where pauses land. `--raw` counts every shift, text still arriving too (what
// this check counted before it told the two apart).
const args = process.argv.slice(2);
const flag = (name) => args.find((a) => a.startsWith(`--${name}=`))?.split('=')[1];
const SWEEP = args.includes('--sweep');
const SWEEP_OFFSETS = (flag('offsets') ?? '0,509,1021,1531').split(',').map(Number);
const JOBS = Number(flag('jobs') ?? 4);
const RAW = args.includes('--raw');

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
          const name = (el) => `${el.tagName.toLowerCase()}.${el.className}`.slice(0, 80);
          const moved = `${Math.round(s.previousRect.y)}->${Math.round(s.currentRect.y)}`;
          if (n instanceof Element) return `${name(n)} y ${moved}`;
          // a text node: the element holding it and the start of its text
          const text = (n?.textContent ?? '').trim().slice(0, 40);
          return `text "${text}" in ${n?.parentElement ? name(n.parentElement) : '?'} y ${moved}`;
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

/** Streams each path at `width` with every pause `offset` bytes later, `jobs` pages at a time. */
async function streamedFailures(browser, width, offset, paths, { jobs = 1, all = false, settle = 800 } = {}) {
  const context = await browser.newContext({
    viewport: { width, height: 900 },
    extraHTTPHeaders: { [OFFSET_HEADER]: String(offset) },
  });
  await context.addInitScript(watchStreamedShifts);
  const found = [];
  const queue = [...paths];
  await Promise.all(
    Array.from({ length: jobs }, async () => {
      const page = await context.newPage();
      for (let path = queue.shift(); path !== undefined; path = queue.shift()) {
        const { counted, arriving } = await streamedShifts(page, STREAMED_BASE + path, { settle });
        const shifts = all ? [...counted, ...arriving] : counted;
        if (shifts.length > 0) {
          found.push(`${width}px ${path} (pauses +${offset} B): layout shift while the page streams in ${JSON.stringify(shifts)}`);
        }
      }
      await page.close();
    }),
  );
  await context.close();
  return found;
}

const failures = [];
const same = (what, a, b) => {
  if (JSON.stringify(a) !== JSON.stringify(b)) {
    failures.push(`${what}: ${JSON.stringify(a)} vs ${JSON.stringify(b)}`);
  }
};

const server = await startServer();
const { proxy, base: STREAMED_BASE } = await startStreamingProxy(BASE);
const browser = await chromium.launch({ channel: 'chrome' });
try {
  if (SWEEP) {
    const manifest = JSON.parse(await readFile(new URL('../.next/prerender-manifest.json', import.meta.url), 'utf8'));
    const paths =
      flag('pages')?.split(',') ?? Object.keys(manifest.routes).filter((r) => r === '/docs' || r.startsWith('/docs/'));
    for (const width of WIDTHS) {
      for (const offset of SWEEP_OFFSETS) {
        // a shorter settle: the sweep is thousands of loads
        const found = await streamedFailures(browser, width, offset, paths, { jobs: JOBS, all: RAW, settle: 400 });
        console.log(`${width}px, pauses +${offset} B: ${paths.length} pages, ${found.length} with a shift`);
        failures.push(...found);
      }
    }
  }
  for (const width of SWEEP ? [] : WIDTHS) {
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
    failures.push(...(await streamedFailures(browser, width, 0, Object.values(PAGES))));
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
