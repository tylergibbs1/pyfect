import type { Metadata } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';
import { ThemeProvider } from '@/components/theme-provider';
import { cn } from '@/lib/cn';
import './global.css';

// Fonts as in shadcn/ui's docs (apps/v4/lib/fonts.ts). next/font serves them with
// size-adjusted fallbacks, so text does not move when they load.
const fontSans = Geist({ subsets: ['latin'], variable: '--font-sans' });
const fontHeading = Geist({ subsets: ['latin'], variable: '--font-heading' });
const fontMono = Geist_Mono({ subsets: ['latin'], variable: '--font-mono', weight: ['400'] });

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
