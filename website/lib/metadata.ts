import type { Metadata } from 'next';
import { appName, blogRoute } from './shared';

export interface PageMeta {
  /** The page's own title; the root layout's template adds " - pyfect". */
  title: string | { absolute: string };
  description: string;
  /** The page's path, e.g. `/docs/errors`: its canonical URL. */
  path: string;
  /** Path of its 1200×630 Open Graph image. */
  image: string;
  article?: { published: string; authors: string[]; tags: string[] };
}

/**
 * A page's `<title>`, meta description, canonical URL, Open Graph and Twitter card. Next
 * replaces a parent's `openGraph`, `twitter` and `alternates` whole rather than merging them,
 * so every page sets all three here.
 */
export function pageMetadata({ title, description, path, image, article }: PageMeta): Metadata {
  const shown = typeof title === 'string' ? title : title.absolute;
  const images = [{ url: image, width: 1200, height: 630, alt: shown }];
  return {
    title,
    description,
    alternates: {
      canonical: path,
      types: { 'application/rss+xml': [{ url: `${blogRoute}/rss.xml`, title: `${appName} blog` }] },
    },
    openGraph: {
      title: shown,
      description,
      url: path,
      siteName: appName,
      locale: 'en_US',
      images,
      ...(article
        ? { type: 'article', publishedTime: article.published, authors: article.authors, tags: article.tags }
        : { type: 'website' }),
    },
    twitter: { card: 'summary_large_image', title: shown, description, images },
  };
}
