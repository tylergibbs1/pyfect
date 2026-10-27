'use client';
import { useSearchContext } from 'fumadocs-ui/contexts/search';
import { Search } from 'lucide-react';

export function SearchButton() {
  const { setOpenSearch } = useSearchContext();

  return (
    <button
      type="button"
      onClick={() => setOpenSearch(true)}
      className="inline-flex h-8 items-center gap-2 rounded-md border bg-fd-muted/50 px-2.5 text-sm text-fd-muted-foreground transition-colors hover:bg-fd-accent hover:text-fd-foreground md:w-56"
    >
      <Search className="size-4" />
      <span className="hidden md:inline">Search docs</span>
      <kbd className="ml-auto hidden rounded border bg-fd-background px-1.5 font-sans text-[0.7rem] md:inline">
        ⌘K
      </kbd>
    </button>
  );
}
