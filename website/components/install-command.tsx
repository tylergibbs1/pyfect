'use client';
import { Check, Copy, SquareTerminal } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Button } from './ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from './ui/tabs';

// After shadcn/ui's package-manager command block (apps/v4/components/code-block-command.tsx,
// MIT), with Python's installers.

export function InstallCommand({ uv, pip }: { uv: string; pip: string }) {
  const tabs = { uv, pip };
  const [installer, setInstaller] = useState<keyof typeof tabs>('uv');
  const [hasCopied, setHasCopied] = useState(false);

  useEffect(() => {
    if (!hasCopied) return;
    const timer = setTimeout(() => setHasCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [hasCopied]);

  return (
    <figure data-code-figure="" data-not-typeset="">
      <div className="overflow-x-auto">
        <Tabs value={installer} className="gap-0" onValueChange={(value) => setInstaller(value as keyof typeof tabs)}>
          <div className="flex items-center gap-2 border-b border-border/50 px-3 py-1">
            <div className="flex size-4 items-center justify-center rounded-[1px] bg-foreground opacity-70">
              <SquareTerminal className="size-3 text-code" />
            </div>
            <TabsList className="rounded-none bg-transparent p-0">
              {Object.keys(tabs).map((key) => (
                <TabsTrigger
                  key={key}
                  value={key}
                  className="h-7 border border-transparent pt-0.5 shadow-none! data-[state=active]:border-input data-[state=active]:bg-background!"
                >
                  {key}
                </TabsTrigger>
              ))}
            </TabsList>
          </div>
          <div className="no-scrollbar overflow-x-auto">
            {Object.entries(tabs).map(([key, value]) => (
              <TabsContent key={key} value={key} className="mt-0 px-4 py-3.5">
                <pre>
                  <code className="relative font-mono text-sm leading-none">{value}</code>
                </pre>
              </TabsContent>
            ))}
          </div>
        </Tabs>
        <Button
          data-slot="copy-button"
          size="icon"
          variant="ghost"
          className="absolute top-2 right-2 z-10 size-7 opacity-70 hover:opacity-100 focus-visible:opacity-100"
          onClick={async () => {
            await navigator.clipboard.writeText(tabs[installer]);
            setHasCopied(true);
          }}
        >
          <span className="sr-only">Copy</span>
          {hasCopied ? <Check /> : <Copy />}
        </Button>
      </div>
    </figure>
  );
}
