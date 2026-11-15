// A typical docs page stays small. Anything a client component takes as a prop is serialized
// into every prerendered page: the sidebar once took the whole page tree, every API reference
// page in it, which made each of the ~2800 pages 1.3 MB larger and the build ten minutes
// longer. Pass client components what they show (lib/page-tree.ts's NavSection), not the tree.
import { readdirSync, statSync } from 'node:fs';
import { join, sep } from 'node:path';

const BUDGET_KB = 512;
const next = new URL('../.next/', import.meta.url).pathname;
const sizes = readdirSync(next, { recursive: true })
  .map(String)
  .filter((path) => path.endsWith('.html') && path.split(sep).includes('docs'))
  .map((path) => statSync(join(next, path)).size)
  .sort((a, b) => a - b);
if (sizes.length === 0) {
  console.error('No prerendered docs pages under .next: did the docs pages stop being static?');
  process.exit(1);
}
const median = sizes[Math.floor(sizes.length / 2)] / 1024;
if (median > BUDGET_KB) {
  console.error(
    `The median docs page is ${median.toFixed(0)} KB, over its ${BUDGET_KB} KB budget. ` +
      'Look for a large prop passed to a client component (it is serialized into every page).',
  );
  process.exit(1);
}
console.log(`Median docs page: ${median.toFixed(0)} KB of HTML (budget ${BUDGET_KB} KB, ${sizes.length} pages).`);
