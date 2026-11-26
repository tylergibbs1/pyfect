// The search index is one prerendered response, and Vercel refuses one over 20 MB
// (FALLBACK_BODY_TOO_LARGE). Fail well before that, while there is room to choose what to drop.
import { statSync } from 'node:fs';
import { prerenderedBody } from './prerendered.mjs';

const BUDGET_MB = 12;
const body = prerenderedBody('api/search');
if (!body) {
  console.error('No prerendered api/search.body under .next: did the search route stop being static?');
  process.exit(1);
}
const mb = statSync(body).size / 1e6;
if (mb > BUDGET_MB) {
  console.error(
    `The search index is ${mb.toFixed(2)} MB, over its ${BUDGET_MB} MB budget (Vercel's limit is 20 MB). ` +
      'Index less per page in app/api/search/route.ts.',
  );
  process.exit(1);
}
console.log(`Search index: ${mb.toFixed(2)} MB (budget ${BUDGET_MB} MB).`);
