# pyfect docs

Next.js + [Fumadocs](https://fumadocs.dev). Guides are in `content/docs`, the API reference is
generated from the Python sources, and every Python example is a file in `snippets/`.

## Run locally

```sh
cd website
bun install
bun run dev          # regenerates the API reference first (needs uv), then http://localhost:3000
```

## Build

```sh
bun run generate:api # writes .generated/pyfect.json from ../src with uv (gitignored)
bun run build        # next build: needs the JSON, never runs Python; then checks /docs links
bun run check:layout # the same frame on every page, no layout shift (uses Google Chrome)
```

## Deploy to Vercel

The build reads the generated JSON but does not run Python, so generate it first, then build
and deploy the output:

```sh
cd website
bun run generate:api
npx vercel build     # after `vercel link` / `vercel pull` once
npx vercel deploy --prebuilt
```

Every route is static (search uses a prebuilt index), so any static host works too.

## How the pieces fit

- `scripts/generate_api.py` runs fumadocs-python's parser (`fumapy`) over `pyfect` with the
  project's uv environment. Unlike `fumapy-generate`, it documents objects defined in private
  `_` modules where they are exported, leaves private modules and members out, includes the
  methods classes inherit from pyfect's mixins, and serves a class whose name differs from a
  module's only by case (`Effect` and `effect`) at `Effect-class`, so the pages are distinct
  files on macOS.
- `lib/source.ts` combines the MDX guides and the generated reference into one source.
  `lib/reference-headings.ts` turns a module page's tabs into sections and gives every
  function a heading; `components/reference.tsx` renders signatures, parameter tables and
  sources.
- The layout, components and styles follow shadcn/ui's docs (`apps/v4`, MIT): the header,
  sidebar, page frame, table of contents, code blocks, tabs and `typeset.css` are adapted
  from it, with attribution comments in each file. `components/ui/` holds its primitives.
- Guides include code with `<include>../../snippets/...</include>`. `tests/test_doc_snippets.py`
  runs every snippet, fails on an inline Python block or a snippet no guide uses, and pyright
  checks `snippets/` with the rest of the project. A snippet that prints keeps its output in
  `x.out` beside it, shown in a Code / Output tab; the test fails when it no longer matches
  (regenerate with `UPDATE_SNIPPET_OUTPUT=1 uv run pytest tests/test_doc_snippets.py`).
- Diagrams are Mermaid files in `diagrams/`, used as `<Diagram name="..." title="..." />` and
  drawn to SVG at build time by [pele](https://pele.run) (pinned to 1.12.0), once for the
  prose column and once for phones; CSS shows the one that fits and colors them from the
  theme. The snippet test fails on a missing or unused diagram.
- `bun run check:layout` (after a build) loads a guide, a guide with tabs and a diagram,
  and a reference page at 1512, 1280, 1024 and 390px, and fails if the title, description,
  body or table of contents moves between them, or if any layout shift is recorded while a
  page loads, after a client-side navigation, when the fonts arrive a second late (they are
  `display: 'optional'`, so a late font never reflows the page), or while a page's HTML
  arrives in slow chunks (the browser paints these large pages part-parsed, so nothing may be
  laid out by an element that comes later in the document). It uses the installed Google Chrome.
