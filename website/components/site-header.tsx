import { source } from '@/lib/source';
import { navItems } from '@/lib/shared';
import { CommandMenu } from './command-menu';
import { GitHubLink } from './github-link';
import { MainNav } from './main-nav';
import { MobileNav } from './mobile-nav';
import { ModeSwitcher } from './mode-switcher';
import { Separator } from './ui/separator';

// After shadcn/ui's site header (apps/v4/components/site-header.tsx, MIT).
export function SiteHeader() {
  const tree = source.getPageTree();

  return (
    <header className="sticky top-0 z-50 w-full bg-background">
      <div className="container-wrapper px-6">
        <div className="flex h-(--header-height) items-center **:data-[slot=separator]:h-4!">
          <MobileNav tree={tree} items={navItems} className="flex lg:hidden" />
          <MainNav items={navItems} className="hidden lg:flex" />
          <div className="ml-auto flex items-center gap-2 md:flex-1 md:justify-end">
            <div className="hidden w-full flex-1 md:flex md:w-auto md:flex-none">
              <CommandMenu tree={tree} navItems={navItems} />
            </div>
            <Separator orientation="vertical" className="ml-2 hidden lg:block" />
            <GitHubLink />
            <Separator orientation="vertical" />
            <ModeSwitcher />
          </div>
        </div>
      </div>
    </header>
  );
}
