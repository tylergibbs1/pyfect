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

/** `type` aliases come with the values, their annotation starting `type ` (see
 * `parse_type_alias` in scripts/generate_api.py): give them a table of their own. */
function splitTypes(nodes: RootContent[]): RootContent[] {
  return nodes.flatMap((node, i): RootContent[] => {
    if (!isElement(node, 'PyAttributes') || nodes[i - 1]?.type === 'heading') return [node];
    const isType = (child: (typeof node.children)[number]) =>
      child.type === 'mdxJsxFlowElement' && (attribute(child, 'type') ?? '').startsWith('type ');
    const values = node.children.filter((child) => !isType(child));
    const types = node.children.filter(isType);
    const out: RootContent[] = [];
    if (values.length > 0) out.push(heading(2, 'Values', 'values'), { ...node, children: values });
    if (types.length > 0) {
      out.push(heading(2, 'Types', 'types'), {
        ...node,
        attributes: [...node.attributes, { type: 'mdxJsxAttribute', name: 'kind', value: 'types' }],
        children: types,
      });
    }
    return out;
  });
}

/**
 * Shapes fumadocs-python's pages like the guides: a module's tabs become sections, its
 * values get a "Values" section and its `type` aliases a "Types" one, and each function or method gets its own heading, so
 * all of them are linkable and listed in the table of contents. A function entry then
 * leaves out its own title.
 */
export function remarkReferenceHeadings() {
  return (tree: Root) => {
    // A module's values (layers, effects, constants) and types come untitled; a class's
    // attributes already follow their own heading.
    tree.children = splitTypes(unwrapTabs(tree.children)).flatMap((node): RootContent[] => {
      if (!isElement(node, 'PyFunction')) return [node];
      const name = attribute(node, 'name');
      if (!name) return [node];
      node.attributes.push({ type: 'mdxJsxAttribute', name: 'titled', value: 'true' });
      return [heading(3, name, name), node];
    });
  };
}
