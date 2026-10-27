'use client';
import { Check, Copy } from 'lucide-react';
import { useState } from 'react';
import { cn } from '@/lib/cn';

/** Copies `value`, or the text of the closest `[data-code-block]` when no value is given. */
export function CopyButton({ value, className }: { value?: string; className?: string }) {
  const [copied, setCopied] = useState(false);

  return (
    <button
      type="button"
      data-slot="copy-button"
      onClick={async (event) => {
        const text =
          value ??
          event.currentTarget.closest('[data-code-block]')?.querySelector('pre')?.innerText ??
          '';
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      className={cn(
        'inline-flex size-7 items-center justify-center rounded-md text-[#9ba3ad] transition-colors hover:bg-white/10 hover:text-white',
        className,
      )}
    >
      {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
      <span className="sr-only">Copy code</span>
    </button>
  );
}
