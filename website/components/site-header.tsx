import Link from 'next/link';
import { source } from '@/lib/source';
import { appName, gitConfig } from '@/lib/shared';
import { GitHubIcon } from './icons';
import { MobileNav } from './mobile-nav';
import { ModeSwitcher } from './mode-switcher';
import { SearchButton } from './search-button';

// Structure after shadcn/ui's site header (apps/v4/components/site-header.tsx, MIT).
export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 w-full border-b bg-fd-background/95 backdrop-blur supports-[backdrop-filter]:bg-fd-background/80">
      <div className="mx-auto flex h-(--header-height) w-full max-w-[90rem] items-center gap-2 px-4 lg:px-6">
        <MobileNav tree={source.getPageTree()} className="lg:hidden" />
        <Link href="/" className="font-semibold tracking-tight">
          {appName}
        </Link>
        <nav className="ml-6 hidden items-center gap-5 text-sm text-fd-muted-foreground md:flex">
          <Link href="/docs" className="transition-colors hover:text-fd-foreground">
            Guide
          </Link>
          <Link href="/docs/reference" className="transition-colors hover:text-fd-foreground">
            API reference
          </Link>
        </nav>
        <div className="ml-auto flex items-center gap-1.5">
          <SearchButton />
          <a
            href={`https://github.com/${gitConfig.user}/${gitConfig.repo}`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex size-8 items-center justify-center rounded-md text-fd-muted-foreground transition-colors hover:bg-fd-accent hover:text-fd-foreground"
          >
            <GitHubIcon className="size-4" />
            <span className="sr-only">GitHub</span>
          </a>
          <ModeSwitcher />
        </div>
      </div>
    </header>
  );
}
