// Every /docs link in the guides points at a page the build prerendered.
// Next does not check Markdown links, and reference URLs change with the code.
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const content = new URL('../content/docs/', import.meta.url).pathname;
// The prerender manifest has the same shape on local and Vercel builds;
// where the HTML files land does not.
const manifest = new URL('../.next/prerender-manifest.json', import.meta.url).pathname;
const pages = new Set(Object.keys(JSON.parse(readFileSync(manifest, 'utf8')).routes));
const link = /\]\((\/docs[^)#\s]*)/g;

const broken = [];
for (const file of readdirSync(content, { recursive: true })) {
  if (!String(file).endsWith('.mdx')) continue;
  const text = readFileSync(join(content, String(file)), 'utf8');
  for (const [, url] of text.matchAll(link)) {
    if (!pages.has(url)) broken.push(`${file}: ${url}`);
  }
}

if (broken.length > 0) {
  console.error(`Broken links:\n${broken.join('\n')}`);
  process.exit(1);
}
