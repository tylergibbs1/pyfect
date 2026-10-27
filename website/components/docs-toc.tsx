'use client';
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { cn } from '@/lib/cn';

// After shadcn/ui's table of contents (apps/v4/components/docs-toc.tsx, MIT), without
// its "On This Page" label: the list sits beside the page and needs no heading.

export interface TocItem {
  title: ReactNode;
  url: string;
  depth: number;
}

function useActiveItem(itemIds: string[]) {
  const [activeId, setActiveId] = useState<string | null>(null);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) setActiveId(entry.target.id);
        }
      },
      { rootMargin: '0% 0% -80% 0%' },
    );
    const elements = itemIds
      .map((id) => document.getElementById(id))
      .filter((element): element is HTMLElement => element !== null);
    for (const element of elements) observer.observe(element);
    return () => observer.disconnect();
  }, [itemIds]);

  return activeId;
}

function Links({ toc, activeId }: { toc: TocItem[]; activeId: string | null }) {
  return toc.map((item) => (
    <a
      key={item.url}
      href={item.url}
      data-active={item.url === `#${activeId}`}
      data-depth={item.depth}
      className="block py-1 text-[0.8125rem] text-fd-muted-foreground no-underline transition-colors hover:text-fd-foreground data-[active=true]:font-medium data-[active=true]:text-fd-foreground data-[depth=3]:pl-3 data-[depth=4]:pl-6"
    >
      {item.title}
    </a>
  ));
}

export function DocsTableOfContents({
  toc,
  variant = 'list',
  className,
}: {
  toc: TocItem[];
  variant?: 'list' | 'dropdown';
  className?: string;
}) {
  const itemIds = useMemo(() => toc.map((item) => item.url.replace('#', '')), [toc]);
  const activeId = useActiveItem(itemIds);

  if (toc.length === 0) return null;

  if (variant === 'dropdown') {
    return (
      <details className={cn('group rounded-lg border text-sm', className)}>
        <summary className="flex cursor-pointer list-none items-center justify-between px-3 py-2 text-fd-muted-foreground [&::-webkit-details-marker]:hidden">
          On this page
          <span aria-hidden className="transition-transform group-open:rotate-90">
            ›
          </span>
        </summary>
        <div className="max-h-[60svh] overflow-y-auto border-t px-3 py-2">
          <Links toc={toc} activeId={activeId} />
        </div>
      </details>
    );
  }

  return (
    <nav className={cn('flex flex-col', className)}>
      <Links toc={toc} activeId={activeId} />
    </nav>
  );
}
