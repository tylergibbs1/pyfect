import type { ComponentProps } from 'react';
import { cn } from '@/lib/cn';
import { CopyButton } from './copy-button';

/**
 * A code block from Fumadocs' rehype-code (shiki), in the figure shadcn/ui's docs use for
 * rehype-pretty-code output: a title bar with the language icon, the code, a copy button.
 */
export function CodeBlock({
  title,
  icon,
  allowCopy,
  className,
  children,
  ...props
}: ComponentProps<'pre'> & { title?: string; icon?: string; allowCopy?: string | boolean }) {
  return (
    <figure data-code-figure="" data-not-typeset="">
      {title ? (
        <figcaption
          data-code-title=""
          className="flex items-center gap-2 text-code-foreground [&_svg]:size-4 [&_svg]:text-code-foreground [&_svg]:opacity-70"
        >
          {icon ? (
            // rehype-code's language icon: a static SVG string it generated
            <span aria-hidden className="flex" dangerouslySetInnerHTML={{ __html: icon }} />
          ) : null}
          {title}
        </figcaption>
      ) : null}
      <pre
        className={cn(
          'no-scrollbar min-w-0 overflow-x-auto overflow-y-auto overscroll-x-contain overscroll-y-auto px-4 py-3.5 outline-none',
          className,
        )}
        {...props}
        style={undefined}
      >
        {children}
      </pre>
      {allowCopy === 'false' || allowCopy === false ? null : <CopyButton />}
    </figure>
  );
}
