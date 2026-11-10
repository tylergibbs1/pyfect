import { source } from '@/lib/source';
import { createFromSource } from 'fumadocs-core/search/server';
import type { StructuredData } from 'fumadocs-core/mdx-plugins';

type Page = ReturnType<typeof source.getPages>[number];

async function structuredData(page: Page): Promise<StructuredData> {
  const data = page.data as {
    structuredData?: StructuredData | (() => Promise<StructuredData>);
    load?: () => Promise<{ structuredData: StructuredData }>;
  };
  if (typeof data.structuredData === 'function') return data.structuredData();
  if (data.structuredData) return data.structuredData;
  if (data.load) return (await data.load()).structuredData;
  throw new Error(`No structured data to index for ${page.url}`);
}

// The API reference is thousands of pages: index each by its name, description and summary
// line. Its full text made the static index too large to serve (scripts/check-search-size.mjs).
async function buildIndex(page: Page) {
  const data = await structuredData(page);
  const reference = page.url.startsWith('/docs/reference');
  return {
    id: page.url,
    url: page.url,
    title: page.data.title ?? page.url,
    description: page.data.description,
    structuredData: reference ? { headings: [], contents: data.contents.slice(0, 1) } : data,
  };
}

// Built once at build time and served as a static file (see components/command-menu.tsx).
export const revalidate = false;
export const { staticGET: GET } = createFromSource(source, { buildIndex });
