"""Code fragments: source text that keeps its bindings until a module renders it
(Effect's ``Codegen.code``, ``join``, ``deferred``, ``indent``, ``literal``, ``docComment``)."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Sequence
from typing import Literal, final

_CANNOT_COERCE = "Code fragments must be rendered by their module"


class _Unprintable:
    """Raises on ``str()`` and f-strings, which would print ``<object ...>``:
    a fragment's text exists only once a module renders it."""

    __slots__ = ()

    def __str__(self) -> str:
        raise TypeError(_CANNOT_COERCE)


class Binding(_Unprintable):
    """A reference to a declaration or import whose identity is independent of
    its printed name. ``str()`` and f-strings raise: put it in ``code(...)``."""

    __slots__ = ("preferred_name",)

    def __init__(self, preferred_name: str) -> None:
        self.preferred_name = preferred_name

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.preferred_name!r})"


@final
class DeclarationBinding(Binding):
    """A declaration binding, with the name its module allocated."""

    __slots__ = ("name",)

    def __init__(self, preferred_name: str, name: str) -> None:
        super().__init__(preferred_name)
        self.name = name


@final
class Parts(_Unprintable):
    """Fragments rendered one after another (what ``code`` and ``join`` make)."""

    __slots__ = ("parts",)

    def __init__(self, parts: tuple[Fragment, ...]) -> None:
        self.parts = parts


@final
class Deferred(_Unprintable):
    """Source built when the module renders, from the names it allocated."""

    __slots__ = ("render",)

    def __init__(self, render: Callable[[Render], str]) -> None:
        self.render = render


type Fragment = str | Binding | Parts | Deferred
type Render = Callable[[Fragment], str]
type CodeHole = Fragment | int | float | Sequence[CodeHole] | Literal[False] | None


def _append(value: CodeHole, parts: list[Fragment]) -> None:
    if value is None or value is False or value == "":
        return
    if isinstance(value, (str, Binding, Parts, Deferred)):
        parts.append(value)
    elif isinstance(value, (int, float)):
        parts.append(str(value))
    else:
        for item in value:
            _append(item, parts)


def code(*values: CodeHole) -> Fragment:
    """Source text and bindings, concatenated without resolving names
    (Effect's ``code`` template: ``code("x = ", binding)``). Strings go in as
    written, numbers as ``str`` writes them, sequences item by item, and
    ``None`` and ``False`` as nothing."""
    parts: list[Fragment] = []
    for value in values:
        _append(value, parts)
    return Parts(tuple(parts))


def join(values: Sequence[CodeHole], separator: str) -> Fragment:
    """``values`` with ``separator`` between each two."""
    parts: list[Fragment] = []
    for index, value in enumerate(values):
        if index > 0:
            parts.append(separator)
        _append(value, parts)
    return Parts(tuple(parts))


def deferred(render: Callable[[Render], str]) -> Fragment:
    """Source built while the module renders: ``render`` gets a function that
    renders a fragment with the module's names. A fragment shared in several
    places renders once per ``finalize``."""
    return Deferred(render)


_NONEMPTY_LINE = re.compile(r"\n(?=[^\n])")


def indent(content: CodeHole) -> Fragment:
    """``content`` with every nonempty line after the first indented by four spaces."""
    fragment = code(content)
    return Deferred(lambda render: _NONEMPTY_LINE.sub("\n    ", render(fragment)))


def literal(value: str | float | None) -> str:
    """``value`` as a Python literal: strings in double quotes, ``float("nan")``
    and ``float("inf")`` for the floats without one, and ``-0.0`` kept."""
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, float):
        if math.isnan(value):
            return 'float("nan")'
        if math.isinf(value):
            return 'float("inf")' if value > 0 else '-float("inf")'
    return repr(value)


def _escape(char: str) -> str:
    if char == "\\":
        return "\\\\"
    return char if char.isprintable() else repr(char)[1:-1]


def _string(value: str) -> str:
    return '"' + "".join('\\"' if char == '"' else _escape(char) for char in value) + '"'


_LINE_BREAK = re.compile(r"\r\n?|\n")
_CLOSING_QUOTE = re.compile(r'"(?="|$)')


def doc_comment(text: str | Sequence[str]) -> str:
    """``text`` as a docstring statement ending in a newline (Effect's JSDoc
    ``docComment``), or ``""`` when it has no text. Put it first in the body it
    documents; backslashes and quotes that would end it are escaped."""
    given = [text] if isinstance(text, str) else text
    lines = [
        _CLOSING_QUOTE.sub('\\\\"', "".join(map(_escape, line.rstrip())))
        for entry in given
        for line in _LINE_BREAK.split(entry)
    ]
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    if not lines:
        return ""
    if len(lines) == 1:
        return f'"""{lines[0]}"""\n'
    return '"""' + "\n".join(lines) + '\n"""\n'
