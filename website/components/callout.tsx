import { cn } from '@/lib/cn';
import { Alert, AlertDescription, AlertTitle } from './ui/alert';

// From shadcn/ui's callout (apps/v4/components/callout.tsx, MIT).
export function Callout({
  title,
  children,
  icon,
  className,
  ...props
}: React.ComponentProps<typeof Alert> & { icon?: React.ReactNode }) {
  return (
    <Alert
      className={cn(
        'not-typeset mt-6 w-auto rounded-2xl border-surface bg-surface text-surface-foreground md:-mx-1 **:[a]:font-medium **:[a]:underline **:[a]:decoration-current/30 **:[a]:hover:decoration-current **:[code]:border',
        className,
      )}
      {...props}
    >
      {icon}
      {title ? <AlertTitle>{title}</AlertTitle> : null}
      <AlertDescription className="text-card-foreground/80">{children}</AlertDescription>
    </Alert>
  );
}
