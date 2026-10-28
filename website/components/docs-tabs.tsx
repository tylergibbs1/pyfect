import { cn } from '@/lib/cn';
import { Tabs, TabsContent, TabsList, TabsTrigger } from './ui/tabs';

// The underlined tabs of shadcn/ui's MDX (apps/v4/mdx-components.tsx, MIT).

export function DocsTabs({ className, ...props }: React.ComponentProps<typeof Tabs>) {
  return <Tabs data-not-typeset="" className={cn('relative mt-6 w-full', className)} {...props} />;
}

export function DocsTabsList({ className, ...props }: React.ComponentProps<typeof TabsList>) {
  return <TabsList className={cn('justify-start gap-4 rounded-none bg-transparent px-0', className)} {...props} />;
}

export function DocsTabsTrigger({ className, ...props }: React.ComponentProps<typeof TabsTrigger>) {
  return (
    <TabsTrigger
      className={cn(
        'rounded-none border-0 border-b-2 border-transparent bg-transparent px-0 pb-3 text-base text-muted-foreground hover:text-primary data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-foreground data-[state=active]:shadow-none! dark:data-[state=active]:border-primary dark:data-[state=active]:bg-transparent',
        className,
      )}
      {...props}
    />
  );
}

export function DocsTabsContent({ className, ...props }: React.ComponentProps<typeof TabsContent>) {
  return (
    <TabsContent
      className={cn('relative *:[figure]:first:mt-0 [&>.steps]:mt-6', className)}
      {...props}
    />
  );
}
