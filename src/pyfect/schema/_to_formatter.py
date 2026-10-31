"""``to_formatter``: a schema's decoded values as text (Effect's
``Schema.toFormatter``).

Structs, tuples, arrays and classes are written part by part with their
parts' formatters (``{ "a": some(1) }``, ``[1, "a"]``, ``A({ ... })``), a
union value with the member it belongs to; a ``to_formatter`` annotation
replaces a node's own (the built-in declarations carry one: ``some(1)``,
``FrozenSet(2) { 1, 2 }``...), and ``on_before`` may take any node first.
Anything else is ``format_unknown`` (Effect's ``Formatter.format``).
"""

from __future__ import annotations

import enum
from collections.abc import Callable, Mapping, Sequence
from typing import Any, cast

from pyfect._stack import with_fresh_stack
from pyfect.logger._text import format_unknown, json_quote
from pyfect.schema import ast
from pyfect.schema._schema import Codec
from pyfect.schema._type_walk import annotation_of, class_name, index_keys, member_selector

type Formatter[A] = Callable[[A], str]
"""A value as text (Effect's ``Formatter``)."""

type FormatterAnnotation = Callable[[tuple[Formatter[Any], ...]], Formatter[Any]]
"""A ``to_formatter`` annotation: a declaration's formatter from its type
parameters' (no parameters for other nodes)."""

type OnBefore = Callable[[ast.AST, Callable[[ast.AST], Formatter[Any]]], Formatter[Any] | None]
"""Takes a node before the derivation does: its formatter, or ``None`` to
leave it to the derivation (which it may call)."""


def to_formatter[T](
    schema: Codec[T, object, object, object], /, *, on_before: OnBefore | None = None
) -> Formatter[T]:
    """``schema``'s decoded values as text (Effect's ``toFormatter``)."""
    return _Derivation(on_before)(schema.__codec__().ast)


def format_key(key: object) -> str:
    """A property key as Effect writes it: a string quoted."""
    return json_quote(key) if isinstance(key, str) else format_unknown(key)


def _format_leaf(value: object) -> str:
    # An enum member is written as its value, as Effect's enums are values.
    return format_unknown(value.value if isinstance(value, enum.Enum) else value)


class _Derivation:
    """One derivation: each node is derived once."""

    def __init__(self, on_before: OnBefore | None) -> None:
        self._on_before = on_before
        self._done: dict[int, tuple[ast.AST, Formatter[Any]]] = {}
        self._classes: dict[int, tuple[object, Formatter[Any]]] = {}

    def __call__(self, node: ast.AST) -> Formatter[Any]:
        hit = self._done.get(id(node))
        if hit is None:
            hit = (node, self._compile(node))
            self._done[id(node)] = hit
        return hit[1]

    def _compile(self, node: ast.AST) -> Formatter[Any]:
        annotation = annotation_of(node, "to_formatter")
        if callable(annotation):
            derive = cast("FormatterAnnotation", annotation)
            parameters = node.type_parameters if isinstance(node, ast.Declaration) else ()
            return derive(tuple(map(self, parameters)))
        if self._on_before is not None:
            formatter = self._on_before(node, self)
            if formatter is not None:
                return formatter
        return self._derive(node)

    def _derive(self, node: ast.AST) -> Formatter[Any]:  # noqa: PLR0911
        match node:
            case ast.Never():
                return lambda _: "never"
            case ast.Arrays():
                return self._arrays(node)
            case ast.Objects():
                return self._objects(node)
            case ast.Union():
                return self._union(node)
            case ast.Suspend():
                return self._suspend(node)
            case ast.Class():
                return self._class(node)
            case _:
                return _format_leaf

    def _arrays(self, node: ast.Arrays) -> Formatter[Sequence[object]]:
        elements = [(self(e.type), e.optional) for e in node.elements]
        rest = [self(r) for r in node.rest]

        def format(value: Sequence[object]) -> str:
            n = len(value)
            out = [element(value[i]) for i, (element, _) in enumerate(elements) if i < n]
            if rest:
                head, *tail = rest
                start = len(elements)
                post = max(start, n - len(tail))
                out += [head(value[i]) for i in range(start, post)]
                out += [tail[j](value[post + j]) for j in range(len(tail))]
            return "[" + ", ".join(out) + "]"

        return format

    def _objects(self, node: ast.Objects) -> Formatter[Any]:
        if not node.properties and not node.index_signatures:
            return format_unknown
        properties = [(p.name, self(p.type)) for p in node.properties]
        indexes = [(i, self(i.type)) for i in node.index_signatures]

        def format(value: Mapping[object, object]) -> str:
            out: list[str] = []
            visited: set[object] = set()
            for name, formatter in properties:
                visited.add(name)
                if name not in value:  # an optional key
                    continue
                out.append(f"{format_key(name)}: {formatter(value[name])}")
            for index, formatter in indexes:
                for key in index_keys(value, index):
                    if key not in visited:
                        visited.add(key)
                        out.append(f"{format_key(key)}: {formatter(value[key])}")
            return "{ " + ", ".join(out) + " }" if out else "{}"

        return format

    def _union(self, node: ast.Union) -> Formatter[object]:
        select = member_selector(node)
        members = [self(t) for t in node.types]

        def format(value: object) -> str:
            for i, guard in select(value):
                if guard(value):
                    return members[i](value)
            return format_unknown(value)

        return format

    def _suspend(self, node: ast.Suspend) -> Formatter[object]:
        target: list[Formatter[object]] = []

        def format(value: object) -> str:
            if not target:
                target.append(self(node.target))
            return with_fresh_stack(lambda: target[0](value))

        return format

    def _class(self, node: ast.Class) -> Formatter[Any]:
        match node.side:
            case "decode" | "type":
                # Derived on first use, once per class: a class may hold itself.
                shape = node.shape
                hit = self._classes.get(id(shape))
                if hit is not None:
                    return hit[1]
                fields: list[Formatter[Any]] = []
                name = class_name(node)

                def format(instance: Any) -> str:
                    if not fields:
                        fields.append(self(shape.fields.to_type()))
                    return with_fresh_stack(
                        lambda: f"{name}({fields[0](shape.values_of(instance))})"
                    )

                self._classes[id(shape)] = (shape, format)
                return format
            case "encode" | "encoded":
                return self(node.shape.encoded)
