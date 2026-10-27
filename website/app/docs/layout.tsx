import { source } from '@/lib/source';
import { DocsSidebar } from '@/components/docs-sidebar';
import { SiteFooter } from '@/components/site-footer';
import { SiteHeader } from '@/components/site-header';

// shadcn/ui's app and docs layouts (apps/v4/app/(app)/layout.tsx, (app)/docs/layout.tsx, MIT).
export default function Layout({ children }: LayoutProps<'/docs'>) {
  return (
    <div data-slot="layout" className="group/layout relative z-10 flex min-h-svh flex-col bg-background">
      <SiteHeader />
      <main className="flex min-h-0 flex-1 flex-col">
        <div className="container-wrapper flex flex-1 flex-col px-2">
          <div className="flex min-h-min w-full flex-1 items-start px-0 lg:grid lg:grid-cols-[var(--sidebar-width)_minmax(0,1fr)]">
            <DocsSidebar tree={source.getPageTree()} />
            <div className="h-full w-full">{children}</div>
          </div>
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}
