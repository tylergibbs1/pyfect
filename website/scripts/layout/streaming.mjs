// The streamed pass of check-layout: a page painted while its HTML is still arriving, and the
// layout shifts that count there.
//
// The network can split a page's HTML anywhere, so the browser paints a block whose text has
// only partly arrived, and that block's lines rewrap as the rest comes in (a "(" that ended a
// line moves down with the code after it). That is text still arriving, not a shift: a reader
// sees the paragraph being filled in. What counts is content that had finished arriving before
// a paint moving after it: a complete paragraph, a button, a heading.
// So a shift's source counts unless, in the frame before the shift, it was text or an inline
// box laid out in a block the parser still had open, or it was itself still open and only grew
// (a right-aligned link whose text was arriving: its left edge moved, its right edge stayed).
import { createServer } from 'node:http';

/**
 * The page's HTML comes in small chunks for its first FINE_UNTIL bytes (the header, the title row
 * and the first screen) and large ones after, with a pause after each so the browser paints in
 * between. `offset` moves every pause that many bytes later, so a run can show its result does
 * not depend on where the pauses land. A paced page (see `PACED_HEADER`) is painted at every pause.
 */
const FINE_CHUNK = 2 * 1024;
const FINE_UNTIL = 256 * 1024;
const CHUNK = 32 * 1024;
const PAUSE = 25;

/** Where the pauses fall in a document of `length` bytes. */
export function pauses(length, offset = 0) {
  const at = [];
  let next = offset > 0 ? offset : FINE_CHUNK;
  while (next < length) {
    at.push(next);
    next += next < FINE_UNTIL ? FINE_CHUNK : CHUNK;
  }
  return at;
}

/** The request header that sets a page's offset (a context's `extraHTTPHeaders`). */
export const OFFSET_HEADER = 'x-stream-offset';

/**
 * The request header that paces a page (a context's `extraHTTPHeaders`, with `reportPaintedFrames`
 * as an init script): a pause lasts until the page has painted what came before it, however
 * slowly the machine paints, instead of a fixed time a starved CPU may not fit a frame into.
 * Its value names the page's stream, unique among the pages streaming at once.
 */
export const PACED_HEADER = 'x-stream-paced';
const PAINTED_PATH = '/__stream-painted';

/**
 * How many elements the parser has made once it has read `html`: its complete start tags, outside
 * comments and the text of raw-text elements.
 */
export function startTags(html) {
  const tags = html
    .replace(/<!--[\s\S]*?(-->|$)/g, '')
    .replace(/<(script|style|title|textarea)\b([^>]*)>[\s\S]*?(?=<\/\1|$)/gi, '<$1$2>');
  return tags.match(/<[a-zA-Z][^>]*>/g)?.length ?? 0;
}

/**
 * An init script for a paced page: after each frame painted while the HTML arrives, tells the
 * proxy how many elements that frame had.
 */
