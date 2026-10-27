import { githubUrl } from '@/lib/shared';

// After shadcn/ui's site footer (apps/v4/components/site-footer.tsx, MIT); as there, docs
// pages hide it.
export function SiteFooter() {
  return (
    <footer className="group-has-[[data-slot=docs]]/body:hidden">
      <div className="container-wrapper px-4 xl:px-6">
        <div className="flex h-14 items-center justify-between xl:h-24">
          <div className="w-full px-1 text-center text-xs leading-loose text-muted-foreground sm:text-sm">
            The source code is available on{' '}
            <a href={githubUrl} target="_blank" rel="noreferrer" className="font-medium underline underline-offset-4">
              GitHub
            </a>
            .
          </div>
        </div>
      </div>
    </footer>
  );
}
