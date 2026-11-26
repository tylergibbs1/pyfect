import type { MetadataRoute } from 'next';
import { getPosts } from '@/lib/blog';
import pageDates from '@/lib/page-dates.json';
import { source } from '@/lib/source';
import { blogRoute, siteUrl } from '@/lib/shared';

export const dynamic = 'force-static';

const guideDates: Record<string, { date: string } | undefined> = pageDates;

/**
 * A guide's lastModified is the day its content last changed, from `lib/page-dates.json`
 * (`scripts/page_dates.py` keeps it; `tests/test_page_dates.py` fails when it is stale). An
 * undated guide fails the build rather than going out without a date.
 *
 * API reference pages have no lastModified: each is generated from the Python sources, and no
 * record says when a module's documented surface last changed, so any date would be a guess.
 */
function guideDate(slugs: string[]): string {
  const entry = guideDates[slugs.join('/')];
  if (!entry) throw new Error(`No date for /docs/${slugs.join('/')}: run website/scripts/page_dates.py`);
  return entry.date;
}

export default function sitemap(): MetadataRoute.Sitemap {
  const docs = source.getPages().map((page) => {
    const url = `${siteUrl}${page.url}`;
    return page.slugs[0] === 'reference' ? { url } : { url, lastModified: guideDate(page.slugs) };
  });
  const posts = getPosts().map((post) => ({ url: `${siteUrl}${post.url}`, lastModified: post.data.date }));
  const newest = posts[0]?.lastModified;
  return [
    ...docs,
    { url: `${siteUrl}${blogRoute}`, ...(newest ? { lastModified: newest } : {}) },
    ...posts,
  ];
}
