'use client';
import Link from 'next/link';
import { useState } from 'react';
import type * as PageTree from 'fumadocs-core/page-tree';
import { navSections } from '@/lib/page-tree';
import { cn } from '@/lib/cn';
import { Button } from './ui/button';
import { Popover, PopoverContent, PopoverTrigger } from './ui/popover';

// After shadcn/ui's mobile nav (apps/v4/components/mobile-nav.tsx, MIT).

function MobileLink({
  href,
  onOpenChange,
  className,
  children,
}: {
  href: string;
  onOpenChange: (open: boolean) => void;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      onClick={() => onOpenChange(false)}
      className={cn('flex items-center gap-2 text-2xl font-medium', className)}
    >
      {children}
    </Link>
  );
}


export function MobileNav({
  tree,
  items,
  className,
}: {
  tree: PageTree.Root;
  items: { href: string; label: string }[];
  className?: string;
}) {
  const [open, setOpen] = useState(false);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          className={cn(
            'extend-touch-target h-8 touch-manipulation items-center justify-start gap-2.5 p-0! hover:bg-transparent focus-visible:bg-transparent focus-visible:ring-0 active:bg-transparent dark:hover:bg-transparent',
            className,
          )}
        >
          <div className="relative flex h-8 w-4 items-center justify-center">
            <div className="relative size-4">
              <span
                className={cn(
                  'absolute left-0 block h-0.5 w-4 bg-foreground transition-all duration-100',
                  open ? 'top-[0.4rem] -rotate-45' : 'top-1',
                )}
              />
              <span
                className={cn(
                  'absolute left-0 block h-0.5 w-4 bg-foreground transition-all duration-100',
                  open ? 'top-[0.4rem] rotate-45' : 'top-2.5',
                )}
              />
            </div>
            <span className="sr-only">Toggle Menu</span>
          </div>
          <span className="flex h-8 items-center text-lg leading-none font-medium">Menu</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent
        className="no-scrollbar h-(--radix-popper-available-height) w-(--radix-popper-available-width) overflow-y-auto rounded-none border-none bg-background/90 p-0 shadow-none backdrop-blur duration-100"
        align="start"
        side="bottom"
        alignOffset={-16}
        sideOffset={14}
      >
        <div className="flex flex-col gap-12 overflow-auto px-6 py-6">
          <div className="flex flex-col gap-4">
            <div className="text-sm font-medium text-muted-foreground">Menu</div>
            <div className="flex flex-col gap-3">
              {items.map((item) => (
                <MobileLink key={item.href} href={item.href} onOpenChange={setOpen}>
                  {item.label}
                </MobileLink>
              ))}
            </div>
          </div>
          <div className="flex flex-col gap-8">
            {navSections(tree).map((section) => (
              <div key={section.key} className="flex flex-col gap-4">
                <div className="text-sm font-medium text-muted-foreground">{section.name}</div>
                <div className="flex flex-col gap-3">
                  {section.items.map((item) => (
                    <MobileLink key={item.url} href={item.url} onOpenChange={setOpen}>
                      {item.name}
                    </MobileLink>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
