// `next build` reads the API reference JSON but never runs Python, so hosts without
// uv (Vercel, `vercel build`) can build once the JSON exists. Fail early, clearly.
import { existsSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const file = new URL('../.generated/pyfect.json', import.meta.url);
if (!existsSync(file)) {
  console.error(
    'Missing .generated/pyfect.json: run `bun run generate:api` (needs uv) before building.',
  );
  process.exit(1);
}

// A stale reference would lack the modules added since, which check-links then reports as
// broken guide links: name the real cause.
const generated = statSync(file).mtimeMs;
const source = fileURLToPath(new URL('../../src/pyfect/', import.meta.url));
if (existsSync(source)) {
  const newer = readdirSync(source, { recursive: true })
    .map(String)
    .find((path) => path.endsWith('.py') && statSync(source + path).mtimeMs > generated);
  if (newer) {
    console.error(
      `.generated/pyfect.json is older than src/pyfect/${newer}: run \`bun run generate:api\` before building.`,
    );
    process.exit(1);
  }
}
