import { Children, type ReactNode } from 'react';
import { DocsTabs, DocsTabsContent, DocsTabsList, DocsTabsTrigger } from './docs-tabs';

/**
 * A snippet and what it prints, as shadcn/ui's "Preview / Code" tabs become for Python.
 * The first child is the snippet, the second its output; both are `<include>`s of files
 * that tests/test_doc_snippets.py checks (the output is what running the snippet prints).
 */
export function CodeOutput({ children }: { children: ReactNode }) {
  const [code, output] = Children.toArray(children);

  return (
    <DocsTabs defaultValue="code">
      <DocsTabsList>
        <DocsTabsTrigger value="code">Code</DocsTabsTrigger>
        <DocsTabsTrigger value="output">Output</DocsTabsTrigger>
      </DocsTabsList>
      <DocsTabsContent value="code">{code}</DocsTabsContent>
      <DocsTabsContent value="output">{output}</DocsTabsContent>
    </DocsTabs>
  );
}
