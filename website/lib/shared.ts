import { createGetUrl } from 'fumadocs-core/source';

export const appName = 'pyfect';
export const docsRoute = '/docs';
export const docsImageRoute = '/og/docs';
export const docsContentRoute = '/llms.mdx/docs';

export const gitConfig = {
  user: 'tylergibbs1',
  repo: 'pyfect',
  branch: 'main',
};

const getContentUrl = createGetUrl(docsContentRoute);

export function getPageMarkdownUrl(page: { slugs: string[]; locale?: string }) {
  const segments = [...page.slugs, 'content.md'];

  return { segments, url: getContentUrl(segments, page.locale) };
}

const getImageUrl = createGetUrl(docsImageRoute);

export function getPageImageUrl(page: { slugs: string[]; locale?: string }) {
  const segments = [...page.slugs, 'image.png'];

  return { segments, url: getImageUrl(segments, page.locale) };
}

export const githubUrl = `https://github.com/${gitConfig.user}/${gitConfig.repo}`;

export const navItems = [
  { href: '/docs', label: 'Docs' },
  { href: '/docs/reference', label: 'API reference' },
];
