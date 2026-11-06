"""The conjunction of two import nodes: ``allOf`` members, siblings of ``$ref``,
``enum`` and ``const`` with what they constrain."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import NoReturn, Protocol, cast

from pyfect.schema import ast
from pyfect.schema._ecma_pattern import compile_ecma
from pyfect.schema.issue import Path
from pyfect.schema.representation._from import error_with_path
from pyfect.schema.representation._import import _nodes as N

_NULL, _STRING, _NUMBER, _BOOLEAN, _OBJECTS, _ARRAYS = 1, 2, 4, 8, 16, 32
_ALL = 63

_UNSUPPORTED_UNION = (
    'Cannot intersect these "anyOf" or "oneOf" alternatives without expanding their branches.'
)


class Definitions(Protocol):
    """How intersecting reads definitions (``_translate.Translator``)."""

    def resolve_reference(self, reference: N.Reference, path: Path) -> N.Node: ...

    def has_choices_in(self, reference: N.Reference) -> bool: ...


def _same_literal(left: object, right: object) -> bool:
    """JavaScript's ``===`` over JSON primitives: ``True`` is not ``1``."""
    return isinstance(left, bool) == isinstance(right, bool) and left == right


def _satisfies_check(check: N.Check, value: str | int | float) -> bool:
    match check:
        case N.FilterGroup(checks=checks):
            return all(_satisfies_check(c, value) for c in checks)
        case N.Filter(filter=filter):
            return filter.run(value, ast.unknown, {}) is None
        case N.PropertyNames():
            return False


def _satisfies_literal(node: N.String | N.Number, literal: N.Literal) -> bool:
    value = literal.literal
    if isinstance(value, bool) or isinstance(value, str) != isinstance(node, N.String):
        return False
    return all(_satisfies_check(check, value) for check in node.checks)


def _representation_id(check: N.Check) -> object:
    if not isinstance(check, N.Filter):
        return None
    representation = (check.filter.annotations or {}).get("representation")
    if not isinstance(representation, Mapping):
        return None
    return cast("Mapping[str, object]", representation).get("id")


def _intersect_checks(
    left: N.Checked, right: N.Checked, deduplicate: tuple[str, ...] = ()
) -> N.CheckedFields:
    """The ``checks`` and annotations of the conjunction: ``right``'s
    annotations describe its checks, or the value when none is left."""
    checks = right.checks
    for id in deduplicate:
        if any(_representation_id(c) == id for c in left.checks):
            checks = tuple(c for c in checks if _representation_id(c) != id)
    annotations = (
        N.merge_annotations(left.annotations, right.annotations) if not checks else left.annotations
    )
    if checks and right.annotations is not None:
        if len(checks) == 1 and checks[0].annotations is None:
            checks = (replace(checks[0], annotations=right.annotations),)
        else:
            first, *rest = checks
            checks = (N.FilterGroup((first, *rest), right.annotations),)
    return {
        "checks": (*left.checks, *checks),
        "annotations": annotations,
        "custom_annotations": N.merge_annotations(
            left.custom_annotations, right.custom_annotations
        ),
    }


def root_mask(node: N.Node) -> int:  # noqa: PLR0911
    """The JSON root types ``node`` may accept, as a bit set."""
    match node:
        case N.Never():
            return 0
        case N.Unknown() | N.Reference():
            return _ALL
        case N.Literal(literal=literal):
            if isinstance(literal, bool):
                return _BOOLEAN
            return _STRING if isinstance(literal, str) else _NUMBER
        case N.Union(types=types):
            out = 0
            for t in types:
                out |= root_mask(t)
            return out
        case N.Null():
            return _NULL
        case N.String():
            return _STRING
        case N.Number():
            return _NUMBER
        case N.Boolean():
            return _BOOLEAN
        case N.Objects():
            return _OBJECTS
        case N.Arrays():
            return _ARRAYS


def _literal_key(node: N.Node) -> tuple[str, object] | None:
    """A map key standing for a literal's value (``None`` for any other node),
    keeping ``True`` and ``1`` apart."""
    if isinstance(node, N.Null):
        return ("null", None)
    if not isinstance(node, N.Literal):
        return None
    return ("boolean" if isinstance(node.literal, bool) else "value", node.literal)


