import Link from 'next/link';
import { notFound } from 'next/navigation';
import type { Metadata } from 'next';
import { ArrowLeft } from 'lucide-react';
import { JsonLd } from '@/components/json-ld';
import { PostMeta } from '@/components/post-meta';
import { Button } from '@/components/ui/button';
import { blogSource, type Post } from '@/lib/blog';
import { pageMetadata } from '@/lib/metadata';
import { appName, blogRoute, getPostImageUrl, siteUrl } from '@/lib/shared';
import { mdxComponents } from '@/mdx-components';

export const revalidate = false;
export const dynamic = 'force-static';
export const dynamicParams = false;

function getPost(slug: string): Post {
  const post = blogSource.getPage([slug]);
  if (!post) notFound();
  return post;
}

export default async function Page(props: PageProps<'/blog/[slug]'>) {
  const { slug } = await props.params;
  const post = getPost(slug);
  const MDX = post.data.body;

  return (
    <article className="mx-auto flex w-full max-w-160 min-w-0 flex-col gap-6 px-4 py-6 text-[1.05rem] sm:text-[15px] md:px-0 lg:py-8">
      <JsonLd data={postJsonLd(post)} />
      <div className="flex flex-col gap-3 pt-(--top-spacing)">
        <Button variant="ghost" size="sm" className="-ml-2.5 self-start text-muted-foreground" asChild>
          <Link href={blogRoute}>
            <ArrowLeft /> All posts
          </Link>
        </Button>
        <h1 className="scroll-m-24 text-3xl font-semibold tracking-tight text-balance">{post.data.title}</h1>
        <p className="text-[1.05rem] text-muted-foreground sm:text-base sm:text-balance">{post.data.description}</p>
        <PostMeta date={post.data.date} author={post.data.author} tags={post.data.tags} />
      </div>
      <div className="typeset w-full pb-16">
        <MDX components={mdxComponents} />
      </div>
    </article>
  );
}

function postJsonLd(post: Post) {
  const url = `${siteUrl}${post.url}`;
  return {
    '@context': 'https://schema.org',
    '@type': 'BlogPosting',
    headline: post.data.title,
    description: post.data.description,
    datePublished: post.data.date,
    author: { '@type': 'Person', name: post.data.author },
    publisher: { '@type': 'Organization', name: appName, url: siteUrl },
    keywords: post.data.tags.join(', '),
    image: `${siteUrl}${getPostImageUrl(post).url}`,
    url,
    mainEntityOfPage: { '@type': 'WebPage', '@id': url },
  };
}

export function generateStaticParams() {
  return blogSource.getPages().map((post) => ({ slug: post.slugs[0] }));
}

export async function generateMetadata(props: PageProps<'/blog/[slug]'>): Promise<Metadata> {
  const { slug } = await props.params;
  const post = getPost(slug);
  return pageMetadata({
    title: post.data.title,
    description: post.data.description,
    path: post.url,
    image: getPostImageUrl(post).url,
    article: { published: post.data.date, authors: [post.data.author], tags: post.data.tags },
  });
}
