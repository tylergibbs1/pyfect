// The streamed pass on fixture pages: text still arriving never counts, wherever the pauses
// land, and real shifts (a late font, an image without dimensions, a late banner, a complete
// button moved by one after it) always do. Every pause is painted (`PACED_HEADER`), so a fixture
// makes its shift however slow the machine. `bun run test:layout`; uses the installed Chrome.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { after, before, describe, test } from 'node:test';
import { chromium } from 'playwright-core';
import {
  OFFSET_HEADER,
  PACED_HEADER,
  pauses,
  reportPaintedFrames,
  startStreamingProxy,
  startTags,
  streamedShifts,
  watchStreamedShifts,
} from './streaming.mjs';

const FONT = new URL('../../node_modules/next/dist/next-devtools/server/font/geist-latin.woff2', import.meta.url);
// a 1x1 PNG
const PIXEL = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=',
  'base64',
);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const page = (body, head = '') => `<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><style>body{margin:16px;font:16px/1.5 sans-serif}</style>${head}</head>
<body>${body}</body></html>`;

/**
 * Words, with a "(" right before a long code span every few words. Chrome inserts the text the
 * parser has read only once it inserts the next node (an empty span here), so a pause after
 * the span is the one that paints the "(" without the code after it.
 */
const prose = (n) =>
  Array.from({ length: n }, (_, i) =>
    i % 7 === 3
      ? `see <code>run</code> (<span></span><code>effect.with_concurrency_and_a_long_name_${i}</code>)`
      : `streamed words ${i}`,
  ).join(' ');

const paragraphs = Array.from({ length: 12 }, () => `<p>${prose(60)}</p>`).join('\n');
const PAGES = {
  '/prose': page(`<h1>A guide</h1>${paragraphs}`),
  '/late-font': page(
    `<h1>A guide</h1>${paragraphs}`,
    `<style>@font-face{font-family:Late;src:url(/slow-font.woff2) format("woff2");font-display:swap}
     body{font-family:Late,monospace}</style>`,
  ),
  // These two move the page while it is still streaming in: about 70 KB, so 35 pauses (900 ms).
  '/image': page(`<h1>A guide</h1><img src="/slow.png" style="width:100%">${paragraphs.repeat(3)}`),
  // the script runs once the parser reaches it, and inserts the banner after the next frame
  '/banner': page(
    `<h1>A guide</h1>${paragraphs}<script>requestAnimationFrame(() => requestAnimationFrame(() => {
       const banner = document.createElement('div');
       banner.style.height = '80px';
       banner.textContent = 'A banner';
       document.body.prepend(banner);
     }))</script>${paragraphs.repeat(2)}`,
  ),
  // A comment of 24 KB, so a dozen pauses (300 ms) where only the part before it has arrived:
  // a slow runner paints the first frame late.
  // A pause always lands inside the link: it grows to the left as its text arrives.
  '/growing-link': page(
    `<div style="display:flex;justify-content:flex-end"><a href="/next">Next <span></span><!--${'x'.repeat(24 * 1024)}-->
     page, with a longer name</a></div>${paragraphs}`,
  ),
  // a pause always lands between the two buttons: the first is complete, and moves left
  '/row': page(
    `<div style="display:flex;justify-content:flex-end;gap:8px"><button>One</button>
     <!--${'x'.repeat(24 * 1024)}--><button>Two</button></div>${paragraphs}`,
  ),
};

let server;
let proxy;
let base;
let browser;

before(async () => {
  const font = await readFile(FONT);
  server = createServer(async (req, res) => {
    if (req.url === '/slow-font.woff2') {
      await wait(600);
      res.writeHead(200, { 'content-type': 'font/woff2' }).end(font);
    } else if (req.url === '/slow.png') {
      // well after the first paint, while the page is still streaming in
      await wait(400);
      res.writeHead(200, { 'content-type': 'image/png' }).end(PIXEL);
    } else if (req.url in PAGES) {
      res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' }).end(PAGES[req.url]);
    } else {
      res.writeHead(404).end();
    }
  });
  await new Promise((r) => server.listen(0, r));
  ({ proxy, base } = await startStreamingProxy(`http://localhost:${server.address().port}`));
  browser = await chromium.launch({ channel: 'chrome' });
});

