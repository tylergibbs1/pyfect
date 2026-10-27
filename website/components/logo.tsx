import { cn } from '@/lib/cn';

// The pyfect mark: a solid "p" whose bowl holds one value, an effect wrapping a result.
// Filled with currentColor so it follows the text color in light and dark mode.
export const LOGO_PATH = 'M4 10a8 8 0 1 1 8 8h-1v3.5A2.5 2.5 0 0 1 8.5 24h-2A2.5 2.5 0 0 1 4 21.5zM12 6.2a3.8 3.8 0 1 0 0 7.6 3.8 3.8 0 0 0 0-7.6z';

export function LogoMark({ className, ...props }: React.ComponentProps<'svg'>) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className={cn('size-5', className)} {...props}>
      <path fill="currentColor" fillRule="evenodd" d={LOGO_PATH} />
      <circle cx="12" cy="10" r="1.6" fill="currentColor" />
    </svg>
  );
}
