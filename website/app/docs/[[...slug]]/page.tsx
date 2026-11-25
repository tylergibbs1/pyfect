import Link from 'next/link';
import { notFound } from 'next/navigation';
import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import { ArrowLeft, ArrowRight } from 'lucide-react';
import { findNeighbour } from 'fumadocs-core/page-tree';
import { source, type Page as SourcePage } from '@/lib/source';
import { githubUrl, getPageImageUrl, getPageMarkdownUrl, siteUrl } from '@/lib/shared';
import { pageMetadata } from '@/lib/metadata';
import { JsonLd } from '@/components/json-ld';
import { mdxComponents } from '@/mdx-components';
import { referenceComponents } from '@/components/reference';
import { DocsCopyPage } from '@/components/docs-copy-page';
import { DocsTableOfContents, type TocItem } from '@/components/docs-toc';
import { Button } from '@/components/ui/button';

// shadcn/ui's docs page (apps/v4/app/(app)/docs/[[...slug]]/page.tsx, MIT): one frame
// for every page, guides and API reference alike.

export const revalidate = false;
export const dynamic = 'force-static';
export const dynamicParams = false;

export default async function Page(props: PageProps<'/docs/[[...slug]]'>) {
  const params = await props.params;
  const page = source.getPage(params.slug);
  if (!page) notFound();

  if ('load' in page.data) {
    const rendered = await page.data.load();
    const { body, toc } = await rendered.render({ ...mdxComponents, ...referenceComponents });
    return (
      <DocsPage page={page} toc={toc} description={describe(page)}>
        {body}
      </DocsPage>
    );
  }

  const MDX = page.data.body;
  const raw = await page.data.getText('processed');
  return (
    <DocsPage
      page={page}
      toc={page.data.toc}
      copy={<DocsCopyPage page={raw} markdownUrl={getPageMarkdownUrl(page).url} />}
    >
      <MDX components={mdxComponents} />
      {page.slugs.length === 0 ? <JsonLd data={projectJsonLd(page.data.description ?? '')} /> : null}
    </DocsPage>
  );
}

/** Reference pages generated from modules without a docstring have no description of their own. */
function describe(page: SourcePage): string {
  return page.data.description ?? `API reference for ${page.data.title}.`;
}

/** The project, for search engines: on the docs index, where / redirects. */
function projectJsonLd(description: string) {
  const project = { name: 'pyfect', description, url: `${siteUrl}/docs` };
  return {
    '@context': 'https://schema.org',
    '@graph': [
      {
        '@type': 'SoftwareSourceCode',
        ...project,
        codeRepository: githubUrl,
        programmingLanguage: 'Python',
        runtimePlatform: 'Python 3.13+',
        license: 'https://opensource.org/licenses/MIT',
      },
      {
        '@type': 'SoftwareApplication',
        ...project,
        applicationCategory: 'DeveloperApplication',
        operatingSystem: 'Linux, macOS, Windows',
        offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' },
        downloadUrl: 'https://pypi.org/project/pyfect-dev/',
      },
    ],
  };
}

const FRAME_PARSED = 'docs-frame-parsed';

