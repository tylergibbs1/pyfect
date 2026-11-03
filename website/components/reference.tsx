import Link from 'next/link';
import { Children, isValidElement, type ReactNode } from 'react';
import { CodeCollapsible } from './code-collapsible';

/**
 * Components for the generated API reference (fumadocs-python's MDX), styled like a
 * shadcn/ui docs page: a signature block, the description, a parameter table in the
 * typeset table style, and the source behind "Expand".
 */

function Signature({ children }: { children: ReactNode }) {
  return (
    <figure data-code-figure="" data-not-typeset="">
      <pre className="no-scrollbar overflow-x-auto px-4 py-3.5">
        <code className="font-mono text-sm whitespace-pre-wrap">{children}</code>
      </pre>
    </figure>
  );
}

function Table({ head, children }: { head: string; children: ReactNode }) {
  return (
    <div className="typeset-scroll no-scrollbar *:[table]:w-full">
      <table>
        <thead>
          <tr>
            <th>{head}</th>
            <th>Type</th>
            <th>Description</th>
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

function Row(props: { name: string; type?: string; value?: string; children?: ReactNode }) {
  return (
    <tr>
      <td>
        <code>{props.name}</code>
      </td>
      <td>
        {props.type ? <code>{props.type}</code> : null}
        {props.value ? (
          <>
            {props.type ? ' ' : null}
            <code>= {props.value}</code>
          </>
        ) : null}
      </td>
      <td>{props.children}</td>
    </tr>
  );
}

export function PyParameter(props: { name: string; type?: string; value?: string; children?: ReactNode }) {
  return <Row {...props} />;
}

export function PyAttribute(props: { name: string; type?: string; value?: string; children?: ReactNode }) {
  return <Row {...props} />;
}

export function PyAttributes({ children }: { children?: ReactNode }) {
  return <Table head="Attribute">{children}</Table>;
}

export function PyFunctionReturn({ type, children }: { type?: string; children?: ReactNode }) {
  if ((type ?? 'None') === 'None' && Children.count(children) === 0) return null;
  // An overloaded function has no single return type: its signatures show each one.
  if (type === undefined) return <>{children}</>;
  return (
    <>
      <p>
        Returns <code>{type ?? 'None'}</code>
      </p>
      {children}
    </>
  );
}

/** Lines in rendered shiki output (`<span class="line">`). */
function countLines(node: ReactNode): number {
  return Children.toArray(node).reduce<number>((total, child) => {
    if (!isValidElement<{ className?: string; children?: ReactNode }>(child)) return total;
    const self = child.props.className?.split(' ').includes('line') ? 1 : 0;
    return total + self + countLines(child.props.children);
  }, 0);
}

/** The source; a long one starts collapsed, as shadcn shows long component sources. */
export function PySourceCode({ children }: { children: ReactNode }) {
  return countLines(children) > 12 ? <CodeCollapsible>{children}</CodeCollapsible> : children;
}

export function PyFunction(props: {
  name: string;
  type: string;
  kind?: 'func' | 'constructor';
  titled?: string;
  children?: ReactNode;
}) {
  const parameters: ReactNode[] = [];
  const rest: ReactNode[] = [];
  for (const child of Children.toArray(props.children)) {
    // fumadocs-python wraps the parameters in a <div>
    const inner = isValidElement<{ children?: ReactNode }>(child) && child.type === 'div' ? Children.toArray(child.props.children) : [];
    if (inner.length > 0 && inner.every((c) => isValidElement(c) && c.type === PyParameter)) parameters.push(...inner);
    else if (isValidElement(child) && child.type === PyParameter) parameters.push(child);
    else rest.push(child);
  }

  return (
    <>
      {props.titled ? null : (
        <h4>
          <code>{props.name}</code>
        </h4>
      )}
      <Signature>
        {/* one line per overload */}
        {props.type
          .split('\n')
          .map((line) => props.name + line)
          .join('\n')}
      </Signature>
      {rest.filter((child) => !(isValidElement(child) && (child.type === PyFunctionReturn || child.type === PySourceCode)))}
      {parameters.length > 0 ? <Table head="Parameter">{parameters}</Table> : null}
      {rest.filter((child) => isValidElement(child) && child.type === PyFunctionReturn)}
      {rest.filter((child) => isValidElement(child) && child.type === PySourceCode)}
    </>
  );
}

/** Links to classes and submodules, as shadcn/ui lists its components. */
export function Cards({ children }: { children?: ReactNode }) {
  return (
    <div data-not-typeset="" className="mt-6 grid grid-cols-2 gap-4 md:grid-cols-3 md:gap-x-8 lg:gap-y-6">
      {children}
    </div>
  );
}

export function Card({ title, href }: { title: ReactNode; href: string }) {
  return (
    <Link href={href} className="inline-flex items-center gap-2 text-lg font-medium underline-offset-4 hover:underline md:text-base">
      {title}
    </Link>
  );
}

export const referenceComponents = {
  Cards,
  Card,
  PyFunction,
  PySourceCode,
  PyParameter,
  PyFunctionReturn,
  PyAttributes,
  PyAttribute,
};
