// What search engines read from the build: `/` redirects to `/docs` permanently (308, so the
// docs index gets the front page's ranking), and the sitemap dates every guide and post. The
// live sitemap once went out with no guide dated, because their dates came from git history
// that Vercel's clone doesn't have; nothing failed.
import { readFileSync } from 'node:fs';

const next = new URL('../.next/', import.meta.url);
const failures = [];

const { redirects } = JSON.parse(readFileSync(new URL('routes-manifest.json', next), 'utf8'));
const root = redirects.find((r) => r.source === '/');
if (root?.destination !== '/docs' || root.statusCode !== 308) {
  failures.push(`/ must redirect to /docs with a 308, not ${JSON.stringify(root)}`);
}

const sitemap = readFileSync(new URL('server/app/sitemap.xml.body', next), 'utf8');
const entries = [...sitemap.matchAll(/<url>([\s\S]*?)<\/url>/g)].map(([, body]) => ({
  loc: body.match(/<loc>(.*?)<\/loc>/)?.[1] ?? '',
  dated: body.includes('<lastmod>'),
}));
const mustBeDated = entries.filter(({ loc }) => !new URL(loc).pathname.startsWith('/docs/reference'));
const undated = mustBeDated.filter(({ dated }) => !dated).map(({ loc }) => loc);
if (undated.length > 0) failures.push(`The sitemap leaves ${undated.length} pages undated: ${undated.slice(0, 5).join(', ')}`);
if (mustBeDated.length < 50) failures.push(`The sitemap lists only ${mustBeDated.length} guides and posts`);

if (failures.length > 0) {
  for (const failure of failures) console.error(failure);
  process.exit(1);
}
console.log(`Sitemap: ${mustBeDated.length} guides and posts dated, ${entries.length} URLs; / redirects with a 308.`);
