'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import type * as PageTree from 'fumadocs-core/page-tree';
import { cn } from '@/lib/cn';

// The sidebar's links, grouped by the separators in content/docs/meta.json.
// Group structure after shadcn/ui's docs sidebar (apps/v4/components/docs-sidebar.tsx, MIT).

function containsUrl(node: PageTree.Node, url: string): boolean {
  if (node.type === 'page') return node.url === url;
  if (node.type === 'folder') {
    return node.index?.url === url || node.children.some((child) => containsUrl(child, url));
  }
  return false;
}

function NavLink({ href, active, children }: { href: string; active: boolean; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      data-active={active}
      className={cn(
        'flex min-h-7 items-center gap-2 rounded-md px-2 text-[0.8125rem] text-fd-muted-foreground transition-colors hover:text-fd-foreground',
        'data-[active=true]:bg-fd-accent data-[active=true]:font-medium data-[active=true]:text-fd-foreground',
      )}
    >
      {children}
    </Link>
  );
}

function Nodes({ nodes, pathname }: { nodes: PageTree.Node[]; pathname: string }) {
  return (
    <ul className="flex flex-col gap-0.5">
      {nodes.map((node, i) => {
        if (node.type === 'separator') return null;
        if (node.type === 'page') {
          return (
            <li key={node.url}>
              <NavLink href={node.url} active={node.url === pathname}>
                {node.name}
              </NavLink>
            </li>
          );
        }
        return (
          <li key={node.$id ?? i}>
            <details open={containsUrl(node, pathname)} className="group/folder">
              <summary className="flex min-h-7 cursor-pointer list-none items-center justify-between rounded-md px-2 text-[0.8125rem] text-fd-muted-foreground hover:text-fd-foreground [&::-webkit-details-marker]:hidden">
                {node.name}
                <span aria-hidden className="text-xs transition-transform group-open/folder:rotate-90">
                  ›
                </span>
              </summary>
              <div className="ml-2 border-l pl-2">
                {node.index ? (
                  <NavLink href={node.index.url} active={node.index.url === pathname}>
                    Overview
                  </NavLink>
                ) : null}
                <Nodes nodes={node.children} pathname={pathname} />
              </div>
            </details>
          </li>
        );
      })}
    </ul>
  );
}

/** Split the root's children into groups, each starting at a separator. */
function groups(tree: PageTree.Root) {
  const out: { name: React.ReactNode; key: string; nodes: PageTree.Node[] }[] = [];
  for (const node of tree.children) {
    if (node.type === 'separator' || out.length === 0) {
      out.push({
        name: node.type === 'separator' ? node.name : null,
        key: node.$id ?? String(out.length),
        nodes: [],
      });
    }
    if (node.type !== 'separator') out[out.length - 1].nodes.push(node);
  }
  return out;
}

export function DocsNav({ tree }: { tree: PageTree.Root }) {
  const pathname = usePathname();

  return (
    <nav className="flex flex-col gap-6 text-sm">
      {groups(tree).map((group) => (
        <div key={group.key} className="flex flex-col gap-1">
          {group.name ? (
            <p className="px-2 pb-1 text-[0.8125rem] font-medium text-fd-foreground">{group.name}</p>
          ) : null}
          <Nodes nodes={group.nodes} pathname={pathname} />
        </div>
      ))}
    </nav>
  );
}