after(async () => {
  await browser?.close();
  proxy?.close();
  server?.close();
});

let streams = 0;

/** Streams `path`, painted at every pause, so a fixture's shift happens however slow the machine. */
async function shifts(path, { offset = 0, width = 390 } = {}) {
  const context = await browser.newContext({
    viewport: { width, height: 900 },
    extraHTTPHeaders: { [OFFSET_HEADER]: String(offset), [PACED_HEADER]: String(streams++) },
  });
  await context.addInitScript(watchStreamedShifts);
  await context.addInitScript(reportPaintedFrames);
  try {
    return await streamedShifts(await context.newPage(), base + path, { settle: 300 });
  } finally {
    await context.close();
  }
}

/** `run` over `items`, a few at a time: many pages at once starve each other's frames. */
async function pooled(items, run, size = 3) {
  const results = [];
  for (let i = 0; i < items.length; i += size) results.push(...(await Promise.all(items.slice(i, i + size).map(run))));
  return results;
}

test('an offset moves every pause by that many bytes', () => {
  assert.deepEqual(pauses(7000), [2048, 4096, 6144]);
  assert.deepEqual(pauses(7000, 100), [100, 2148, 4196, 6244]);
  assert.deepEqual(pauses(300 * 1024).slice(-3), [254 * 1024, 256 * 1024, 288 * 1024]);
});

test('a paced pause waits for the elements whose start tags have arrived', () => {
  assert.equal(startTags('<!doctype html><html><head><meta charset="utf-8"><title>a <b></title>'), 4);
  assert.equal(startTags('<p>one <code>two</code> <a href="/x'), 2);
  assert.equal(startTags('<div><!-- <p> --><span></span><!-- <p>'), 2);
  assert.equal(startTags('<script>if (a <b) x()</script><p><script>"<i>'), 3);
});

describe('text still arriving', () => {
  const html = PAGES['/prose'];
  // a pause right after each of the first "(" before a code span
  const afterParens = [...html.matchAll(/\(<span><\/span><code>/g)].slice(0, 12).map((m) => m.index + '(<span></span>'.length);

  test('rewraps when a pause lands after a "(", and never counts', async () => {
    for (const width of [390, 1024]) {
      const offsets = [...afterParens, ...Array.from({ length: 8 }, (_, i) => i * 256)];
      const found = await pooled(offsets, (offset) => shifts('/prose', { offset, width }));
      let rewrapped = 0;
      found.forEach(({ counted, arriving }, i) => {
        assert.deepEqual(counted, [], `${width}px, pauses +${offsets[i]} B: ${JSON.stringify(counted)}`);
        rewrapped += arriving.length;
      });
      // so the pass saw text rewrap, and ignored it
      assert.ok(rewrapped > 0, `${width}px: no pause made a paragraph rewrap; the fixture tests nothing`);
    }
  });
});

test('a right-aligned link growing as its text arrives never counts', async () => {
  const offsets = [0, 700, 1400];
  const found = await pooled(offsets, (offset) => shifts('/growing-link', { offset, width: 1024 }));
  found.forEach(({ counted, arriving }, i) => {
    assert.deepEqual(counted, [], `pauses +${offsets[i]} B: ${JSON.stringify(counted)}`);
    assert.ok(arriving.length > 0, `pauses +${offsets[i]} B: the link never moved; the fixture tests nothing`);
  });
});

describe('real shifts count', () => {
  for (const [path, what, streaming] of [
    ['/late-font', 'a font that arrives after the text is painted', false],
    ['/image', 'an image without dimensions above the text', true],
    ['/banner', 'a script inserting a banner above the content', true],
    ['/row', 'a complete button moved by the one after it', true],
  ]) {
    test(what, async () => {
      const offsets = [0, 700, 1400];
      const found = await pooled(offsets, (offset) => shifts(path, { offset }));
      found.forEach(({ counted }, i) => {
        assert.ok(counted.length > 0, `pauses +${offsets[i]} B: no shift counted ${JSON.stringify(found[i])}`);
        // the ones that move while the HTML arrives are counted then, not only after it is in
        if (streaming) assert.ok(counted.some((s) => s.streaming), `pauses +${offsets[i]} B: ${JSON.stringify(counted)}`);
      });
    });
  }
});
