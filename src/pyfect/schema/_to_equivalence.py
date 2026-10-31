"""``to_equivalence``: when two values of a schema's decoded side are the
same (Effect's ``Schema.toEquivalence``).

Structs, tuples and arrays compare part by part with their parts'
equivalences, a union with the member both values belong to, a class by
its fields; a ``to_equivalence`` annotation replaces a node's own (the
built-in declarations carry one: ``Option``, ``Result``, ``Cause``, sets,
maps, ``Redacted``...). Anything else is ``pyfect._equal.equals``: Python
``==``, except that ``bool`` is not a number and ``NaN`` equals ``NaN``, as
Effect's ``Equal.equals``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, cast

from pyfect._equal import equals
from pyfect._stack import with_fresh_stack
from pyfect.schema import ast
from pyfect.schema._schema import Codec
from pyfect.schema._type_walk import annotation_of, index_keys, member_selector

type Equivalence[A] = Callable[[A, A], bool]
"""Whether two values are the same (Effect's ``Equivalence``)."""

type EquivalenceAnnotation = Callable[[tuple[Equivalence[Any], ...]], Equivalence[Any]]
"""A ``to_equivalence`` annotation: a declaration's equivalence from its
type parameters' (no parameters for other nodes)."""


def to_equivalence[T](schema: Codec[T, object, object, object], /) -> Equivalence[T]:
    """When two values of ``schema``'s decoded side are the same (Effect's
    ``toEquivalence``)."""
    return _Derivation()(schema.__codec__().ast)


def same_items[A](equivalence: Equivalence[A]) -> Equivalence[Iterable[A]]:
    """Two collections holding equivalent items, each matched once, in any
    order (Effect's ``Equal.makeCompareSet``)."""

    def compare(a: Iterable[A], b: Iterable[A]) -> bool:
        remaining = list(b)
        for item in a:
            for i, other in enumerate(remaining):
                if equivalence(item, other):
                    remaining[i] = remaining[-1]
                    remaining.pop()
                    break
            else:
                return False
        return not remaining

    return compare


class _Derivation:
    """One derivation: each node is derived once."""

    def __init__(self) -> None:
        self._done: dict[int, tuple[ast.AST, Equivalence[Any]]] = {}
        self._classes: dict[int, tuple[object, Equivalence[Any]]] = {}

    def __call__(self, node: ast.AST) -> Equivalence[Any]:
        hit = self._done.get(id(node))
        if hit is None:
            hit = (node, self._derive(node))
            self._done[id(node)] = hit
        return hit[1]

    def _derive(self, node: ast.AST) -> Equivalence[Any]:  # noqa: PLR0911
        annotation = annotation_of(node, "to_equivalence")
        if callable(annotation):
            derive = cast("EquivalenceAnnotation", annotation)
            parameters = node.type_parameters if isinstance(node, ast.Declaration) else ()
            return derive(tuple(map(self, parameters)))
        match node:
            case ast.Never():
                return lambda a, b: a is b
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
                return equals

    def _arrays(self, node: ast.Arrays) -> Equivalence[object]:
        elements = [self(e.type) for e in node.elements]
        rest = [self(r) for r in node.rest]

        def equivalent(a: object, b: object) -> bool:
            if not isinstance(a, list | tuple) or not isinstance(b, list | tuple):
                return False
            a = cast("Sequence[object]", a)
            b = cast("Sequence[object]", b)
            if len(a) != len(b):
                return False
            n = len(a)
            fixed = min(n, len(elements))
            if not all(elements[i](a[i], b[i]) for i in range(fixed)):
                return False
            if not rest:
                return True
            head, *tail = rest
            post = max(fixed, n - len(tail))
            return all(head(a[i], b[i]) for i in range(fixed, post)) and all(
                tail[j](a[post + j], b[post + j]) for j in range(len(tail))
            )

        return equivalent

    def _objects(self, node: ast.Objects) -> Equivalence[Any]:
        if not node.properties and not node.index_signatures:
            return equals
        properties = [(p.name, p.optional, self(p.type)) for p in node.properties]
        indexes = [(i, self(i.type)) for i in node.index_signatures]

        def equivalent(a: object, b: object) -> bool:
            if not isinstance(a, Mapping) or not isinstance(b, Mapping):
                return False
            a = cast("Mapping[object, object]", a)
            b = cast("Mapping[object, object]", b)
            for name, optional, equivalence in properties:
                a_has, b_has = name in a, name in b
                if optional and a_has != b_has:
                    return False
                if a_has and b_has and not equivalence(a[name], b[name]):
                    return False
            for index, equivalence in indexes:
                keys = index_keys(a, index)
                if len(keys) != len(index_keys(b, index)):
                    return False
                if not all(key in b and equivalence(a[key], b[key]) for key in keys):
                    return False
            return True

        return equivalent

    def _union(self, node: ast.Union) -> Equivalence[object]:
        select = member_selector(node)
        members = [self(t) for t in node.types]

        def equivalent(a: object, b: object) -> bool:
            for i, guard in select(a):
                if guard(a) and guard(b):
                    return members[i](a, b)
            return False

        return equivalent

    def _suspend(self, node: ast.Suspend) -> Equivalence[object]:
        target: list[Equivalence[object]] = []

        def equivalent(a: object, b: object) -> bool:
            if not target:
                target.append(self(node.target))
            return with_fresh_stack(lambda: target[0](a, b))

        return equivalent

    def _class(self, node: ast.Class) -> Equivalence[Any]:
        match node.side:
            case "decode" | "type":
                # Derived on first use, once per class: a class may hold itself.
                shape = node.shape
                hit = self._classes.get(id(shape))
                if hit is not None:
                    return hit[1]
                fields: list[Equivalence[Any]] = []

                def equivalent(a: Any, b: Any) -> bool:
                    if not fields:
                        fields.append(self(shape.fields.to_type()))
                    values_of = shape.values_of
                    return with_fresh_stack(lambda: fields[0](values_of(a), values_of(b)))

                self._classes[id(shape)] = (shape, equivalent)
                return equivalent
            case "encode" | "encoded":
                return self(node.shape.encoded)
