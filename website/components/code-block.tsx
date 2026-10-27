import type { ComponentProps } from 'react';
import { cn } from '@/lib/cn';
import { CopyButton } from './copy-button';

/**
 * A code block from Fumadocs' rehype-code: a dark panel with an optional file-name
 * title and a copy button. Styling after shadcn/ui's code figures (MIT).
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
    <figure data-code-block="" data-not-typeset="" className="code-block">
      {title ? (
        <figcaption className="code-block-title">
          {icon ? (
            <span
              aria-hidden
              className="[&_svg]:size-3.5"
              // rehype-code's file icon: a static SVG string
              dangerouslySetInnerHTML={{ __html: icon }}
            />
          ) : null}
          <span className="truncate">{title}</span>
          {allowCopy === 'false' ? null : <CopyButton className="ml-auto" />}
        </figcaption>
      ) : allowCopy === 'false' ? null : (
        <CopyButton className="absolute top-2 right-2 z-10" />
      )}
      <pre className={cn('code-block-pre', className)} {...props}>
        {children}
      </pre>
    </figure>
  );
}
