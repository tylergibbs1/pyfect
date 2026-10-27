import { source } from '@/lib/source';
import { notFound } from 'next/navigation';
import { generateOGImage } from 'fumadocs-ui/og';
import { appName, getPageImageUrl } from '@/lib/shared';

export const revalidate = false;

export async function GET(_req: Request, { params }: RouteContext<'/og/docs/[...slug]'>) {
  const { slug } = await params;
  const page = source.getPage(slug.slice(0, -1));
  if (!page) notFound();

  return generateOGImage({
    title: page.data.title,
    description: page.data.description,
    site: appName,
    primaryColor: 'rgba(250, 250, 250, 0.12)',
    primaryTextColor: 'rgb(250, 250, 250)',
    icon: (
      <svg viewBox="0 0 24 24" width="48" height="48">
        <path fill="white" fillRule="evenodd" d="M4 10a8 8 0 1 1 8 8h-1v3.5A2.5 2.5 0 0 1 8.5 24h-2A2.5 2.5 0 0 1 4 21.5zM12 6.2a3.8 3.8 0 1 0 0 7.6 3.8 3.8 0 0 0 0-7.6z" />
        <circle cx="12" cy="10" r="1.6" fill="white" />
      </svg>
    ),
  });
}

export function generateStaticParams() {
  return source.getPages().map((page) => ({
    lang: page.locale,
    slug: getPageImageUrl(page).segments,
  }));
}
