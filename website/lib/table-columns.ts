import type { Element, ElementContent, Root, RootContent } from 'hast';

/**
 * Gives every Markdown table its column widths at build time, so a page painted while its HTML
 * streams in never resizes a column when a longer row arrives.
 *
 * The widths are the browser's own auto table layout, worked out from the cells' text: each column
 * gets its min-content width (its header, which never wraps, or its longest word) and shares the
 * rest of the width in proportion to how much wider its content gets unwrapped. That is linear in
 * the table's width, so it is one CSS length per column, in `em` (the text) plus `cqi` (the scroll
 * wrapper, a size container). Narrower than every column's minimum, the table keeps that minimum
 * and scrolls. The last column takes whatever is left.
 */

/** Advance widths in em of printable ASCII (from " "), Geist 400 and 500 as measured in Chrome;
 * digits are tabular in tables, so each is the widest digit. Geist Mono is 0.6em throughout. */
// prettier-ignore
const SANS = [0.25,0.213,0.346,0.478,0.629,0.802,0.62,0.178,0.274,0.274,0.43,0.558,0.201,0.419,0.201,0.48,0.663,0.663,0.663,0.663,0.663,0.663,0.663,0.663,0.663,0.663,0.297,0.297,0.544,0.54,0.544,0.559,0.906,0.668,0.68,0.703,0.694,0.603,0.59,0.7,0.713,0.27,0.597,0.64,0.58,0.877,0.743,0.739,0.65,0.733,0.672,0.64,0.552,0.689,0.667,0.945,0.606,0.576,0.544,0.347,0.455,0.347,0.426,0.557,0.248,0.551,0.595,0.546,0.595,0.561,0.395,0.594,0.581,0.244,0.26,0.59,0.267,0.877,0.581,0.573,0.595,0.595,0.379,0.52,0.392,0.575,0.536,0.819,0.585,0.537,0.537,0.389,0.264,0.389,0.523];
// prettier-ignore
const MEDIUM = [0.243,0.228,0.361,0.515,0.643,0.81,0.649,0.186,0.29,0.29,0.427,0.562,0.213,0.418,0.213,0.494,0.673,0.673,0.673,0.673,0.673,0.673,0.673,0.673,0.673,0.673,0.302,0.302,0.546,0.544,0.546,0.57,0.925,0.689,0.688,0.713,0.701,0.609,0.595,0.713,0.716,0.28,0.607,0.656,0.583,0.89,0.745,0.751,0.657,0.745,0.68,0.654,0.568,0.694,0.688,0.968,0.633,0.594,0.561,0.361,0.47,0.361,0.438,0.558,0.258,0.565,0.608,0.563,0.608,0.576,0.412,0.607,0.591,0.256,0.284,0.609,0.282,0.885,0.591,0.588,0.608,0.608,0.394,0.537,0.41,0.586,0.56,0.829,0.607,0.553,0.552,0.395,0.274,0.395,0.523];
/** Inline code (typeset.css): 0.85em Geist Mono with 0.3em of padding each side. */
const CODE_SIZE = 0.85;
const CODE_CHAR = 0.6 * CODE_SIZE;
const CODE_PADDING = 2 * 0.3 * CODE_SIZE;
/** A cell's padding (typeset.css): 1em each side, none before the first column. */
const PADDING = 2;
/** Kerning and fonts that miss the table: a word measured short would overflow its column. */
const SLACK = 1.04;

type Run = { text: string; font: 'sans' | 'medium' | 'mono' };

function charWidth(ch: string, font: Run['font']): number {
  if (font === 'mono') return CODE_CHAR;
  const i = ch.charCodeAt(0) - 32;
  const table = font === 'medium' ? MEDIUM : SANS;
  return table[i] ?? 0.6;
}

function runs(node: ElementContent | Element, font: Run['font'], out: Run[]): Run[] {
  if (node.type === 'text') out.push({ text: node.value.replace(/\s+/g, ' '), font });
  if (node.type !== 'element') return out;
  if (node.tagName === 'code') {
    // the padding is part of the code's first and last word
    out.push({ text: '\u0001', font: 'mono' });
    for (const child of node.children) runs(child, 'mono', out);
    out.push({ text: '\u0001', font: 'mono' });
    return out;
  }
  const inner = font === 'sans' && (node.tagName === 'strong' || node.tagName === 'th') ? 'medium' : font;
  for (const child of node.children) runs(child, inner, out);
  return out;
}

