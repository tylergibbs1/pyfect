import { useId } from 'react';
import { cn } from '@/lib/cn';

// The pyfect mark: a solid disc holding one value, opened by a single cut —
// an effect wraps a result, and yielding takes it out.
// Filled with currentColor so it follows the text color in light and dark mode.
export function logoSvg(color: string): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><defs><mask id="m"><circle cx="12" cy="12" r="11" fill="#fff"/><circle cx="12" cy="12" r="5.5" fill="#000"/><path d="M12 12L24 0" stroke="#000" stroke-width="2.4"/><circle cx="12" cy="12" r="2.6" fill="#fff"/></mask></defs><rect width="24" height="24" fill="${color}" mask="url(#m)"/></svg>`;
}

export function LogoMark({ className, ...props }: React.ComponentProps<'svg'>) {
  const id = useId();
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className={cn('size-5', className)} {...props}>
      <defs>
        <mask id={id}>
          <circle cx="12" cy="12" r="11" fill="#fff" />
          <circle cx="12" cy="12" r="5.5" fill="#000" />
          <path d="M12 12L24 0" stroke="#000" strokeWidth={2.4} />
          <circle cx="12" cy="12" r="2.6" fill="#fff" />
        </mask>
      </defs>
      <rect width="24" height="24" fill="currentColor" mask={`url(#${id})`} />
    </svg>
  );
}
