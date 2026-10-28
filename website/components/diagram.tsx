import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { render } from 'pele';

/**
 * A diagram from `diagrams/<name>.mmd` (Mermaid syntax), drawn to SVG by pele at build
 * time. It is drawn twice, for the prose column (640px) and for phones, and CSS shows
 * the one that fits, so nothing is measured or redrawn in the browser and the page
 * never shifts. Colors are pele's CSS variables, set from the theme in global.css.
 */
const WIDTHS = { wide: 640, narrow: 358 } as const;

export function Diagram({ name, title }: { name: string; title: string }) {
  const source = readFileSync(join(process.cwd(), 'diagrams', `${name}.mmd`), 'utf8');
  const draw = (width: number) =>
    render(source, {
      maxWidth: width,
      // a wide left-to-right chart turns vertical rather than shrinking its text
      directionBreakpoint: WIDTHS.wide + 60,
      idPrefix: `diagram-${name}-${width}`,
      fontFamily: 'Geist, ui-sans-serif, system-ui, sans-serif',
      fontSize: 14,
    }).svg;

  return (
    <figure data-diagram="" data-not-typeset="" role="group" aria-label={title} className="diagram">
      <div className="diagram-wide" dangerouslySetInnerHTML={{ __html: draw(WIDTHS.wide) }} />
      <div className="diagram-narrow" dangerouslySetInnerHTML={{ __html: draw(WIDTHS.narrow) }} />
    </figure>
  );
}
