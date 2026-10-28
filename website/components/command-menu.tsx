'use client';
import { type SearchResultRecord, useStaticSearch } from 'fumadocs-core/search/client';
import type * as PageTree from 'fumadocs-core/page-tree';
import { ArrowRight, CornerDownLeft, Hash, Text } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { navSections } from '@/lib/page-tree';
import { cn } from '@/lib/cn';
import { Button } from './ui/button';
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from './ui/command';
import { Dialog as DialogPrimitive } from 'radix-ui';
import { Dialog, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from './ui/dialog';

// After shadcn/ui's command menu (apps/v4/components/command-menu.tsx, MIT): pages by
// section, plus full-text results from the static index /api/search writes at build time.

const groupClass =
  'p-0! **:[[cmdk-group-heading]]:scroll-mt-16 **:[[cmdk-group-heading]]:p-3! **:[[cmdk-group-heading]]:pb-1!';
const itemClass =
  'h-9 rounded-md border border-transparent px-3! font-medium data-[selected=true]:border-input data-[selected=true]:bg-input/50';

function Kbd({ className, ...props }: React.ComponentProps<'kbd'>) {
  return (
    <kbd
      className={cn(
        'pointer-events-none flex h-5 items-center justify-center gap-1 rounded border bg-background px-1 font-sans text-[0.7rem] font-medium text-muted-foreground select-none [&_svg:not([class*=size-])]:size-3',
        className,
      )}
      {...props}
    />
  );
}

export function CommandMenu({
  tree,
  navItems,
}: {
  tree: PageTree.Root;
  navItems: { href: string; label: string }[];
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const { search, onSearchChange: setSearch, data } = useStaticSearch();
  const sections = useMemo(() => navSections(tree), [tree]);

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if ((e.key === 'k' && (e.metaKey || e.ctrlKey)) || e.key === '/') {
        const target = e.target;
        if (
          target instanceof HTMLElement &&
          (target.isContentEditable || target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement)
        ) {
          return;
        }
        e.preventDefault();
        setOpen((value) => !value);
      }
    };
    document.addEventListener('keydown', down);
    return () => document.removeEventListener('keydown', down);
  }, []);

  const go = useCallback(
    (url: string) => {
      setOpen(false);
      router.push(url);
    },
    [router],
  );

  const results = useMemo(() => {
    const seen = new Set<string>();
    const records: SearchResultRecord[] = [];
    for (const item of data?.items ?? []) {
      if (item.type === 'table') continue;
      // the reference's index holds some MDX (`<Card ... />`) and Markdown code spans
      const content = item.content.replace(/`/g, '').trim();
      if (content.startsWith('<') || content.length <= 1 || seen.has(content)) continue;
      seen.add(content);
      records.push({ ...item, content });
    }
    return records;
  }, [data]);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant="outline"
          className="relative h-8 w-full justify-start rounded-lg border-none bg-muted pl-3 font-normal text-foreground shadow-none transition-colors hover:bg-muted/50 md:w-48 lg:w-40 xl:w-64 dark:bg-card"
        >
          <span className="hidden xl:inline-flex">Search documentation...</span>
          <span className="inline-flex xl:hidden">Search...</span>
        </Button>
      </DialogTrigger>
      <DialogContent
        className="rounded-xl border-none bg-clip-padding p-2 pb-11 shadow-2xl ring-4 ring-neutral-200/80 dark:bg-neutral-900 dark:ring-neutral-800"
      >
        <DialogHeader className="sr-only">
          <DialogTitle>Search documentation...</DialogTitle>
          <DialogDescription>Search for a page or a symbol</DialogDescription>
        </DialogHeader>
        <Command
          shouldFilter={search.trim().length === 0}
          className="rounded-none bg-transparent **:data-[slot=command-input]:h-9! **:data-[slot=command-input]:py-0 **:data-[slot=command-input-wrapper]:mb-0 **:data-[slot=command-input-wrapper]:h-9! **:data-[slot=command-input-wrapper]:rounded-md **:data-[slot=command-input-wrapper]:border **:data-[slot=command-input-wrapper]:border-input **:data-[slot=command-input-wrapper]:bg-input/50"
        >
          <CommandInput placeholder="Search documentation..." value={search} onValueChange={setSearch} />
          <CommandList className="no-scrollbar min-h-80 scroll-pt-2 scroll-pb-1.5">
            <CommandEmpty className="py-12 text-center text-sm text-muted-foreground">
              No results found.
            </CommandEmpty>
            {search.trim().length === 0 ? (
              <>
                <CommandGroup heading="Pages" className={groupClass}>
                  {navItems.map((item) => (
                    <CommandItem key={item.href} value={`Navigation ${item.label}`} className={itemClass} onSelect={() => go(item.href)}>
                      <ArrowRight />
                      {item.label}
                    </CommandItem>
                  ))}
                </CommandGroup>
                {sections.map((section) => (
                  <CommandGroup key={section.key} heading={section.name} className={groupClass}>
                    {section.items.map((item) => (
                      <CommandItem key={item.url} value={item.url} className={itemClass} onSelect={() => go(item.url)}>
                        <ArrowRight />
                        {item.name}
                      </CommandItem>
                    ))}
                  </CommandGroup>
                ))}
              </>
            ) : (
              <CommandGroup heading="Search Results" className={groupClass}>
                {results.map((item) => (
                  <CommandItem
                    key={item.id}
                    value={item.id}
                    className={cn(itemClass, 'font-normal')}
                    onSelect={() => go(item.url)}
                  >
                    {item.type === 'page' ? <ArrowRight /> : item.type === 'heading' ? <Hash /> : <Text />}
                    <div className="line-clamp-1 text-sm">{item.content}</div>
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
          </CommandList>
        </Command>
        <div className="absolute inset-x-0 bottom-0 z-20 flex h-10 items-center gap-2 rounded-b-xl border-t border-t-neutral-100 bg-neutral-50 px-4 text-xs font-medium text-muted-foreground dark:border-t-neutral-700 dark:bg-neutral-800">
          <div className="flex items-center gap-2">
            <Kbd>
              <CornerDownLeft />
            </Kbd>
            Go to Page
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** shadcn's command menu dialog: near the top, without an overlay. */
function DialogContent({ className, children, ...props }: React.ComponentProps<typeof DialogPrimitive.Content>) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Content
        data-slot="dialog-content"
        className={cn(
          'fixed top-[15%] left-[50%] z-50 grid w-full max-w-[calc(100%-2rem)] translate-x-[-50%] gap-4 rounded-lg border bg-background p-6 shadow-lg duration-200 outline-none sm:max-w-lg',
          className,
        )}
        {...props}
      >
        {children}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}
