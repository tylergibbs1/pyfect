'use client';
import { TextAlignJustify } from 'lucide-react';
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { Button } from './ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from './ui/dropdown-menu';

// From shadcn/ui's table of contents (apps/v4/components/docs-toc.tsx, MIT). The active
// link changes color only (no weight change), so the rail's text never rewraps.

export interface TocItem {
  title?: ReactNode;
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
    for (const id of itemIds) {
      const element = document.getElementById(id);
      if (element) observer.observe(element);
    }
    return () => observer.disconnect();
  }, [itemIds]);

  return activeId;
}

export function DocsTableOfContents({
  toc,
  variant = 'list',
  className,
}: {
  toc: TocItem[];
  variant?: 'dropdown' | 'list';
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const itemIds = useMemo(() => toc.map((item) => item.url.replace('#', '')), [toc]);
  const activeHeading = useActiveItem(itemIds);

  if (!toc.length) return null;

  if (variant === 'dropdown') {
    return (
      <DropdownMenu open={open} onOpenChange={setOpen}>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm" className={cn('h-8 md:h-7', className)}>
            <TextAlignJustify /> On This Page
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="no-scrollbar max-h-[70svh]">
          {toc.map((item) => (
            <DropdownMenuItem
              key={item.url}
              asChild
              onClick={() => setOpen(false)}
              data-depth={item.depth}
              className="data-[depth=3]:pl-6 data-[depth=4]:pl-8"
            >
              <a href={item.url}>{item.title}</a>
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    );
  }

  return (
    <div className={cn('flex flex-col gap-2 p-4 pt-0 text-sm', className)}>
      <p className="h-6 bg-background text-xs font-medium text-muted-foreground">On This Page</p>
      {toc.map((item) => (
        <a
          key={item.url}
          href={item.url}
          className="text-[0.8rem] text-muted-foreground no-underline transition-colors hover:text-foreground data-[active=true]:text-foreground data-[depth=3]:pl-4 data-[depth=4]:pl-6"
          data-active={item.url === `#${activeHeading}`}
          data-depth={item.depth}
        >
          {item.title}
        </a>
      ))}
    </div>
  );
}