function DocsPage({
  page,
  toc,
  copy,
  description,
  children,
}: {
  page: SourcePage;
  toc: TocItem[];
  copy?: ReactNode;
  description?: string;
  children: ReactNode;
}) {
  const summary = description ?? page.data.description;
  const neighbours = findNeighbour(source.getPageTree(), page.url);

  return (
    // These pages are large and the browser paints them while it is still parsing them.
    // - The header's and the title row's buttons are right-aligned, so each is placed by the
    //   ones after it: a paint between two of them showed them moving when the rest arrived.
    //   So nothing renders until the title row is parsed (the `expect` link below).
    // - At xl a grid, not flex: the rail's column exists before the rail is parsed. A flex
    //   column first filled the rail's place too, so the article jumped sideways when the
    //   rail arrived.
    // - At xl the column is at least as tall as the rail: on a page shorter than the screen
    //   the rail set the row's height, so the prev / next row moved down when it arrived.
    <div
      data-slot="docs"
      className="flex scroll-mt-24 items-stretch pb-8 text-[1.05rem] sm:text-[15px] xl:grid xl:w-full xl:grid-cols-[minmax(0,1fr)_var(--sidebar-width)]"
    >
      <div className="flex min-w-0 flex-1 flex-col xl:min-h-[90svh]">
        <div className="h-(--top-spacing) shrink-0" />
        <div
          data-docs-article=""
          className="mx-auto flex w-full max-w-160 min-w-0 flex-1 flex-col gap-6 px-4 py-6 text-foreground md:px-0 lg:py-8"
        >
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between md:items-start">
              <h1 className="scroll-m-24 text-3xl font-semibold tracking-tight sm:text-3xl">{page.data.title}</h1>
              <div className="docs-nav flex items-center gap-2">
                {copy ? <div className="hidden sm:block">{copy}</div> : null}
                <div className="ml-auto flex gap-2">
                  {neighbours.previous ? (
                    <Button variant="secondary" size="icon" className="extend-touch-target size-8 shadow-none md:size-7" asChild>
                      <Link href={neighbours.previous.url}>
                        <ArrowLeft />
                        <span className="sr-only">Previous</span>
                      </Link>
                    </Button>
                  ) : null}
                  {neighbours.next ? (
                    <Button variant="secondary" size="icon" className="extend-touch-target size-8 shadow-none md:size-7" asChild>
                      <Link href={neighbours.next.url}>
                        <span className="sr-only">Next</span>
                        <ArrowRight />
                      </Link>
                    </Button>
                  ) : null}
                </div>
              </div>
            </div>
            {summary ? (
              <p className="text-[1.05rem] text-muted-foreground sm:text-base sm:text-balance md:max-w-[80%]">
                {summary}
              </p>
            ) : null}
            {/* React hoists the link into <head>: rendering waits until this span is parsed. */}
            <link rel="expect" href={`#${FRAME_PARSED}`} blocking="render" />
            <span id={FRAME_PARSED} hidden />
          </div>
          {toc.length > 0 ? (
            <div data-docs-toc-box="" className="xl:hidden">
              <DocsTableOfContents toc={toc} variant="dropdown" />
            </div>
          ) : null}
          <div className="typeset w-full flex-1 pb-16 *:data-[slot=alert]:first:mt-0 sm:pb-0">{children}</div>
          {/* Each link takes at most half the row, so two long names never overflow it and the
              right one stays right-aligned while its name streams in. */}
          <div className="hidden h-16 w-full items-center gap-2 px-4 sm:flex sm:px-0">
            {neighbours.previous ? (
              <Button variant="secondary" size="sm" asChild className="max-w-[calc(50%-0.25rem)] shadow-none">
                <Link href={neighbours.previous.url}>
                  <ArrowLeft /> <span className="min-w-0 truncate">{neighbours.previous.name}</span>
                </Link>
              </Button>
            ) : null}
            {neighbours.next ? (
              <Button variant="secondary" size="sm" className="ml-auto max-w-[calc(50%-0.25rem)] shadow-none" asChild>
                <Link href={neighbours.next.url}>
                  <span className="min-w-0 truncate">{neighbours.next.name}</span> <ArrowRight />
                </Link>
              </Button>
            ) : null}
          </div>
        </div>
      </div>
      <div
        data-docs-toc-rail=""
        className="sticky top-[calc(var(--header-height)+1px)] z-30 hidden h-[90svh] w-(--sidebar-width) flex-col gap-4 overflow-hidden overscroll-none pb-8 xl:flex"
      >
        <div className="h-(--top-spacing) shrink-0" />
        {toc.length > 0 ? (
          <div className="no-scrollbar flex flex-col gap-8 overflow-y-auto px-8">
            <DocsTableOfContents toc={toc} />
          </div>
        ) : null}
      </div>
    </div>
  );
}

export async function generateStaticParams() {
  return source.generateParams();
}

export async function generateMetadata(props: PageProps<'/docs/[[...slug]]'>): Promise<Metadata> {
  const params = await props.params;
  const page = source.getPage(params.slug);
  if (!page) notFound();

  return pageMetadata({
    title: metaTitle(page),
    description: await metaDescription(page),
    path: page.url,
    image: getPageImageUrl(page).url,
  });
}

/**
 * The `<title>`. The index is the site's front page, so its title says what pyfect is. A
 * reference page's own title is a bare name many modules share (`client`, `config`), so its
 * `<title>` is the dotted path: `pyfect.http.client API reference`.
 */
function metaTitle(page: SourcePage): string | { absolute: string } {
  if (page.slugs.length === 0) return { absolute: 'pyfect: Effect for Python' };
  if (page.slugs[0] !== 'reference') return page.data.title;
  if (page.slugs.length === 1) return 'API reference';
  const path = ['pyfect', ...page.slugs.slice(1, -1), page.data.title].join('.');
  return { absolute: `${path} API reference` };
}

/** A reference page's meta description is its docstring's summary line, when it has one. */
async function metaDescription(page: SourcePage): Promise<string> {
  if (page.data.description || !('load' in page.data)) return describe(page);
  const { structuredData } = await page.data.load();
  // Docstrings are Markdown: a description is plain text.
  const summary = structuredData.contents[0]?.content.replaceAll('`', '').trim();
  return summary || describe(page);
}
