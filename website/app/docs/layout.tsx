import { source } from '@/lib/source';
import { DocsSidebar } from '@/components/docs-sidebar';
import { SiteHeader } from '@/components/site-header';

// Layout after shadcn/ui's docs layout (apps/v4/app/(app)/docs/layout.tsx, MIT):
// a sticky header, a slim sidebar and the page.
export default function Layout({ children }: LayoutProps<'/docs'>) {
  return (
    <>
      <SiteHeader />
      <div className="mx-auto flex w-full max-w-[90rem] flex-1 items-start px-2 lg:px-4">
        <DocsSidebar tree={source.getPageTree()} />
        <div className="min-w-0 flex-1">{children}</div>
      </div>
    </>
  );
}