def _unsupported(path: Path) -> NoReturn:
    raise error_with_path(_UNSUPPORTED_UNION, path)


def _make_union(source: N.Union, types: tuple[N.Node, ...]) -> N.Node:
    if not types:
        return N.NEVER
    if len(types) == 1 and not source.checks:
        return N.annotate(types[0], source)
    return replace(source, types=types)


def _is_type_partition(union: N.Union) -> bool:
    mask = 0
    for t in union.types:
        member = root_mask(t)
        if mask & member:
            return False
        mask |= member
    return True


def _annotated(node: N.ImportedAnnotations) -> bool:
    return node.annotations is not None or node.custom_annotations is not None


class Intersector:
    def __init__(self, definitions: Definitions) -> None:
        self.definitions = definitions

    def intersect(self, left: N.Node, right: N.Node, path: Path) -> N.Node:  # noqa: PLR0911
        if isinstance(left, N.Never):
            return left
        if isinstance(right, N.Never):
            return right
        if isinstance(left, N.Unknown):
            return self._both(right, left, right)
        if isinstance(right, N.Unknown):
            return self._both(left, left, right)
        if isinstance(left, N.Reference):
            # An unannotated reference resolves first: an annotated empty
            # definition could otherwise leave the other one unresolved during
            # union partitioning.
            if _annotated(left) and isinstance(right, N.Reference) and not _annotated(right):
                resolved = self.definitions.resolve_reference(right, path)
                return self.intersect(left, resolved, path)
            resolved = self.definitions.resolve_reference(left, path)
            return N.annotate(self.intersect(resolved, right, path), left)
        if isinstance(right, N.Reference):
            resolved = self.definitions.resolve_reference(right, path)
            return N.annotate(self.intersect(left, resolved, path), right)
        if isinstance(left, N.Union):
            if isinstance(right, N.Union):
                return self._unions(left, right, path)
            return self._union_with_type(left, right, path, union_on_left=True)
        if isinstance(right, N.Union):
            return self._union_with_type(right, left, path, union_on_left=False)
        return self._plain(left, right, path)

    def all(self, types: list[N.Node], path: Path) -> N.Node:
        out = types[0] if types else N.UNKNOWN
        for index, node in enumerate(types[1:], start=1):
            out = self.intersect(out, node, (*path, index))
        return out

    def _both(
        self, node: N.Node, left: N.ImportedAnnotations, right: N.ImportedAnnotations
    ) -> N.Node:
        return N.annotate(N.annotate(node, left), right)

    def _plain(self, left: N.Node, right: N.Node, path: Path) -> N.Node:  # noqa: PLR0911, PLR0912
        match left:
            case N.Null():
                if isinstance(right, N.Null):
                    return self._both(N.Null(checks=(*left.checks, *right.checks)), left, right)
                return N.NEVER
            case N.String():
                if isinstance(right, N.Literal):
                    return self._primitive_with_literal(left, right)
                if not isinstance(right, N.String):
                    return N.NEVER
                return N.String(**_intersect_checks(left, right))
            case N.Number():
                if isinstance(right, N.Literal):
                    return self._primitive_with_literal(left, right)
                if not isinstance(right, N.Number):
                    return N.NEVER
                checks = _intersect_checks(
                    left, right, ("effect/schema/isFinite", "effect/schema/isInt")
                )
                return N.Number(**checks)
            case N.Boolean():
                if isinstance(right, N.Literal):
                    return self._primitive_with_literal(left, right)
                if isinstance(right, N.Boolean):
                    return self._both(N.Boolean(checks=(*left.checks, *right.checks)), left, right)
                return N.NEVER
            case N.Literal():
                return self._literal_with(left, right)
            case N.Arrays():
                if not isinstance(right, N.Arrays):
                    return N.NEVER
                arrays = self._arrays(left, right, path)
                if arrays is None:
                    return N.NEVER
                elements, rest = arrays
                checks = _intersect_checks(left, right, ("effect/schema/isUnique",))
                return N.Arrays(elements=elements, rest=rest, **checks)
            case N.Objects():
                if not isinstance(right, N.Objects):
                    return N.NEVER
                return self.lower_object(
                    (*left.scopes, *right.scopes), _intersect_checks(left, right), path
                )
            case _:
                raise AssertionError(left)

    def _literal_with(self, left: N.Literal, right: N.Node) -> N.Node:
        if isinstance(right, N.Literal):
            if not _same_literal(left.literal, right.literal):
                return N.NEVER
            return self._both(replace(left, checks=(*left.checks, *right.checks)), left, right)
        satisfied = (
            isinstance(right, N.String | N.Number) and _satisfies_literal(right, left)
        ) or (isinstance(right, N.Boolean) and isinstance(left.literal, bool))
        return self._both(left, left, right) if satisfied else N.NEVER

    def _primitive_with_literal(
        self, primitive: N.String | N.Number | N.Boolean, literal: N.Literal
    ) -> N.Node:
        satisfied = (
            isinstance(literal.literal, bool)
            if isinstance(primitive, N.Boolean)
            else _satisfies_literal(primitive, literal)
        )
        return self._both(literal, primitive, literal) if satisfied else N.NEVER

    def _arrays(
        self, left: N.Arrays, right: N.Arrays, path: Path
    ) -> tuple[tuple[N.Element, ...], N.Node | None] | None:
        elements: list[N.Element] = []
        for index in range(max(len(left.elements), len(right.elements))):
            left_element = left.elements[index] if index < len(left.elements) else None
            right_element = right.elements[index] if index < len(right.elements) else None
            is_optional = (left_element is None or left_element.is_optional) and (
                right_element is None or right_element.is_optional
            )
            left_type = left.rest if left_element is None else left_element.type
            right_type = right.rest if right_element is None else right_element.type
            if left_type is None or right_type is None:
                return (tuple(elements), None) if is_optional else None
            type = self.intersect(left_type, right_type, (*path, "elements", index, "type"))
            if isinstance(type, N.Never):
                return (tuple(elements), None) if is_optional else None
            elements.append(N.Element(type, is_optional))
        if left.rest is None or right.rest is None:
            return tuple(elements), None
        rest = self.intersect(left.rest, right.rest, (*path, "rest", 0))
        return tuple(elements), None if isinstance(rest, N.Never) else rest

    def lower_object(  # noqa: PLR0912
        self, scopes: tuple[N.ObjectScope, ...], checked: N.CheckedFields, path: Path
    ) -> N.Node:
        names: dict[str, None] = {}
        has_finite_key_domain = False
        requires_finite_key_domain = False
        for scope in scopes:
            names.update(dict.fromkeys(scope.properties))
            additional = scope.additional_properties
            has_finite_key_domain |= isinstance(additional, N.Never) and not scope.patterns
            requires_finite_key_domain |= isinstance(additional, N.Never) or (
                not isinstance(additional, N.Unknown)
                and (scope.has_properties or bool(scope.patterns))
            )
        closed_pattern = (
            scopes[0].patterns[0]
            if len(scopes) == 1
            and not names
            and isinstance(scopes[0].additional_properties, N.Never)
            and len(scopes[0].patterns) == 1
            else None
        )
        if not has_finite_key_domain and requires_finite_key_domain and closed_pattern is None:
            closed = any(isinstance(s.additional_properties, N.Never) for s in scopes)
            raise error_with_path(
                "Cannot import this closed patterned object: "
                "only one pattern without properties is supported."
                if closed
                else 'Cannot combine typed "additionalProperties" with other property schemas: '
                "Effect index signatures also check excluded keys.",
                path,
            )

        properties: list[N.Property] = []
        for name in names:
            is_optional = True
            types: list[N.Node] = []
            for scope in scopes:
                property = scope.properties.get(name)
                if property is not None:
                    is_optional = is_optional and property.is_optional
                    if property.type is not None:
                        types.append(property.type)
                matches = False
                for pattern in scope.patterns:
                    if compile_ecma(pattern.source).search(name) is not None:
                        types.append(pattern.type)
                        matches = True
                if (property is None or property.type is None) and not matches:
                    types.append(scope.additional_properties)
            type = self.all(types, (*path, "properties", name))
            if not is_optional and isinstance(type, N.Never):
                return N.NEVER
            properties.append(N.Property(name, type, is_optional))

        index_signature = None
        if closed_pattern is not None:
            index_signature = N.IndexSignature(closed_pattern.parameter, closed_pattern.type)
        elif not has_finite_key_domain:
            additional = [s.additional_properties for s in scopes]
            index_signature = N.IndexSignature(
                N.STRING, self.all(additional, (*path, "additionalProperties"))
            )
        elif not properties:
            index_signature = N.IndexSignature(N.STRING, N.NEVER)
        return N.Objects(
            property_signatures=tuple(properties),
            index_signature=index_signature,
            scopes=scopes,
            path=path,
            **checked,
        )

    def has_choices(self, node: N.Node) -> bool:
        match node:
            case N.Reference():
                return self.definitions.has_choices_in(node)
            case N.Union(types=types):
                return len(types) > 1 or any(self.has_choices(t) for t in types)
            case N.Arrays(elements=elements, rest=rest):
                return any(self.has_choices(e.type) for e in elements) or (
                    rest is not None and self.has_choices(rest)
                )
            case N.Objects():
                index = node.index_signature
                return (
                    any(self.has_choices(p.type) for p in node.property_signatures)
                    or (
                        index is not None
                        and (self.has_choices(index.parameter) or self.has_choices(index.type))
                    )
                    or any(self.has_choices(p.type) for s in node.scopes for p in s.patterns)
                    or any(self._check_has_choices(c) for c in node.checks)
                )
            case _:
                return False

    def _check_has_choices(self, check: N.Check) -> bool:
        match check:
            case N.FilterGroup(checks=checks):
                return any(self._check_has_choices(c) for c in checks)
            case N.PropertyNames(type=type):
                return self.has_choices(type)
            case N.Filter():
                return False

    def _literal_unions(self, left: N.Union, right: N.Union, path: Path) -> N.Node | None:
        if (left.mode or "any_of") != "any_of" or (right.mode or "any_of") != "any_of":
            return None
        by_value: dict[tuple[str, object], N.Node] = {}
        for node in right.types:
            key = _literal_key(node)
            if key is None:
                return None
            previous = by_value.get(key)
            by_value[key] = replace(
                node,
                custom_annotations=N.merge_annotations(
                    None if previous is None else previous.custom_annotations,
                    node.custom_annotations,
                ),
            )
        types: list[N.Node] = []
        for node in left.types:
            key = _literal_key(node)
            if key is None:
                return None
            match = by_value.get(key)
            if match is not None:
                types.append(self.intersect(node, N.annotate(match, right), path))
        return _make_union(left, tuple(types))

    def _union_with_type(
        self, union: N.Union, type: N.Node, path: Path, *, union_on_left: bool
    ) -> N.Node:
        mask = root_mask(type)
        members = [(i, m) for i, m in enumerate(union.types) if root_mask(m) & mask]
        if len(members) > 1 and self.has_choices(type):
            _unsupported(path)

        def member_with(index: int, member: N.Node) -> N.Node:
            at = (*path, "types", index)
            if union_on_left:
                return self.intersect(member, type, at)
            return self.intersect(type, member, at)

        if len(members) == 1 and not union.checks:
            index, member = members[0]
            return member_with(index, N.annotate(member, union))
        out = (member_with(i, m) for i, m in members)
        return _make_union(union, tuple(t for t in out if not isinstance(t, N.Never)))

    def _partition(
        self, partition: N.Union, other: N.Union, path: Path, *, partition_on_left: bool
    ) -> N.Node:
        for type in other.types:
            mask = root_mask(type)
            overlapping = [m for m in partition.types if root_mask(m) & mask]
            if len(overlapping) > 1 and self.has_choices(type):
                _unsupported(path)
        types: list[N.Node] = []
        for index, member in enumerate(partition.types):
            type = self._union_with_type(
                other, member, (*path, "types", index), union_on_left=not partition_on_left
            )
            if not isinstance(type, N.Never):
                types.append(type)
        return _make_union(partition, tuple(types))

    def _unions(self, left: N.Union, right: N.Union, path: Path) -> N.Node:
        literals = self._literal_unions(left, right, path)
        if literals is not None:
            return literals
        if _is_type_partition(left):
            return self._partition(left, right, path, partition_on_left=True)
        if _is_type_partition(right):
            return self._partition(right, left, path, partition_on_left=False)
        _unsupported(path)
