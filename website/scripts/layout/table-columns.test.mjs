// lib/table-columns.ts: a table's column widths, fixed at build time from all of its rows, as the
// browser's auto layout would lay them out once every row had arrived. `bun run test:layout`.
import { describe, expect, test } from 'bun:test';
import { columnWidths, measureCell, rehypeTableColumns } from '../../lib/table-columns.ts';

const text = (value) => ({ type: 'text', value });
const code = (value) => ({ type: 'element', tagName: 'code', properties: {}, children: [text(value)] });
const cell = (tagName, ...children) => ({
  type: 'element',
  tagName,
  properties: {},
  children: children.map((c) => (typeof c === 'string' ? text(c) : c)),
});
const row = (tagName, cells) => cells.map((c) => (Array.isArray(c) ? cell(tagName, ...c) : cell(tagName, c)));

// /docs/http-server's table, whose first column widened as its longest row streamed in
const HEAD = row('th', ['Failure', 'Status']);
const BODY = [
  row('td', [[code('SchemaError'), " (a request that doesn't decode)"], '400']),
  row('td', [[code('HttpServerError'), ' with a ', code('RequestParseError'), ": a body that can't be read, or isn't valid JSON"], '400']),
  row('td', ['the same past ', '413']),
];

/** The width in px of a CSS length from columnWidths, at font size `em` and container width `w`. */
function px(length, em, w) {
  const value = (s) => {
    const max = s.match(/^max\((.*), calc\((.*)em \+ (.*)cqi\)\)$/);
    if (max) return Math.max(value(max[1]), Number(max[2]) * em + (Number(max[3]) * w) / 100);
    return Number(s.replace(/em$/, '')) * em;
  };
  return value(length);
}

/** Every column's width in px as Chrome's fixed layout gives them: the last takes what is left. */
function layout(rows, em, w) {
  const { widths, minWidth } = columnWidths(rows);
  const table = Math.max(w, px(minWidth, em, w));
  const fixed = widths.map((l) => px(l, em, w));
  return [...fixed, table - fixed.reduce((a, b) => a + b, 0)];
}

describe('columnWidths', () => {
  test('come from every row, not the first ones', () => {
    expect(columnWidths([HEAD, ...BODY])).not.toEqual(columnWidths([HEAD, BODY[2]]));
  });

  test('fill the wrapper exactly when it is wider than the minimum', () => {
    for (const w of [480, 640, 900]) {
      const cols = layout([HEAD, ...BODY], 16, w);
      expect(cols.reduce((a, b) => a + b, 0)).toBeCloseTo(w, 1);
    }
  });

  test('never narrow a column below its header or its longest word: a narrow screen scrolls', () => {
    const rows = [HEAD, ...BODY];
    for (const w of [120, 327, 640]) {
      const cols = layout(rows, 18, w);
      rows.forEach((r) =>
        r.forEach((c, i) => {
          const padding = i === 0 ? 1 : 2;
          expect(cols[i]).toBeGreaterThanOrEqual((measureCell(c).word + padding) * 18 - 0.01);
        }),
      );
    }
    expect(layout(rows, 18, 120).reduce((a, b) => a + b, 0)).toBeGreaterThan(120);
  });

  test('give the room to the column whose text wraps, not to a short one', () => {
    const [failure, status] = layout([HEAD, ...BODY], 16, 640);
    expect(status).toBeCloseTo((measureCell(HEAD[1]).word + 2) * 16, 1);
    expect(failure).toBeGreaterThan(500);
  });

  test('a header never wraps', () => {
    expect(measureCell(cell('th', 'What happens to a failure')).word).toBe(
      measureCell(cell('th', 'What happens to a failure')).full,
    );
  });
});

test('the plugin gives every table a colgroup and a minimum width', () => {
  const table = {
    type: 'element',
    tagName: 'table',
    properties: {},
    children: [
      { type: 'element', tagName: 'thead', properties: {}, children: [{ type: 'element', tagName: 'tr', properties: {}, children: HEAD }] },
      { type: 'element', tagName: 'tbody', properties: {}, children: BODY.map((r) => ({ type: 'element', tagName: 'tr', properties: {}, children: r })) },
    ],
  };
  rehypeTableColumns()({ type: 'root', children: [table] });
  const [colgroup] = table.children;
  expect(colgroup.tagName).toBe('colgroup');
  expect(colgroup.children.map((c) => c.properties.style ?? null)).toEqual([
    `width: ${columnWidths([HEAD, ...BODY]).widths[0]}`,
    null,
  ]);
  expect(table.properties.style).toMatch(/^min-width: [\d.]+em$/);
});
