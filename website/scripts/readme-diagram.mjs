// Draws assets/how-it-works.mmd with pele for the README, once per GitHub theme
// (how-it-works-light.svg, how-it-works-dark.svg; the README picks one with <picture>).
// GitHub shows each as an image, so it carries its own colors instead of the site's
// CSS variables. `--check` fails when a committed SVG is out of date with its source.
import { readFileSync, writeFileSync } from 'node:fs';
import { render } from 'pele';

const root = new URL('../../assets/', import.meta.url);
const source = readFileSync(new URL('how-it-works.mmd', root), 'utf8');

const light = {
  bg: '#ffffff', fg: '#0a0a0a', muted: '#737373', line: '#a3a3a3',
  surface: '#fafafa', 'surface-alt': '#f5f5f5', border: '#e5e5e5', accent: '#0a0a0a',
};
const dark = {
  bg: '#0d1117', fg: '#fafafa', muted: '#a3a3a3', line: '#737373',
  surface: '#161b22', 'surface-alt': '#21262d', border: '#30363d', accent: '#fafafa',
};
const vars = (colors) =>
  Object.entries(colors).map(([k, v]) => `--pele-${k}:${v};`).join('') +
  '--pele-fg-on-light:#000;--pele-fg-on-dark:#fff;--pele-radius:6px;' +
  '--pele-font:ui-sans-serif,-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;' +
  '--pele-font-mono:ui-monospace,SFMono-Regular,Menlo,monospace;';

const { svg } = render(source, {
  maxWidth: 830,
  idPrefix: 'readme-how-it-works',
  fontFamily: 'ui-sans-serif, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif',
  fontSize: 14,
});

let stale = false;
for (const [theme, colors] of Object.entries({ light, dark })) {
  const out = new URL(`how-it-works-${theme}.svg`, root);
  const result = svg.replace(/(<svg[^>]*>)/, `$1<style>svg{${vars(colors)}}</style>`) + '\n';
  if (!process.argv.includes('--check')) writeFileSync(out, result);
  else if (readFileSync(out, 'utf8') !== result) stale = true;
}
if (stale) {
  console.error('The README diagram is out of date: run `bun run diagram:readme`');
  process.exit(1);
}
