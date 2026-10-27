import Link from 'next/link';
import { notFound } from 'next/navigation';
import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import { ArrowLeft, ArrowRight } from 'lucide-react';
import { findNeighbour } from 'fumadocs-core/page-tree';
import { source, type Page as SourcePage } from '@/lib/source';
import { getPageImageUrl, getPageMarkdownUrl } from '@/lib/shared';
import { mdxComponents } from '@/mdx-components';
import { referenceComponents } from '@/components/reference';
import { DocsTableOfContents, type TocItem } from '@/components/docs-toc';
import { CopyPageButton } from '@/components/copy-page-button';
import { cn } from '@/lib/cn';

// Page structure after shadcn/ui's docs page (apps/v4/app/(app)/docs/[[...slug]]/page.tsx, MIT).

export const revalidate = false;
export const dynamicParams = false;

type ReferenceData = Extract<SourcePage['data'], { load: unknown }>;

export default async function Page(props: PageProps<'/docs/[[...slug]]'>) {
  const params = await props.params;
  const page = source.getPage(params.slug);
  if (!page) notFound();

  if ('load' in page.data) {
    const { body, toc } = await renderReference(page.data);
    return (
      <DocsArticle page={page} toc={toc} wide>
        {body}
      </DocsArticle>
    );
  }

  const MDX = page.data.body;
  return (
    <DocsArticle
      page={page}
      toc={page.data.toc}
      wide={page.data.full === true}
      actions={<CopyPageButton markdownUrl={getPageMarkdownUrl(page).url} />}
    >
      <MDX components={mdxComponents} />
    </DocsArticle>
  );
}

/** A page generated from the API reference JSON (scripts/generate_api.py). */
async function renderReference(data: ReferenceData) {
  const rendered = await data.load();
  return rendered.render({ ...mdxComponents, ...referenceComponents });
}

/**
 * The page frame. Wide pages (two-column walkthroughs and the API reference) use the
 * whole width and fold the table of contents into a disclosure above the content.
 */
function DocsArticle({
  page,
  toc,
  wide,
  actions,
  children,
}: {
  page: SourcePage;
  toc: TocItem[];
  wide: boolean;
  actions?: ReactNode;
  children: ReactNode;
}) {
  const neighbours = findNeighbour(source.getPageTree(), page.url);

  return (
    <div className="flex items-start">
      <article
        className={cn(
          'mx-auto w-full min-w-0 px-4 py-8 md:px-8 lg:py-10',
          wide ? 'max-w-[72rem]' : 'max-w-[44rem]',
        )}
      >
        <header className="flex flex-col gap-2 border-b pb-6">
          <div className="flex items-start justify-between gap-4">
            <h1 className="text-3xl font-semibold tracking-tight">{page.data.title}</h1>
            {actions ? <div className="hidden shrink-0 sm:block">{actions}</div> : null}
          </div>
          {page.data.description ? (
            <p className="text-[1.0625rem] text-balance text-fd-muted-foreground">
              {page.data.description}
            </p>
          ) : null}
        </header>
        {toc.length > 0 ? (
          <DocsTableOfContents
            toc={toc}
            variant="dropdown"
            className={cn('mt-6', wide ? '' : 'xl:hidden')}
          />
        ) : null}
        <div className="typeset mt-2 pb-12">{children}</div>
        <footer className="flex items-center gap-2 border-t pt-6 text-sm">
          {neighbours.previous ? (
            <Link
              href={neighbours.previous.url}
              className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-fd-muted-foreground hover:bg-fd-accent hover:text-fd-foreground"
            >
              <ArrowLeft className="size-3.5" /> {neighbours.previous.name}
            </Link>
          ) : null}
          {neighbours.next ? (
            <Link
              href={neighbours.next.url}
              className="ml-auto inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-fd-muted-foreground hover:bg-fd-accent hover:text-fd-foreground"
            >
              {neighbours.next.name} <ArrowRight className="size-3.5" />
            </Link>
          ) : null}
        </footer>
      </article>
      {wide || toc.length === 0 ? null : (
        <aside className="sticky top-(--header-height) hidden max-h-[calc(100svh-var(--header-height))] w-56 shrink-0 overflow-y-auto py-10 pr-4 xl:block">
          <DocsTableOfContents toc={toc} />
        </aside>
      )}
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

  return {
    title: page.data.title,
    description: page.data.description,
    openGraph: {
      images: getPageImageUrl(page).url,
    },
  };
}
