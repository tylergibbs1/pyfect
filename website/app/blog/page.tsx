import Link from 'next/link';
import type { Metadata } from 'next';
import { PostMeta } from '@/components/post-meta';
import { getPosts } from '@/lib/blog';
import { pageMetadata } from '@/lib/metadata';
import { blogRoute, docsImageRoute } from '@/lib/shared';

export const dynamic = 'force-static';

const description =
  'Posts about pyfect, the Effect port for Python: typed errors, services and layers, structured concurrency, and how they work under pyright.';

export const metadata: Metadata = pageMetadata({
  title: 'Blog',
  description,
  path: blogRoute,
  // The docs index's image: the site's own card.
  image: `${docsImageRoute}/image.png`,
});

export default function Page() {
  const posts = getPosts();
  return (
    <div className="mx-auto flex w-full max-w-160 flex-col gap-10 px-4 py-6 md:px-0 lg:py-8">
      <div className="flex flex-col gap-2 pt-(--top-spacing)">
        <h1 className="scroll-m-24 text-3xl font-semibold tracking-tight">Blog</h1>
        <p className="text-[1.05rem] text-muted-foreground sm:text-base">{description}</p>
      </div>
      <ol className="flex flex-col">
        {posts.map((post) => (
          <li key={post.url} className="border-t py-6 first:border-t-0 first:pt-0">
            <article className="flex flex-col gap-2">
              <h2 className="text-xl font-semibold tracking-tight">
                <Link href={post.url} className="underline-offset-4 hover:underline">
                  {post.data.title}
                </Link>
              </h2>
              <PostMeta date={post.data.date} tags={post.data.tags} />
              <p className="text-muted-foreground">{post.data.description}</p>
            </article>
          </li>
        ))}
      </ol>
    </div>
  );
}
