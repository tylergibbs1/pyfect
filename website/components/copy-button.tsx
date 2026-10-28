'use client';
import { Check, Copy } from 'lucide-react';
import { useEffect, useState } from 'react';
import { cn } from '@/lib/cn';
import { Button } from './ui/button';

// From shadcn/ui's copy button (apps/v4/components/copy-button.tsx, MIT). Without a
// `value` it copies the code of the figure it sits in.
export function CopyButton({
  value,
  className,
  variant = 'ghost',
}: {
  value?: string;
  className?: string;
  variant?: 'ghost' | 'secondary';
}) {
  const [hasCopied, setHasCopied] = useState(false);

  useEffect(() => {
    if (!hasCopied) return;
    const timer = setTimeout(() => setHasCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [hasCopied]);

  return (
    <Button
      data-slot="copy-button"
      data-copied={hasCopied}
      size="icon"
      variant={variant}
      className={cn(
        'absolute top-3 right-2 z-10 size-7 bg-code hover:opacity-100 focus-visible:opacity-100',
        className,
      )}
      onClick={async (event) => {
        const text =
          value ??
          event.currentTarget.closest('[data-code-figure]')?.querySelector('pre')?.innerText ??
          '';
        await navigator.clipboard.writeText(text);
        setHasCopied(true);
      }}
    >
      <span className="sr-only">Copy</span>
      {hasCopied ? <Check /> : <Copy />}
    </Button>
  );
}
