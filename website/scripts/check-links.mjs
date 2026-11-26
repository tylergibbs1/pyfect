// Every link in the guides, the blog's posts and the API reference points at a page the build prerendered,
// or at another site by an absolute URL. Next does not check Markdown links, reference URLs
// change with the code, and the reference renders docstrings as Markdown, so a docstring
// that links to a path (a provider spec's `[key](/docs/guides/...)`) resolves against pyfect.dev.
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const content = new URL('../content/', import.meta.url).pathname;
// The prerender manifest has the same shape on local and Vercel builds;
// where the HTML files land does not.
const manifest = new URL('../.next/prerender-manifest.json', import.meta.url).pathname;
const reference = new URL('../.generated/pyfect.json', import.meta.url).pathname;
const pages = new Set(Object.keys(JSON.parse(readFileSync(manifest, 'utf8')).routes));
const link = /\]\((\/(?:docs|blog)[^)#\s]*)/g;

const broken = [];
for (const file of readdirSync(content, { recursive: true })) {
  if (!String(file).endsWith('.mdx')) continue;
  const text = readFileSync(join(content, String(file)), 'utf8');
  for (const [, url] of text.matchAll(link)) {
    if (!pages.has(url)) broken.push(`${file}: ${url}`);
  }
}

// The reference's Markdown: docstrings (`description`) and the sections generate_api.py
// writes (`{ kind: 'text', value }`). Signatures and source are code, never links.
const code = /```[\s\S]*?```|``[\s\S]*?``|`[^`\n]*`/g;
const anyLink = /\]\(\s*<?([^)\s>]*)|\b(?:href|src)\s*=\s*["']([^"']*)/g;
const absolute = /^[a-z][a-z0-9+.-]*:/i;
const urlLike = /^[\w./#?=&%~+-]+$/;

function checkMarkdown(where, text) {
  for (const match of text.replace(code, '').matchAll(anyLink)) {
    const target = match[1] || match[2] || '';
    if (!target || absolute.test(target) || !urlLike.test(target)) continue;
    const path = target.split('#')[0];
    if (target.startsWith('/docs') && pages.has(path)) continue;
    broken.push(`${where}: ${target}`);
  }
}

function walk(node, where) {
  if (Array.isArray(node)) {
    for (const item of node) walk(item, where);
    return;
  }
  if (node === null || typeof node !== 'object') return;
  const here = typeof node.path === 'string' ? `reference ${node.path}` : where;
  if (typeof node.description === 'string') checkMarkdown(here, node.description);
  if (node.kind === 'text' && typeof node.value === 'string') checkMarkdown(here, node.value);
  for (const value of Object.values(node)) walk(value, here);
}
walk(JSON.parse(readFileSync(reference, 'utf8')), 'reference');

if (broken.length > 0) {
  console.error(`Broken links:\n${broken.join('\n')}`);
  process.exit(1);
}
