import { llms, loader } from 'fumadocs-core/source';
import { lucideIconsPlugin } from 'fumadocs-core/source/lucide-icons';
import { docsRoute } from './shared';
import { defineDocs } from 'fumadocs-mdx/macro';
import { applyMdxPreset } from 'fumadocs-mdx/config';
import { metaSchema, pageSchema } from 'fumadocs-core/source/schema';
import { createPython } from 'fumadocs-python';
import { codeThemes } from './code-theme';
import { remarkReferenceHeadings } from './reference-headings';

const docs = defineDocs({
  dir: 'content/docs',
  docs: {
    schema: pageSchema,
    mdxOptions: applyMdxPreset({ rehypeCodeOptions: { themes: codeThemes } }),
    postprocess: {
      includeProcessedMarkdown: true,
    },
  },
  meta: {
    schema: metaSchema,
  },
});

// Written by `bun run generate:api` (scripts/generate_api.py) from the Python sources.
const python = createPython({
  file: './.generated/pyfect.json',
  groupBy: 'none',
  remarkPlugins: [remarkReferenceHeadings],
  rehypeCodeOptions: { themes: codeThemes },
});

// See https://fumadocs.dev/docs/headless/source-api for more info
export const source = loader(
  {
    docs: docs.toFumadocsSource(),
    reference: await python.staticSource({ baseDir: 'reference' }),
  },
  {
    baseUrl: docsRoute,
    plugins: [lucideIconsPlugin(), python.loaderPlugin()],
  },
);

export type Page = NonNullable<ReturnType<typeof source.getPage>>;

export const docsLlms = llms(source, {
  renderPage: async (page) => {
    const header = `# ${page.data.title} (${page.url})`;
    if ('getText' in page.data) {
      return `${header}\n\n${await page.data.getText('processed')}`;
    }
    return header;
  },
});
