'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { appName } from '@/lib/shared';
import { cn } from '@/lib/cn';
import { Button } from './ui/button';

// After shadcn/ui's main nav (apps/v4/components/main-nav.tsx, MIT).
export function MainNav({
  items,
  className,
  ...props
}: React.ComponentProps<'nav'> & { items: { href: string; label: string }[] }) {
  const pathname = usePathname();

  return (
    <nav className={cn('items-center gap-0', className)} {...props}>
      <Button asChild variant="ghost" size="sm" className="mr-2 px-2.5 text-base font-semibold">
        <Link href="/docs">{appName}</Link>
      </Button>
      {items.map((item) => (
        <Button key={item.href} variant="ghost" asChild size="sm" className="px-2.5">
          <Link href={item.href} data-active={pathname === item.href} className="relative items-center">
            {item.label}
          </Link>
        </Button>
      ))}
    </nav>
  );
}
