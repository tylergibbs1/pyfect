import type { ReactNode } from 'react';

// After shadcn/ui's callout (apps/v4/components/callout.tsx, MIT): a quiet surface, no icon.
export function Callout({ title, children }: { title?: ReactNode; children: ReactNode }) {
  return (
    <div data-slot="callout" className="rounded-xl border bg-fd-muted/60 px-4 py-3 text-[0.9375rem]">
      {title ? <p className="font-medium">{title}</p> : null}
      <div className="text-fd-muted-foreground [&_a]:font-medium [&_a]:underline [&_code]:font-mono [&_code]:text-[0.85em]">
        {children}
      </div>
    </div>
  );
}
