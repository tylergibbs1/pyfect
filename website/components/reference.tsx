import { Children, type ReactNode } from 'react';

/**
 * Components for the generated API reference (fumadocs-python's MDX), laid out like
 * Stripe's API reference: the description and parameters on the left, the source in a
 * sticky panel on the right on wide screens.
 */

export function PyFunction(props: {
  name: string;
  type: string;
  kind?: 'func' | 'constructor';
  titled?: string;
  children?: ReactNode;
}) {
  return (
    <section className="py-entry">
      {props.titled ? null : <p className="py-entry-name">{props.name}</p>}
      <code className="py-signature">
        {props.name}
        {props.type}
      </code>
      <div className="py-entry-body">{props.children}</div>
    </section>
  );
}

export function PySourceCode({ children }: { children: ReactNode }) {
  return <div className="py-source">{children}</div>;
}

export function PyParameter(props: {
  name: string;
  type?: string;
  value?: string;
  children?: ReactNode;
}) {
  return (
    <div className="py-row" data-parameter="">
      <div className="py-row-head">
        <code className="py-row-name">{props.name}</code>
        {props.type ? <code className="py-row-type">{props.type}</code> : null}
        {props.value ? <code className="py-row-type">= {props.value}</code> : null}
      </div>
      <div className="py-row-doc">{props.children}</div>
    </div>
  );
}

export function PyFunctionReturn({ type, children }: { type?: string; children?: ReactNode }) {
  if ((type ?? 'None') === 'None' && Children.count(children) === 0) return null;
  return (
    <div className="py-row py-returns">
      <div className="py-row-head">
        <span className="py-row-name">Returns</span>
        <code className="py-row-type">{type ?? 'None'}</code>
      </div>
      <div className="py-row-doc">{children}</div>
    </div>
  );
}

export function PyAttributes({ children }: { children?: ReactNode }) {
  return <div className="py-rows not-prose">{children}</div>;
}

export function PyAttribute(props: {
  name: string;
  type?: string;
  value?: string;
  children?: ReactNode;
}) {
  return (
    <div className="py-row">
      <div className="py-row-head">
        <code className="py-row-name">{props.name}</code>
        {props.type ? <code className="py-row-type">{props.type}</code> : null}
        {props.value ? <code className="py-row-type">= {props.value}</code> : null}
      </div>
      <div className="py-row-doc">{props.children}</div>
    </div>
  );
}

export const referenceComponents = {
  PyFunction,
  PySourceCode,
  PyParameter,
  PyFunctionReturn,
  PyAttributes,
  PyAttribute,
};
