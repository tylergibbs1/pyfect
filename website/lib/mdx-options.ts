import { applyMdxPreset } from 'fumadocs-mdx/config';
import { codeThemes } from './code-theme';
import { rehypeTableColumns } from './table-columns';

/** The guides' and the blog's MDX pipeline: the same code themes, includes and tables. */
export const mdxOptions = applyMdxPreset({
  rehypeCodeOptions: { themes: codeThemes },
  rehypePlugins: (plugins) => [rehypeTableColumns, ...plugins],
});
