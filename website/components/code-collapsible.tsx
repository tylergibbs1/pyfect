'use client';
import { useState } from 'react';
import { cn } from '@/lib/cn';
import { Button } from './ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from './ui/collapsible';
import { Separator } from './ui/separator';

// From shadcn/ui's collapsible code (apps/v4/components/code-collapsible-wrapper.tsx, MIT).
export function CodeCollapsible({ className, children }: { className?: string; children: React.ReactNode }) {
  const [isOpened, setIsOpened] = useState(false);

  return (
    <Collapsible
      open={isOpened}
      onOpenChange={setIsOpened}
      data-not-typeset=""
      className={cn('group/collapsible relative md:-mx-1', className)}
    >
      <CollapsibleTrigger asChild>
        <div className="absolute top-1.5 right-9 z-10 flex items-center">
          <Button variant="ghost" size="sm" className="h-7 rounded-md px-2 text-muted-foreground">
            {isOpened ? 'Collapse' : 'Expand'}
          </Button>
          <Separator orientation="vertical" className="mx-1.5 h-4!" />
        </div>
      </CollapsibleTrigger>
      <CollapsibleContent
        forceMount
        className="relative mt-6 overflow-hidden data-[state=closed]:max-h-64 [&>figure]:mt-0 [&>figure]:md:mx-0!"
      >
        {children}
      </CollapsibleContent>
      <CollapsibleTrigger className="absolute inset-x-0 -bottom-2 flex h-20 items-center justify-center rounded-b-lg bg-gradient-to-b from-code/70 to-code text-sm text-muted-foreground group-data-[state=open]/collapsible:hidden">
        {isOpened ? 'Collapse' : 'Expand'}
      </CollapsibleTrigger>
    </Collapsible>
  );
}
