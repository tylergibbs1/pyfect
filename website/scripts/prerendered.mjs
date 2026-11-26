// Where `next build` left a prerendered route's response body. Without an adapter it is
// `.next/server/app/<route>.body`; with one (Vercel sets NEXT_ADAPTER_PATH) Next writes
// `.next/server/route-cache/APP_ROUTE/<hash>/$/<route>.body` instead. The postbuild checks
// look a body up here rather than by a fixed path, so they pass on both layouts.
import { readdirSync } from 'node:fs';
import { join, sep } from 'node:path';

const server = new URL('../.next/server/', import.meta.url).pathname;

/** The path of `route`'s prerendered body (`'sitemap.xml'`, `'api/search'`), or `undefined`. */
export function prerenderedBody(route) {
  const suffix = `${sep}${route.split('/').join(sep)}.body`;
  const found = readdirSync(server, { recursive: true })
    .map(String)
    .find((path) => `${sep}${path}`.endsWith(suffix));
  return found === undefined ? undefined : join(server, found);
}
