'use client';
import { Check, Copy } from 'lucide-react';
import { useState } from 'react';

/** Copies the page as Markdown (served from /llms.mdx). */
export function CopyPageButton({ markdownUrl }: { markdownUrl: string }) {
  const [copied, setCopied] = useState(false);

  return (
    <button
      type="button"
      onClick={async () => {
        const text = await fetch(markdownUrl).then((response) => response.text());
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      className="inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-sm text-fd-muted-foreground transition-colors hover:bg-fd-accent hover:text-fd-foreground"
    >
      {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
      Copy page
    </button>
  );
}
