// `next build` reads the API reference JSON but never runs Python, so hosts without
// uv (Vercel, `vercel build`) can build once the JSON exists. Fail early, clearly.
import { existsSync } from 'node:fs';

const file = new URL('../.generated/pyfect.json', import.meta.url);
if (!existsSync(file)) {
  console.error(
    'Missing .generated/pyfect.json: run `bun run generate:api` (needs uv) before building.',
  );
  process.exit(1);
}
