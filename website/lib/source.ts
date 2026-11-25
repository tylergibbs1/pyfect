import { llms, loader } from 'fumadocs-core/source';
import { lucideIconsPlugin } from 'fumadocs-core/source/lucide-icons';
import { docsRoute } from './shared';
import { defineDocs } from 'fumadocs-mdx/macro';
import { metaSchema, pageSchema } from 'fumadocs-core/source/schema';
import { createPython } from 'fumadocs-python';
import { codeThemes } from './code-theme';
import { searchDescription } from './frontmatter';
import { mdxOptions } from './mdx-options';
import { remarkReferenceHeadings } from './reference-headings';
import { rehypeTableColumns } from './table-columns';
import { navSections, type NavSection } from './page-tree';

const docs = defineDocs({
  dir: 'content/docs',
  docs: {
    // A guide's description is its meta description: one search engines show in full.
    schema: pageSchema.extend({ description: searchDescription }),
    mdxOptions,
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
  rehypePlugins: [rehypeTableColumns],
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

/**
 * The sidebar's, mobile menu's and command menu's links. Client components get these, never
 * the page tree: the tree holds every API reference page, and as a prop it was serialized
 * into every page (1.3 MB each, and most of the build's time).
 */
export const docsNav: NavSection[] = navSections(source.getPageTree());

export const docsLlms = llms(source, {
  renderPage: async (page) => {
    const header = `# ${page.data.title} (${page.url})`;
    if ('getText' in page.data) {
      return `${header}\n\n${await page.data.getText('processed')}`;
    }
    return header;
  },
});
