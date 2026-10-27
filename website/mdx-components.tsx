import Link from 'next/link';
import type { MDXComponents } from 'mdx/types';
import type { ComponentProps, ReactNode } from 'react';
import { Callout } from '@/components/callout';
import { CodeBlock } from '@/components/code-block';
import { CodeOutput } from '@/components/code-output';
import { Diagram } from '@/components/diagram';
import { DocsTabs, DocsTabsContent, DocsTabsList, DocsTabsTrigger } from '@/components/docs-tabs';
import { InstallCommand } from '@/components/install-command';
import { cn } from '@/lib/cn';

// The MDX component map, after shadcn/ui's apps/v4/mdx-components.tsx (MIT).

function HeadingAnchor({ id, children }: { id?: string; children: ReactNode }) {
  if (!id) return children;
  return (
    <a className="group no-underline" href={`#${id}`}>
      <span className="underline-offset-4 group-hover:underline">{children}</span>
      <span aria-hidden="true" className="ml-2 text-muted-foreground opacity-0 group-hover:opacity-100">
        #
      </span>
    </a>
  );
}

function heading<Tag extends 'h1' | 'h2' | 'h3' | 'h4' | 'h5' | 'h6'>(Tag: Tag) {
  return function Heading({ children, id, ...props }: ComponentProps<Tag>) {
    const Element = Tag as 'h2';
    return (
      <Element id={id} {...(props as ComponentProps<'h2'>)}>
        <HeadingAnchor id={id}>{children}</HeadingAnchor>
      </Element>
    );
  };
}

function MdxLink({ href = '', ...props }: ComponentProps<'a'>) {
  if (href.startsWith('/')) return <Link href={href} {...props} />;
  if (href.startsWith('#')) return <a href={href} {...props} />;
  return <a href={href} target="_blank" rel="noreferrer" {...props} />;
}

export const mdxComponents = {
  h1: heading('h1'),
  h2: heading('h2'),
  h3: heading('h3'),
  h4: heading('h4'),
  h5: heading('h5'),
  h6: heading('h6'),
  a: MdxLink,
  // Typeset tables stay real tables and wrap to fit; wide ones scroll.
  table: (props: ComponentProps<'table'>) => (
    <div className="typeset-scroll no-scrollbar *:[table]:w-full">
      <table {...props} />
    </div>
  ),
  pre: CodeBlock,
  Step: (props: ComponentProps<'h3'>) => <h3 {...props} />,
  Steps: ({ className, ...props }: ComponentProps<'div'>) => (
    <div
      className={cn('steps mb-12 [counter-reset:step] md:ml-4 md:border-l md:pl-8 [&>h3]:step', className)}
      {...props}
    />
  ),
  Tabs: DocsTabs,
  TabsList: DocsTabsList,
  TabsTrigger: DocsTabsTrigger,
  TabsContent: DocsTabsContent,
  Callout,
  CodeOutput,
  Diagram,
  InstallCommand,
  Link,
} satisfies MDXComponents;

export function getMDXComponents(components?: MDXComponents) {
  return { ...mdxComponents, ...components } satisfies MDXComponents;
}

export const useMDXComponents = getMDXComponents;

declare global {
  type MDXProvidedComponents = ReturnType<typeof getMDXComponents>;
}
