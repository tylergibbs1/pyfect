// Every /docs link in the guides points at a page the build prerendered.
// Next does not check Markdown links, and reference URLs change with the code.
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const content = new URL('../content/docs/', import.meta.url).pathname;
const app = new URL('../.next/server/app', import.meta.url).pathname;
const link = /\]\((\/docs[^)#\s]*)/g;

const broken = [];
for (const file of readdirSync(content, { recursive: true })) {
  if (!String(file).endsWith('.mdx')) continue;
  const text = readFileSync(join(content, String(file)), 'utf8');
  for (const [, url] of text.matchAll(link)) {
    if (!existsSync(join(app, `${url}.html`))) broken.push(`${file}: ${url}`);
  }
}

if (broken.length > 0) {
  console.error(`Broken links:\n${broken.join('\n')}`);
  process.exit(1);
}
