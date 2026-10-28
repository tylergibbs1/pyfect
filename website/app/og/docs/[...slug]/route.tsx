import { source } from '@/lib/source';
import { notFound } from 'next/navigation';
import { generateOGImage } from 'fumadocs-ui/og';
import { logoSvg } from '@/components/logo';
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
      // eslint-disable-next-line @next/next/no-img-element
      <img
        width={48}
        height={48}
        alt=""
        src={`data:image/svg+xml;utf8,${encodeURIComponent(logoSvg('#fafafa'))}`}
      />
    ),
  });
}

export function generateStaticParams() {
  return source.getPages().map((page) => ({
    lang: page.locale,
    slug: getPageImageUrl(page).segments,
  }));
}
