import type * as PageTree from 'fumadocs-core/page-tree';
import type { ReactNode } from 'react';

/** A sidebar link. */
export interface NavItem {
  name: ReactNode;
  url: string;
}

export interface NavSection {
  key: string;
  name: ReactNode;
  items: NavItem[];
}

function firstUrl(folder: PageTree.Folder): string | undefined {
  if (folder.index) return folder.index.url;
  for (const child of folder.children) {
    if (child.type === 'page') return child.url;
    if (child.type === 'folder') {
      const url = firstUrl(child);
      if (url) return url;
    }
  }
  return undefined;
}

function toItems(nodes: PageTree.Node[]): NavItem[] {
  const items: NavItem[] = [];
  for (const node of nodes) {
    if (node.type === 'page') items.push({ name: node.name, url: node.url });
    if (node.type === 'folder') {
      const url = firstUrl(node);
      if (url) items.push({ name: node.name, url });
    }
  }
  return items;
}

/**
 * The tree as flat sections, one per separator in content/docs/meta.json. A folder at
 * the top of a section (the API reference) is opened: its index becomes "Overview" and
 * its children become the section's links.
 */
export function navSections(tree: PageTree.Root): NavSection[] {
  const sections: NavSection[] = [];
  for (const node of tree.children) {
    if (node.type === 'separator' || sections.length === 0) {
      sections.push({
        key: node.$id ?? String(sections.length),
        name: node.type === 'separator' ? node.name : null,
        items: [],
      });
    }
    const section = sections[sections.length - 1];
    if (node.type === 'page') section.items.push(...toItems([node]));
    if (node.type === 'folder') {
      if (node.index) section.items.push({ name: 'Overview', url: node.index.url });
      section.items.push(...toItems(node.children));
    }
  }
  return sections.filter((section) => section.items.length > 0);
}
