import type { Heading, Root, RootContent } from 'mdast';
import type { MdxJsxFlowElement } from 'mdast-util-mdx-jsx';

function isElement(node: RootContent, name: string): node is MdxJsxFlowElement {
  return node.type === 'mdxJsxFlowElement' && node.name === name;
}

function attribute(node: MdxJsxFlowElement, name: string): string | undefined {
  for (const attr of node.attributes) {
    if (attr.type === 'mdxJsxAttribute' && attr.name === name && typeof attr.value === 'string') {
      return attr.value;
    }
  }
}

function heading(depth: 2 | 3, text: string, id: string): Heading {
  return {
    type: 'heading',
    depth,
    children: [{ type: 'text', value: text }],
    data: { hProperties: { id } },
  };
}

const SECTION_TITLES: Record<string, string> = { Class: 'Classes', Functions: 'Functions', Modules: 'Modules' };

/** A module page's `<Tabs>` of classes, functions and submodules, as sections in a row. */
function unwrapTabs(nodes: RootContent[]): RootContent[] {
  return nodes.flatMap((node): RootContent[] => {
    if (!isElement(node, 'Tabs')) return [node];
    return node.children.flatMap((tab): RootContent[] => {
      if (tab.type !== 'mdxJsxFlowElement' || tab.name !== 'Tab') return [tab as RootContent];
      const title = SECTION_TITLES[attribute(tab, 'value') ?? ''] ?? attribute(tab, 'value') ?? '';
      return [heading(2, title, title.toLowerCase()), ...(tab.children as RootContent[])];
    });
  });
}

/**
 * Shapes fumadocs-python's pages like the guides: a module's tabs become sections, its
 * values get a "Values" section, and each function or method gets its own heading, so
 * all of them are linkable and listed in the table of contents. A function entry then
 * leaves out its own title.
 */
export function remarkReferenceHeadings() {
  return (tree: Root) => {
    tree.children = unwrapTabs(tree.children).flatMap((node, i, nodes): RootContent[] => {
      // A module's values (layers, effects, constants) come untitled; a class's attributes
      // already follow their own heading.
      if (isElement(node, 'PyAttributes') && nodes[i - 1]?.type !== 'heading') {
        return [heading(2, 'Values', 'values'), node];
      }
      if (!isElement(node, 'PyFunction')) return [node];
      const name = attribute(node, 'name');
      if (!name) return [node];
      node.attributes.push({ type: 'mdxJsxAttribute', name: 'titled', value: 'true' });
      return [heading(3, name, name), node];
    });
  };
}
