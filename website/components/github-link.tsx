import { githubUrl } from '@/lib/shared';
import { GitHubIcon } from './icons';
import { Button } from './ui/button';

// After shadcn/ui's GitHub link (apps/v4/components/github-link.tsx, MIT), without the
// star count: the site is static and fetches nothing at build time.
export function GitHubLink() {
  return (
    <Button asChild size="sm" variant="ghost" className="h-8 shadow-none">
      <a href={githubUrl} target="_blank" rel="noreferrer">
        <GitHubIcon />
        <span className="sr-only">GitHub</span>
      </a>
    </Button>
  );
}
