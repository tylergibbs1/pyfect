'use client';
import { Check, ChevronDown, Copy } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Button } from './ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from './ui/dropdown-menu';
import { Popover, PopoverAnchor, PopoverContent, PopoverTrigger } from './ui/popover';
import { Separator } from './ui/separator';

// After shadcn/ui's "Copy Page" menu (apps/v4/components/docs-copy-page.tsx, MIT), with
// only the Markdown view: the page as served from /llms.mdx.

// Radix's `asChild` passes the menu item's props (role, handlers, ref) to this link.
function MarkdownLink({ url, ...props }: React.ComponentProps<'a'> & { url: string }) {
  return (
    <a href={url} target="_blank" rel="noopener noreferrer" {...props}>
      <svg strokeLinejoin="round" viewBox="0 0 22 16">
        <path fillRule="evenodd" clipRule="evenodd" d="M19.5 2.25H2.5C1.80964 2.25 1.25 2.80964 1.25 3.5V12.5C1.25 13.1904 1.80964 13.75 2.5 13.75H19.5C20.1904 13.75 20.75 13.1904 20.75 12.5V3.5C20.75 2.80964 20.1904 2.25 19.5 2.25ZM2.5 1C1.11929 1 0 2.11929 0 3.5V12.5C0 13.8807 1.11929 15 2.5 15H19.5C20.8807 15 22 13.8807 22 12.5V3.5C22 2.11929 20.8807 1 19.5 1H2.5ZM3 4.5H4H4.25H4.6899L4.98715 4.82428L7 7.02011L9.01285 4.82428L9.3101 4.5H9.75H10H11V5.5V11.5H9V7.79807L7.73715 9.17572L7 9.97989L6.26285 9.17572L5 7.79807V11.5H3V5.5V4.5ZM15 8V4.5H17V8H19.5L17 10.5L16 11.5L15 10.5L12.5 8H15Z" fill="currentColor" />
      </svg>
      View as Markdown
    </a>
  );
}

export function DocsCopyPage({ page, markdownUrl }: { page: string; markdownUrl: string }) {
  const [isCopied, setIsCopied] = useState(false);

  useEffect(() => {
    if (!isCopied) return;
    const timer = setTimeout(() => setIsCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [isCopied]);

  const trigger = (
    <Button variant="secondary" size="sm" className="peer -ml-0.5 size-8 shadow-none md:size-7 md:text-[0.8rem]">
      <ChevronDown className="rotate-180 sm:rotate-0" />
    </Button>
  );

  return (
    <Popover>
      <div className="group/buttons relative flex rounded-lg bg-secondary *:[[data-slot=button]]:focus-visible:relative *:[[data-slot=button]]:focus-visible:z-10">
        <PopoverAnchor />
        <Button
          variant="secondary"
          size="sm"
          className="h-8 shadow-none md:h-7 md:text-[0.8rem]"
          onClick={async () => {
            await navigator.clipboard.writeText(page);
            setIsCopied(true);
          }}
        >
          {isCopied ? <Check /> : <Copy />}
          Copy Page
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild className="hidden sm:flex">
            {trigger}
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="animate-none! rounded-lg shadow-none">
            <DropdownMenuItem asChild>
              <MarkdownLink url={markdownUrl} />
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <Separator
          orientation="vertical"
          className="absolute top-1 right-8 z-0 h-6! bg-foreground/5! peer-focus-visible:opacity-0 sm:right-7 sm:h-5!"
        />
        <PopoverTrigger asChild className="flex sm:hidden">
          {trigger}
        </PopoverTrigger>
        <PopoverContent
          className="w-52 origin-center! rounded-lg bg-background/70 p-1 shadow-none backdrop-blur-sm dark:bg-background/60"
          align="start"
        >
          <Button
            variant="ghost"
            size="lg"
            asChild
            className="w-full justify-start text-base font-normal *:[svg]:text-muted-foreground"
          >
            <MarkdownLink url={markdownUrl} />
          </Button>
        </PopoverContent>
      </div>
    </Popover>
  );
}