export function reportPaintedFrames() {
  const elements = document.getElementsByTagName('*');
  let sent = -1;
  const tick = () => {
    if (document.readyState !== 'loading') return;
    const count = elements.length;
    // a task queued in a frame's callbacks runs after that frame is rendered
    setTimeout(() => {
      if (count <= sent) return;
      sent = count;
      // PAINTED_PATH, spelled out: an init script is sent to the page as its source alone
      fetch('/__stream-painted', { method: 'POST', body: String(count) });
    });
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

/** A proxy to `upstream` that streams HTML documents with pauses (see `pauses`). */
export async function startStreamingProxy(upstream) {
  /** Per paced stream: the most elements a painted frame had, and a wake for the pause waiting on it. */
  const paced = new Map();
  const proxy = createServer(async (req, res) => {
    const stream = req.headers[PACED_HEADER];
    if (req.url === PAINTED_PATH) {
      let body = '';
      for await (const part of req) body += part;
      const page = paced.get(stream);
      if (page) {
        page.painted = Math.max(page.painted, Number(body));
        page.wake();
      }
      res.writeHead(204).end();
      return;
    }
    const offset = Number(req.headers[OFFSET_HEADER] ?? 0);
    const headers = { ...req.headers };
    delete headers.host;
    delete headers['accept-encoding'];
    delete headers[OFFSET_HEADER];
    delete headers[PACED_HEADER];
    const response = await fetch(upstream + req.url, { headers });
    const body = Buffer.from(await response.arrayBuffer());
    res.writeHead(response.status, {
      'content-type': response.headers.get('content-type') ?? '',
      'cache-control': 'no-store',
    });
    // only the page itself; the router's prefetches and assets come at full speed
    if (req.headers['sec-fetch-dest'] !== 'document') {
      res.end(body);
      return;
    }
    const page = stream === undefined ? undefined : { painted: 0, wake: () => {} };
    if (page) paced.set(stream, page);
    let from = 0;
    for (const to of pauses(body.length, offset)) {
      res.write(body.subarray(from, to));
      from = to;
      const pause = new Promise((r) => setTimeout(r, PAUSE));
      if (page) {
        const made = startTags(body.subarray(0, to).toString());
        while (page.painted < made) await new Promise((r) => (page.wake = r));
      }
      await pause;
    }
    res.end(body.subarray(from));
    paced.delete(stream);
  });
  await new Promise((r) => proxy.listen(0, r));
  return { proxy, base: `http://localhost:${proxy.address().port}` };
}

/**
 * An init script: records every layout shift, and in each frame the elements the parser still
 * has open, so `window.__streamedShifts()` can tell text still arriving from content that moved.
 */
export function watchStreamedShifts() {
  const SLACK = 100;
  /** One per frame, in order: when it ran and the nodes still open (the document's last path). */
  const frames = [];
  const entries = [];
  const tick = () => {
    const open = new Set();
    if (document.readyState === 'loading') {
      for (let n = document.documentElement; n; n = n.lastChild) open.add(n);
    }
    frames.push({ t: performance.now(), open });
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
  new PerformanceObserver((list) => entries.push(...list.getEntries())).observe({
    type: 'layout-shift',
    buffered: true,
  });

  const inlineLevel = (el) => /^(inline|contents|ruby)/.test(getComputedStyle(el).display);
  /** The block whose lines place `node`: for text or an inline box, the nearest non-inline ancestor. */
  const lineBlock = (node) => {
    let el = node instanceof Element && !inlineLevel(node) ? null : node.parentElement;
    while (el && inlineLevel(el)) el = el.parentElement;
    return el;
  };
  /**
   * Whether a box only grew where it stands: along each axis its start stayed, or it grew with
   * its end (aligned to the end) or its center (centered) fixed. A rect the viewport clips on an
   * axis does not show its true size there, so along that axis only a start that stayed counts.
   */
  const grewInPlace = ({ previousRect: a, currentRect: b }) => {
    const axis = (start, size, start2, size2, limit) => {
      const moved = start2 - start;
      const grew = size2 - size;
      const clipped = [start, start2].some((p) => p < 0.5) || [start + size, start2 + size2].some((p) => p > limit - 0.5);
      if (Math.abs(moved) < 0.5) return true;
      return !clipped && grew > 0 && (Math.abs(moved + grew) < 1 || Math.abs(moved + grew / 2) < 1);
    };
    return axis(a.x, a.width, b.x, b.width, innerWidth) && axis(a.y, a.height, b.y, b.height, innerHeight);
  };
  const stillArriving = (source, open) => {
    const block = lineBlock(source.node);
    return (block !== null && open.has(block)) || (open.has(source.node) && grewInPlace(source));
  };
  const describe = (s) => {
    const n = s.node;
    const name = (el) => `${el.tagName.toLowerCase()}.${el.className}`.slice(0, 80);
    const moved = `y ${Math.round(s.previousRect.y)}->${Math.round(s.currentRect.y)} x ${Math.round(s.previousRect.x)}->${Math.round(s.currentRect.x)}`;
    if (n instanceof Element) {
      const text = (n.getAttribute('href') ?? n.textContent ?? '').trim().slice(0, 40);
      return `${name(n)} "${text}" in ${n.parentElement ? name(n.parentElement) : '?'} ${moved}`;
    }
    if (n?.nodeType === Node.TEXT_NODE) {
      const text = n.textContent.trim().slice(0, 40);
      return `text "${text}" in ${n.parentElement ? name(n.parentElement) : '?'} ${moved}`;
    }
    return `${String(n)} ${moved}`;
  };

  /**
   * `counted`: the shifts in which something already complete moved. `arriving`: the others,
   * in which every source was text still arriving.
   */
  window.__streamedShifts = () => {
    const counted = [];
    const arriving = [];
    for (const entry of entries) {
      // The layout a shift moved from is the frame before the one it was painted in. Chrome
      // stamps a shift with its frame's start, which on a busy machine is well before that
      // frame's callbacks ran, so the frames of the SLACK ms before the shift, the last one
      // that started before it and the one before that all count: what was open in any of them
      // was still arriving (this hides nothing that had been complete for longer).
      let i = frames.length - 1;
      while (i >= 0 && frames[i].t >= entry.startTime) i--;
      const before = new Set();
      for (let j = i; j >= 0 && (j >= i - 1 || frames[j].t >= entry.startTime - SLACK); j--) {
        for (const node of frames[j].open) before.add(node);
      }
      // a source whose node is gone (removed since) counts
      const moved = entry.sources.filter((s) => !s.node || !stillArriving(s, before));
      const shift = {
        value: entry.value,
        // whether the HTML was still arriving
        streaming: before.size > 0,
        sources: (moved.length > 0 ? moved : entry.sources).map(describe),
      };
      (moved.length > 0 ? counted : arriving).push(shift);
    }
    return { counted, arriving };
  };
}

/** Loads `url` streamed (in a context with `watchStreamedShifts`); see `window.__streamedShifts`. */
export async function streamedShifts(page, url, { settle = 800 } = {}) {
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(settle);
  return page.evaluate(() => window.__streamedShifts());
}
