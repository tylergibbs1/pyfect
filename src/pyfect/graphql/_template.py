"""Joining and slicing a ``DocumentTemplate`` without a GraphQL parser
(Effect's ``internal/graphql`` printer): ``join_template`` gives the
document a template was split from, and ``render_slices`` repeats it once
per alias prefix."""

from __future__ import annotations

import re
from collections.abc import Sequence

from pyfect.graphql.template import DocumentTemplate, Fragment, Parts

_WORD_END = re.compile(r'[\w"-]$')
_WORD_START = re.compile(r'^[\w"-]')


def _concat(left: str, right: str) -> str:
    """Two printed pieces, with a space only where two non-punctuators
    would touch (the generator printer's rule)."""
    if _WORD_END.search(left) and _WORD_START.search(right):
        return f"{left} {right}"
    return left + right


def _concat_all(pieces: Sequence[str]) -> str:
    joined = ""
    for piece in pieces:
        joined = _concat(joined, piece)
    return joined


def _render_parts(parts: Parts, prefix: str) -> str:
    return "".join(prefix + part if i % 2 == 1 else part for i, part in enumerate(parts))


def _is_shared(fragment: Fragment) -> bool:
    return len(fragment.body) <= 1


def _render(kind: str, name: str, template: DocumentTemplate, prefixes: Sequence[str]) -> str:
    variables = (
        ""
        if not template.variables
        else "("
        + _concat_all(
            [
                f"${prefix}{variable.name}:{variable.body}"
                for prefix in prefixes
                for variable in template.variables
            ]
        )
        + ")"
    )
    selections: list[str] = []
    for prefix in prefixes:
        for selection in template.selections:
            key = (
                selection.alias if prefix == "" else f"{prefix}{selection.alias or selection.name}"
            )
            head = "" if key is None else f"{key}:"
            selections.append(
                f"{head}{selection.name or ''}{_render_parts(selection.body, prefix)}"
            )
    fragments = [
        _concat_all(["fragment", prefix + fragment.name, _render_parts(fragment.body, prefix)])
        for fragment in template.fragments
        for prefix in ([""] if _is_shared(fragment) else prefixes)
    ]
    directives = "" if template.directives is None else _render_parts(template.directives, "")
    return _concat_all(
        [kind, name, variables, directives, "{" + _concat_all(selections) + "}", *fragments]
    )


def join_template(kind: str, name: str, template: DocumentTemplate) -> str:
    """The document ``template`` was split from."""
    return _render(kind, name, template, [""])


def unsliceable_reason(template: DocumentTemplate) -> str | None:
    """Why ``template`` cannot be repeated under aliases, if it cannot."""
    if template.directives is not None and len(template.directives) > 1:
        return "its operation directives reference variables"
    if any(selection.name is None for selection in template.selections):
        return "it has a fragment spread or inline fragment at the root"
    return None


def render_slices(kind: str, name: str, template: DocumentTemplate, prefixes: Sequence[str]) -> str:
    """One operation repeating ``template`` once per prefix: each slice's
    variables, root response keys and per-slice fragments are renamed with
    its prefix; directives and shared fragments appear once. No prefix may
    be a prefix of another. Raises ``ValueError`` for an unsliceable
    template or a renamed fragment taking a shared fragment's name."""
    shared = {fragment.name for fragment in template.fragments if _is_shared(fragment)}
    collision = next(
        (
            prefix + fragment.name
            for fragment in template.fragments
            if not _is_shared(fragment)
            for prefix in prefixes
            if prefix + fragment.name in shared
        ),
        None,
    )
    reason = unsliceable_reason(template) or (
        None if collision is None else f"fragment {collision} would collide with a shared fragment"
    )
    if reason is not None:
        raise ValueError(f"Cannot render slices of operation {name}: {reason}")
    return _render(kind, name, template, prefixes)
