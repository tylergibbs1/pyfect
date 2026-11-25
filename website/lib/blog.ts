import { loader } from 'fumadocs-core/source';
import { defineCollections } from 'fumadocs-mdx/macro';
import { z } from 'zod';
import { mdxOptions } from './mdx-options';
import { blogRoute } from './shared';

/**
 * A post's frontmatter, checked when the site builds: a post with a missing field, a date
 * that isn't YYYY-MM-DD, or a description search engines would cut short fails the build.
 */
const postSchema = z.object({
  title: z.string().min(1),
  // Google shows about 155 characters of a meta description.
  description: z.string().min(120).max(160),
  date: z.iso.date(),
  author: z.string().min(1),
  tags: z.array(z.string().min(1)),
});

const posts = defineCollections({
  type: 'doc',
  dir: 'content/blog',
  schema: postSchema,
  mdxOptions,
});

export const blogSource = loader({ baseUrl: blogRoute, source: posts.toFumadocsSource() });

export type Post = NonNullable<ReturnType<typeof blogSource.getPage>>;

/** Every post, newest first (by date, then by title). */
export function getPosts(): Post[] {
  return blogSource
    .getPages()
    .toSorted((a, b) => b.data.date.localeCompare(a.data.date) || a.data.title.localeCompare(b.data.title));
}

/** A post's date as readers see it, e.g. "November 24, 2026" (the date itself, in UTC). */
export function formatDate(date: string): string {
  return new Date(`${date}T00:00:00Z`).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    timeZone: 'UTC',
  });
}
