import { notFound } from 'next/navigation';
import { ogImage } from '@/components/og-image';
import { blogSource } from '@/lib/blog';
import { appName } from '@/lib/shared';

export const revalidate = false;

export async function GET(_req: Request, { params }: RouteContext<'/og/blog/[slug]/image.png'>) {
  const { slug } = await params;
  const post = blogSource.getPage([slug]);
  if (!post) notFound();

  return ogImage({ title: post.data.title, description: post.data.description, site: `${appName} blog` });
}

export function generateStaticParams() {
  return blogSource.getPages().map((post) => ({ slug: post.slugs[0] }));
}
