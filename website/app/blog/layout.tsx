import { SiteFooter } from '@/components/site-footer';
import { SiteHeader } from '@/components/site-header';

// The docs layout without the sidebar: the blog's pages are one centered column.
export default function Layout({ children }: LayoutProps<'/blog'>) {
  return (
    <div data-slot="layout" className="group/layout relative z-10 flex min-h-svh flex-col bg-background">
      <SiteHeader />
      <main className="flex min-h-0 flex-1 flex-col">
        <div className="container-wrapper flex flex-1 flex-col px-2">{children}</div>
      </main>
      <SiteFooter />
    </div>
  );
}
