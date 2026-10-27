import type * as PageTree from 'fumadocs-core/page-tree';
import { DocsNav } from './docs-nav';

export function DocsSidebar({ tree }: { tree: PageTree.Root }) {
  return (
    <aside className="sticky top-(--header-height) hidden h-[calc(100svh-var(--header-height))] w-(--sidebar-width) shrink-0 overflow-y-auto overscroll-contain border-r py-8 pr-4 pl-2 lg:block [scrollbar-width:thin]">
      <DocsNav tree={tree} />
    </aside>
  );
}
