import { execFileSync } from 'node:child_process';
import type { MetadataRoute } from 'next';
import { getPosts } from '@/lib/blog';
import { source } from '@/lib/source';
import { blogRoute, siteUrl } from '@/lib/shared';

export const dynamic = 'force-static';

/**
 * Whether the checkout has its whole history. A guide's lastModified is the last commit that
 * changed it, and in a shallow clone (CI's, Vercel's) every guide older than the clone looks
 * changed by its oldest commit: a wrong date is worse than none, so those are left out.
 */
function fullHistory(): boolean {
  try {
    return execFileSync('git', ['rev-parse', '--is-shallow-repository'], { encoding: 'utf8' }).trim() === 'false';
  } catch {
    return false; // no git, or not a checkout: no history to read dates from
  }
}

export default function sitemap(): MetadataRoute.Sitemap {
  const dated = fullHistory();
  const docs = source.getPages().map((page) => {
    const lastModified = dated && 'lastModified' in page.data ? page.data.lastModified : undefined;
    return { url: `${siteUrl}${page.url}`, ...(lastModified ? { lastModified } : {}) };
  });
  const posts = getPosts().map((post) => ({ url: `${siteUrl}${post.url}`, lastModified: post.data.date }));
  const newest = posts[0]?.lastModified;
  return [
    ...docs,
    { url: `${siteUrl}${blogRoute}`, ...(newest ? { lastModified: newest } : {}) },
    ...posts,
  ];
}
