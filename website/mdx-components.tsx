import Link from 'next/link';
import type { MDXComponents } from 'mdx/types';
import type { ComponentProps, ReactNode } from 'react';
import { Tab, Tabs } from 'fumadocs-ui/components/tabs';
import { Callout } from '@/components/callout';
import { CodeBlock } from '@/components/code-block';
import { Split, SplitCode, SplitProse } from '@/components/split';
import { cn } from '@/lib/cn';

// The MDX component map, after shadcn/ui's apps/v4/mdx-components.tsx (MIT): headings
// with hover anchors, code blocks with titles and copy buttons, steps, callouts, tabs.

type HeadingTag = 'h1' | 'h2' | 'h3' | 'h4' | 'h5' | 'h6';

function heading(Tag: HeadingTag) {
  return function Heading({ id, children, ...props }: ComponentProps<HeadingTag>) {
    return (
      <Tag id={id} {...props}>
        {id ? (
          <a className="group no-underline" href={`#${id}`}>
            {children}
            <span aria-hidden className="ml-2 text-fd-muted-foreground opacity-0 group-hover:opacity-100">
              #
            </span>
          </a>
        ) : (
          children
        )}
      </Tag>
    );
  };
}

function MdxLink({ href = '', ...props }: ComponentProps<'a'>) {
  if (href.startsWith('/')) return <Link href={href} {...props} />;
  if (href.startsWith('#')) return <a href={href} {...props} />;
  return <a href={href} target="_blank" rel="noreferrer" {...props} />;
}

function Steps({ className, ...props }: ComponentProps<'div'>) {
  return <div className={cn('steps', className)} {...props} />;
}

function Cards({ children }: { children: ReactNode }) {
  return (
    <div data-slot="cards" className="grid gap-3 sm:grid-cols-2">
      {children}
    </div>
  );
}

function Card({ title, href, children }: { title: ReactNode; href: string; children?: ReactNode }) {
  return (
    <Link
      href={href}
      className="block rounded-xl border p-4 transition-colors hover:bg-fd-accent/60"
    >
      <span className="font-medium">{title}</span>
      {children ? <span className="mt-1 block text-sm text-fd-muted-foreground">{children}</span> : null}
    </Link>
  );
}

export const mdxComponents = {
  h1: heading('h1'),
  h2: heading('h2'),
  h3: heading('h3'),
  h4: heading('h4'),
  h5: heading('h5'),
  h6: heading('h6'),
  a: MdxLink,
  pre: CodeBlock,
  table: (props: ComponentProps<'table'>) => (
    <div className="typeset-scroll">
      <table {...props} />
    </div>
  ),
  Callout,
  Card,
  Cards,
  Step: (props: ComponentProps<'h3'>) => <h3 {...props} />,
  Steps,
  Split,
  SplitCode,
  SplitProse,
  Tab,
  Tabs,
} satisfies MDXComponents;

export function getMDXComponents(components?: MDXComponents) {
  return { ...mdxComponents, ...components } satisfies MDXComponents;
}

export const useMDXComponents = getMDXComponents;

declare global {
  type MDXProvidedComponents = ReturnType<typeof getMDXComponents>;
}
