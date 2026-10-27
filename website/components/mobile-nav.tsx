'use client';
import { Menu, X } from 'lucide-react';
import { useState } from 'react';
import type * as PageTree from 'fumadocs-core/page-tree';
import { cn } from '@/lib/cn';
import { DocsNav } from './docs-nav';

export function MobileNav({ tree, className }: { tree: PageTree.Root; className?: string }) {
  const [open, setOpen] = useState(false);

  return (
    <div className={className}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="-ml-1 inline-flex size-8 items-center justify-center rounded-md text-fd-muted-foreground hover:bg-fd-accent hover:text-fd-foreground"
      >
        {open ? <X className="size-4" /> : <Menu className="size-4" />}
        <span className="sr-only">Menu</span>
      </button>
      <div
        // close after following a link
        onClick={(event) => {
          if ((event.target as HTMLElement).closest('a')) setOpen(false);
        }}
        className={cn(
          'fixed inset-x-0 top-(--header-height) bottom-0 z-40 overflow-y-auto bg-fd-background px-4 py-6',
          open ? 'block' : 'hidden',
        )}
      >
        <DocsNav tree={tree} />
      </div>
    </div>
  );
}
