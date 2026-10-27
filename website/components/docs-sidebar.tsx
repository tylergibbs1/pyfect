'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useLayoutEffect, useRef } from 'react';
import type * as PageTree from 'fumadocs-core/page-tree';
import { navSections, type NavItem } from '@/lib/page-tree';

// After shadcn/ui's docs sidebar (apps/v4/components/docs-sidebar.tsx, MIT), with the
// classes of its Sidebar primitives inlined.

const itemClass =
  'relative flex h-[30px] w-fit items-center gap-2 overflow-visible rounded-md border border-transparent p-2 text-left text-[0.8rem] font-medium outline-hidden ring-sidebar-ring transition-[width,height,padding] after:absolute after:inset-x-0 after:-inset-y-1 after:z-0 after:rounded-md hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-2 data-[active=true]:border-accent data-[active=true]:bg-accent data-[active=true]:text-sidebar-accent-foreground';

// Links stay flat, as in shadcn's sidebar: expanding a module in place would push the
// links below it down on every navigation. A module's page lists its classes.
function Item({ item, pathname }: { item: NavItem; pathname: string }) {

  return (
    <li className="relative">
      <Link href={item.url} data-active={item.url === pathname} className={itemClass}>
        <span className="absolute inset-0 flex w-(--sidebar-menu-width) bg-transparent" />
        {item.name}
      </Link>
    </li>
  );
}

export function DocsSidebar({ tree }: { tree: PageTree.Root }) {
  const pathname = usePathname();
  const contentRef = useRef<HTMLDivElement>(null);

  // Keep the active link in view (the reference list is long).
  useLayoutEffect(() => {
    const container = contentRef.current;
    const active = container?.querySelector<HTMLElement>('[data-active="true"]');
    if (!container || !active) return;
    const box = container.getBoundingClientRect();
    const rect = active.getBoundingClientRect();
    if (rect.top < box.top || rect.bottom > box.bottom) {
      container.scrollTop += rect.top - box.top - (container.clientHeight - rect.height) / 2;
    }
  }, [pathname]);

  return (
    <aside
      data-slot="sidebar"
      className="sticky top-[calc(var(--header-height)+0.6rem)] z-30 hidden h-[calc(100svh-10rem)] w-(--sidebar-width) flex-col overflow-hidden overscroll-none bg-transparent text-sidebar-foreground [--sidebar-menu-width:--spacing(56)] lg:flex"
    >
      <div className="absolute top-12 right-2 bottom-0 hidden h-full w-px bg-[linear-gradient(to_bottom,transparent_0%,var(--border)_10%,var(--border)_90%,transparent_100%)] lg:flex" />
      <div
        ref={contentRef}
        className="no-scrollbar flex min-h-0 w-(--sidebar-menu-width) flex-1 flex-col gap-2 overflow-auto overflow-x-hidden pl-2.5"
      >
        {navSections(tree).map((section, index) => (
          <div key={section.key} className={`relative flex w-full min-w-0 flex-col p-2 ${index === 0 ? 'pt-12' : ''}`}>
            {section.name ? (
              <div className="flex h-8 shrink-0 items-center rounded-md px-2 text-xs font-medium text-muted-foreground">
                {section.name}
              </div>
            ) : null}
            <ul className="flex w-full min-w-0 flex-col gap-0.5 text-sm">
              {section.items.map((item) => (
                <Item key={item.url} item={item} pathname={pathname} />
              ))}
            </ul>
          </div>
        ))}
      </div>
    </aside>
  );
}
