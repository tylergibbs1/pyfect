import type { ReactNode } from 'react';

/**
 * A guide section in two columns on wide screens: prose on the left, its code in a
 * sticky panel on the right. Stacked on narrow screens.
 *
 *     <Split>
 *       <SplitProse>...</SplitProse>
 *       <SplitCode><include>...</include></SplitCode>
 *     </Split>
 */
export function Split({ children }: { children: ReactNode }) {
  return <div className="split">{children}</div>;
}

export function SplitProse({ children }: { children: ReactNode }) {
  return <div className="split-prose">{children}</div>;
}

export function SplitCode({ children }: { children: ReactNode }) {
  return <div className="split-code">{children}</div>;
}