/** A cell's width on one line, and its widest word (where it can wrap), in em. */
export function measureCell(cell: Element): { full: number; word: number } {
  const font = cell.tagName === 'th' ? 'medium' : 'sans';
  let full = 0;
  let word = 0;
  let current = 0;
  for (const run of runs(cell, font, [])) {
    for (const ch of run.text) {
      if (ch === '\u0001') {
        current += CODE_PADDING / 2;
        full += CODE_PADDING / 2;
        continue;
      }
      const w = charWidth(ch, run.font);
      full += w;
      if (ch === ' ') {
        word = Math.max(word, current);
        current = 0;
      } else {
        current += w;
      }
    }
  }
  word = Math.max(word, current);
  // a header never wraps (typeset.css)
  return cell.tagName === 'th' ? { full: full * SLACK, word: full * SLACK } : { full: full * SLACK, word: word * SLACK };
}

const round = (n: number) => Math.round(n * 1000) / 1000;

/** Each column's width as a CSS length, all but the last, and the table's minimum width. */
export function columnWidths(rows: Element[][]): { widths: string[]; minWidth: string } {
  const count = Math.max(...rows.map((r) => r.length));
  const min = Array<number>(count).fill(0);
  const max = Array<number>(count).fill(0);
  for (const row of rows) {
    row.forEach((cell, i) => {
      const { full, word } = measureCell(cell);
      min[i] = Math.max(min[i], word);
      max[i] = Math.max(max[i], full);
    });
  }
  for (let i = 0; i < count; i++) {
    const padding = i === 0 ? PADDING / 2 : PADDING;
    min[i] += padding;
    max[i] += padding;
  }
  const sumMin = min.reduce((a, b) => a + b, 0);
  const slack = max.map((m, i) => m - min[i]);
  const sumSlack = slack.reduce((a, b) => a + b, 0);
  const sumMax = max.reduce((a, b) => a + b, 0);
  // nothing wraps anywhere: share the room as the browser does, by content width
  const share = sumSlack > 0 ? slack.map((s) => s / sumSlack) : max.map((m) => m / sumMax);
  const widths = min.slice(0, -1).map((m, i) => {
    const percent = round(100 * share[i]);
    if (percent === 0) return `${round(m)}em`;
    return `max(${round(m)}em, calc(${round(m - sumMin * share[i])}em + ${percent}cqi))`;
  });
  return { widths, minWidth: `${round(sumMin)}em` };
}

function cellsOf(node: Element): Element[][] {
  const rows: Element[][] = [];
  const walk = (n: Element) => {
    for (const child of n.children) {
      if (child.type !== 'element') continue;
      if (child.tagName === 'tr') {
        rows.push(child.children.filter((c): c is Element => c.type === 'element' && /^t[hd]$/.test(c.tagName)));
      } else if (child.tagName !== 'table') {
        walk(child);
      }
    }
  };
  walk(node);
  return rows;
}

function visit(node: Root | RootContent | ElementContent, fn: (el: Element) => void) {
  if (node.type === 'element') fn(node);
  if ('children' in node) for (const child of node.children) visit(child, fn);
}

/** The rehype plugin: a `<colgroup>` and a minimum width on every table. */
export function rehypeTableColumns() {
  return (tree: Root) => {
    visit(tree, (table) => {
      if (table.tagName !== 'table') return;
      const rows = cellsOf(table);
      if (rows.length === 0) return;
      const { widths, minWidth } = columnWidths(rows);
      const count = Math.max(...rows.map((r) => r.length));
      const cols: Element[] = Array.from({ length: count }, (_, i) => ({
        type: 'element',
        tagName: 'col',
        properties: i < widths.length ? { style: `width: ${widths[i]}` } : {},
        children: [],
      }));
      table.children.unshift({ type: 'element', tagName: 'colgroup', properties: {}, children: cols });
      table.properties = { ...table.properties, style: `min-width: ${minWidth}`, dataColumns: '' };
    });
  };
}
