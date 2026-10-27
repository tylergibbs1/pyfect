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
- `lib/source.ts` combines the MDX guides and the generated reference into one source;
  `components/reference.tsx` lays reference entries out in two columns.
- Guides include code with `<include>../../snippets/...</include>`. `tests/test_doc_snippets.py`
  runs every snippet, fails on an inline Python block or a snippet no guide uses, and pyright
  checks `snippets/` with the rest of the project.
