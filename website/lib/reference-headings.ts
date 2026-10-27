import type { Heading, Root, RootContent } from 'mdast';
import type { MdxJsxFlowElement } from 'mdast-util-mdx-jsx';

function isFunctionEntry(node: RootContent): node is MdxJsxFlowElement {
  return node.type === 'mdxJsxFlowElement' && node.name === 'PyFunction';
}

function attribute(node: MdxJsxFlowElement, name: string): string | undefined {
  for (const attr of node.attributes) {
    if (attr.type === 'mdxJsxAttribute' && attr.name === name && typeof attr.value === 'string') {
      return attr.value;
    }
  }
}

/**
 * Gives each method on a class page its own heading, so methods are linkable and
 * listed in the table of contents. The entry then leaves out its own title.
 */
export function remarkReferenceHeadings() {
  return (tree: Root) => {
    tree.children = tree.children.flatMap((node): RootContent[] => {
      if (!isFunctionEntry(node)) return [node];
      const name = attribute(node, 'name');
      if (!name) return [node];
      node.attributes.push({ type: 'mdxJsxAttribute', name: 'titled', value: 'true' });
      const heading: Heading = {
        type: 'heading',
        depth: 3,
        children: [{ type: 'inlineCode', value: name }],
        data: { hProperties: { id: name } },
      };
      return [heading, node];
    });
  };
}
