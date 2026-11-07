import type { Metadata } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';
import { ThemeProvider } from '@/components/theme-provider';
import { cn } from '@/lib/cn';
import './global.css';

// Fonts as in shadcn/ui's docs (apps/v4/lib/fonts.ts), but `optional` where shadcn swaps:
// a size-adjusted fallback still wraps some lines differently, so a font arriving after the
// first paint moved the text below them. Preloaded, they are there in time on almost every
// load, and on a slow one the page keeps the fallback instead of shifting.
const fontSans = Geist({ subsets: ['latin'], variable: '--font-sans', display: 'optional' });
const fontHeading = Geist({ subsets: ['latin'], variable: '--font-heading', display: 'optional' });
const fontMono = Geist_Mono({
  subsets: ['latin'],
  variable: '--font-mono',
  weight: ['400'],
  display: 'optional',
});

export const metadata: Metadata = {
  title: { default: 'pyfect', template: '%s - pyfect' },
  description: 'Effect for Python: typed errors, services and structured concurrency.',
};

export default function Layout({ children }: LayoutProps<'/'>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={cn(fontSans.variable, fontHeading.variable, fontMono.variable)}
    >
      <body className="group/body overscroll-none antialiased">
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
