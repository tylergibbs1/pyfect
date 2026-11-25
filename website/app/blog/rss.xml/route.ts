import { getPosts } from '@/lib/blog';
import { rssFeed } from '@/lib/rss';

export const revalidate = false;
export const dynamic = 'force-static';

export function GET() {
  const feed = rssFeed(
    getPosts().map((post) => ({
      title: post.data.title,
      description: post.data.description,
      path: post.url,
      date: post.data.date,
      author: post.data.author,
      tags: post.data.tags,
    })),
  );
  return new Response(feed, { headers: { 'Content-Type': 'application/rss+xml; charset=utf-8' } });
}
