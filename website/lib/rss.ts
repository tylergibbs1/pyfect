import { appName, blogRoute, siteUrl } from './shared';

export interface FeedItem {
  title: string;
  description: string;
  /** Path on the site, e.g. `/blog/effect-for-python`. */
  path: string;
  /** YYYY-MM-DD. */
  date: string;
  author: string;
  tags: string[];
}

const escapes: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' };

function xml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => escapes[c]);
}

function rfc822(date: string): string {
  return new Date(`${date}T00:00:00Z`).toUTCString();
}

/** An RSS 2.0 feed of the given items, newest first as given. */
export function rssFeed(items: FeedItem[]): string {
  const feedUrl = `${siteUrl}${blogRoute}/rss.xml`;
  const entries = items.map((item) => {
    const url = `${siteUrl}${item.path}`;
    const categories = item.tags.map((tag) => `      <category>${xml(tag)}</category>`);
    return [
      '    <item>',
      `      <title>${xml(item.title)}</title>`,
      `      <link>${url}</link>`,
      `      <guid isPermaLink="true">${url}</guid>`,
      `      <description>${xml(item.description)}</description>`,
      `      <pubDate>${rfc822(item.date)}</pubDate>`,
      `      <dc:creator>${xml(item.author)}</dc:creator>`,
      ...categories,
      '    </item>',
    ].join('\n');
  });
  const updated = items[0] ? [`    <lastBuildDate>${rfc822(items[0].date)}</lastBuildDate>`] : [];
  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:dc="http://purl.org/dc/elements/1.1/">',
    '  <channel>',
    `    <title>${appName} blog</title>`,
    `    <link>${siteUrl}${blogRoute}</link>`,
    '    <description>Posts about pyfect, the Effect port for Python.</description>',
    '    <language>en</language>',
    ...updated,
    `    <atom:link href="${feedUrl}" rel="self" type="application/rss+xml"/>`,
    ...entries,
    '  </channel>',
    '</rss>',
    '',
  ].join('\n');
}
