"""Reads JSON Schema objects into import nodes, and resolves ``$ref``s to the
definitions (and pointers below them) of the document."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import cast

from pyfect import schema as S
from pyfect._digits import parse_digits
from pyfect.json_pointer import escape_token, parse_uri_fragment
from pyfect.json_schema import JsonSchema, get_reference_key
from pyfect.logger._text import json_quote
from pyfect.schema import ast
from pyfect.schema._ecma_pattern import EcmaPatternError, is_ecma_pattern
from pyfect.schema.issue import Path
from pyfect.schema.representation._from import error_with_path
from pyfect.schema.representation._import import _keywords as K
from pyfect.schema.representation._import import _nodes as N
from pyfect.schema.representation._import._intersect import Intersector

_UNSUPPORTED_KEYWORDS = frozenset(
    {
        "if",
        "$dynamicRef",
        "contains",
        "dependentRequired",
        "dependentSchemas",
        "not",
        "unevaluatedItems",
        "unevaluatedProperties",
    }
)

_MAP_KEYWORDS = frozenset({"$defs", "properties", "patternProperties", "dependentSchemas"})
_ARRAY_KEYWORDS = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})
_SCHEMA_KEYWORDS = frozenset(
    {
        "not",
        "additionalProperties",
        "propertyNames",
        "unevaluatedProperties",
        "items",
        "contains",
        "unevaluatedItems",
        "if",
        "then",
        "else",
        "contentSchema",
    }
)


@dataclass(frozen=True, slots=True)
class Options:
    on_enter: Callable[[JsonSchema], JsonSchema] | None
    patterns: K.PatternMode
    include_annotation_key: Callable[[str], bool] | None


@dataclass(frozen=True, slots=True)
class _Pointer:
    target: object
    tokens: tuple[str, ...]
    crosses_resource: bool


def _child(node: object, token: str) -> object:
    """``node[token]`` as JavaScript's ``hasOwn`` reads it, arrays included."""
    if K.is_object(node):
        return node.get(token)
    if K.is_array(node):
        index = parse_digits(token, unpadded=True)
        return node[index] if index is not None and index < len(node) else None
    return None


def _filter(filter: object) -> N.Filter:
    return N.Filter(cast("ast.Filter[object]", filter))


class Translator:
    def __init__(self, definitions: Mapping[str, JsonSchema], options: Options) -> None:
        self.definitions = definitions
        self.options = options
        self.cache: dict[str, N.Node | None] = {}
        self.validated_aliases: set[str] = set()
        self.resolving_choices: set[str] = set()
        self.pointers: dict[str, _Pointer] = {}
        self.in_nested_resource = False
        self.intersector = Intersector(self)

    # ----------------------------------------------------------- definitions

    def definition(self, key: str, path: Path, recursive_error: str | None = None) -> N.Node:
        """The node of definition ``key``. ``None`` in the cache marks one
        being read: reaching it again is a cycle no value consumes."""
        if key in self.cache:
            cached = self.cache[key]
            if cached is None:
                message = recursive_error or f"Definition {json_quote(key)} is a circular alias."
                raise error_with_path(message, (*path, "$ref"))
            return cached
        self.cache[key] = None
        pointer = self.pointers.get(key)
        was_nested = self.in_nested_resource
        if pointer is None:
            node = self.schema(self.definitions[key], ("definitions", key))
        else:
            self.in_nested_resource = pointer.crosses_resource
            node = self.schema(pointer.target, ("definitions", *pointer.tokens))
        self.in_nested_resource = was_nested
        self.cache[key] = node
        if pointer is not None:
            self._validate_pointer_aliases(node, path, recursive_error, set())
        return node

    def _validate_pointer_aliases(
        self, node: N.Node, path: Path, recursive_error: str | None, visiting: set[str]
    ) -> None:
        if isinstance(node, N.Reference):
            key = node.ref
            if key in self.validated_aliases:
                return
            if key in visiting:
                raise error_with_path(
                    f"Definition {json_quote(key)} is a circular alias.", (*path, "$ref")
                )
            visiting.add(key)
            target = self.definition(key, path, recursive_error)
            self._validate_pointer_aliases(target, path, recursive_error, visiting)
            visiting.discard(key)
            self.validated_aliases.add(key)
        elif isinstance(node, N.Union):
            # Alternatives share completed checks, but only ancestors belong
            # to the active path.
            for type in node.types:
                self._validate_pointer_aliases(type, path, recursive_error, visiting)
        # Recursion through object properties or array items consumes a child value.

    def resolve_reference(
        self,
        reference: N.Reference,
        path: Path,
        recursive_error: str | None = None,
        seen: set[str] | None = None,
    ) -> N.Node:
        seen = set() if seen is None else seen
        if reference.ref in seen:
            raise error_with_path(
                f"Definition {json_quote(reference.ref)} is a circular alias.", (*path, "$ref")
            )
        seen.add(reference.ref)
        node = self.definition(reference.ref, path, recursive_error)
        if isinstance(node, N.Reference):
            resolved = self.resolve_reference(node, path, recursive_error, seen)
            return N.annotate(resolved, node)
        return node

    def has_choices_in(self, reference: N.Reference) -> bool:
        key = reference.ref
        if self.cache.get(key, reference) is None or key in self.resolving_choices:
            return True
        self.resolving_choices.add(key)
        cached = self.cache.get(key)
        node = self.definition(key, reference.path) if cached is None else cached
        out = self.intersector.has_choices(node)
        self.resolving_choices.discard(key)
        return out

    def _resolve_pointer(self, ref: str, path: Path) -> str:
        """The key of the definition a ``$ref`` below ``$defs`` stands for:
        its escaped tokens, such as ``Name/properties/field``."""
        pointer = parse_uri_fragment(ref) if ref.startswith("#") else None
        if pointer is None or len(pointer) < 3 or pointer[0] != "$defs":
            raise error_with_path(
                f'Unsupported $ref {json_quote(ref)}. Use "#/$defs/Name".', (*path, "$ref")
            )
        tokens = tuple(pointer[1:])
        key = "/".join(escape_token(token) for token in tokens)
        if key in self.definitions:
            raise error_with_path(
                f"Pointer $ref {json_quote(ref)} conflicts with definition {json_quote(key)}.",
                (*path, "$ref"),
            )
        if key in self.pointers:
            return key
        # Walks through the on_enter result of each ancestor, as reading them would.
        node: object = self.definitions
        position = "container"
        crosses_resource = False
        for token in tokens:
            if position == "container":
                position = "schema"
            elif position == "schema" and K.is_object(node):
                if self.options.on_enter is not None:
                    node = self.options.on_enter(cast("JsonSchema", node))
                crosses_resource |= K.is_object(node) and isinstance(node.get("$id"), str)
                if token in _SCHEMA_KEYWORDS:
                    position = "schema"
                else:
                    known = token in _MAP_KEYWORDS or token in _ARRAY_KEYWORDS
                    position = "container" if known else "value"
            else:
                position = "value"
            node = _child(node, token)
        if not K.is_object(node) and not isinstance(node, bool):
            raise error_with_path(
                f"Unresolvable $ref {json_quote(ref)}. Nothing exists at that location.",
                (*path, "$ref"),
            )
        self.pointers[key] = _Pointer(node, tokens, crosses_resource)
        return key

    # --------------------------------------------------------------- schemas

    def schema(self, input: object, path: Path, *, is_root: bool = False) -> N.Node:  # noqa: PLR0912
        if input is False:
            return N.NEVER
        if not K.is_object(input):
            return N.UNKNOWN
        schema = cast("JsonSchema", input)
        if self.options.on_enter is not None:
            schema = self.options.on_enter(schema)
        not_ = schema.get("not")
        if K.is_object(not_) and not not_:
            return N.annotate(N.NEVER, self._annotations(schema))
        was_nested = self.in_nested_resource
        self.in_nested_resource |= not is_root and isinstance(schema.get("$id"), str)
        for keyword in schema:
            if keyword == "if" and "then" not in schema and "else" not in schema:
                continue
            if keyword in _UNSUPPORTED_KEYWORDS:
                raise error_with_path(
                    f'Cannot import JSON Schema keyword "{keyword}": '
                    "Effect has no equivalent constraint.",
                    (*path, keyword),
                )
        intersect = self.intersector.intersect

        node = self._type(schema, path)
        if "const" in schema:
            at = (*path, "const")
            literal = K.json_literal(schema["const"], at)
            if literal is not None:
                node = intersect(node, literal, at)
        members = schema.get("enum")
        if K.is_array(members):
            types = tuple(
                K.json_literal(value, (*path, "enum", i)) or N.UNKNOWN
                for i, value in enumerate(members)
            )
            enum = types[0] if len(types) == 1 else N.Union(types=types)
            node = intersect(node, enum, (*path, "enum"))
        ref = schema.get("$ref")
        if isinstance(ref, str):
            node = self._ref(ref, node, path)
        node = N.annotate(node, self._annotations(schema))

        all_of = schema.get("allOf")
        if K.is_array(all_of):
            for index, member in enumerate(all_of):
                at = (*path, "allOf", index)
                node = intersect(node, self.schema(member, at), at)
        for keyword, mode in (("anyOf", None), ("oneOf", "one_of")):
            alternatives = schema.get(keyword)
            if K.is_array(alternatives):
                types = tuple(
                    self.schema(member, (*path, keyword, i))
                    for i, member in enumerate(alternatives)
                )
                union = N.Union(types=types, mode=cast("ast.UnionMode | None", mode))
                node = intersect(union, node, (*path, keyword))
        self.in_nested_resource = was_nested
        return node

    def _annotations(self, schema: JsonSchema) -> N.ImportedAnnotations:
        return K.annotations_of(schema, self.options.include_annotation_key)

    def _ref(self, ref: str, node: N.Node, path: Path) -> N.Node:
        if self.in_nested_resource:
            raise error_with_path(
                'Cannot resolve $ref under a nested "$id". Resolve or flatten it first.',
                (*path, "$ref"),
            )
        key = get_reference_key(ref)
        if key is not None and key not in self.definitions:
            raise error_with_path(
                f"Missing definition {json_quote(key)} for $ref {json_quote(ref)}.", (*path, "$ref")
            )
        reference = N.Reference(
            ref=self._resolve_pointer(ref, path) if key is None else key, path=path
        )
        if isinstance(node, N.Unknown):
            return reference
        if isinstance(node, N.Never):
            return N.NEVER
        message = f"Recursive $ref {json_quote(reference.ref)} cannot have sibling constraints."
        return self.intersector.intersect(
            self.resolve_reference(reference, path, message), node, path
        )

    def _type(self, schema: JsonSchema, path: Path) -> N.Node:  # noqa: PLR0911
        declared = schema.get("type")
        types: tuple[object, ...] | None = None
        if K.is_array(declared) and all(K.is_type_name(t) for t in declared):
            types = tuple(declared)
        elif not K.is_type_name(declared) and K.has_type_specific_keywords(schema):
            types = K.VALUE_TYPES
        if types is not None:
            return N.Union(
                types=tuple(self._type({**schema, "type": type}, path) for type in types)
            )
        match declared if K.is_type_name(declared) else None:
            case "null":
                return N.Null()
            case "string":
                return N.String(checks=self._string_checks(schema, path))
            case "number":
                return N.Number(checks=(_filter(S.is_finite()), *_number_checks(schema)))
            case "integer":
                return N.Number(checks=(_filter(S.is_int()), *_number_checks(schema)))
            case "boolean":
                return N.Boolean()
            case "array":
                return self._array(schema, path)
            case "object":
                scope = self._object_scope(schema, path)
                checked: N.CheckedFields = {
                    "checks": self._object_checks(schema, path),
                    "annotations": None,
                    "custom_annotations": None,
                }
                return self.intersector.lower_object((scope,), checked, path)
            case _:
                return N.UNKNOWN

    def _array(self, schema: JsonSchema, path: Path) -> N.Arrays:
        prefix_items = schema.get("prefixItems")
        prefix = tuple(prefix_items) if K.is_array(prefix_items) else None
        min_items = schema.get("minItems")
        minimum = min_items if K.is_number(min_items) else 0
        elements = tuple(
            N.Element(self.schema(element, (*path, "prefixItems", i)), i + 1 > minimum)
            for i, element in enumerate(prefix or ())
        )
        items = schema.get("items")
        max_items = schema.get("maxItems")
        is_closed = items is False or (
            "items" not in schema
            and prefix is not None
            and K.is_number(max_items)
            and max_items == len(prefix)
        )
        is_max_items_redundant = is_closed and K.is_number(max_items) and max_items >= len(elements)
        rest = None
        if not is_closed:
            rest = N.UNKNOWN if "items" not in schema else self.schema(items, (*path, "items"))
        checks: list[N.Check] = []
        if prefix is None or (K.is_number(min_items) and min_items > len(prefix)):
            _add_number(checks, min_items, S.is_min_length)
        if not is_max_items_redundant:
            _add_number(checks, max_items, S.is_max_length)
        if schema.get("uniqueItems") is True:
            checks.append(_filter(S.is_unique()))
        return N.Arrays(elements=elements, rest=rest, checks=tuple(checks))

    def _pattern(self, source: str, path: Path) -> N.Filter | None:
        match self.options.patterns:
            case "error":
                raise error_with_path(
                    "Patterns may block validation and are disabled. Use patterns: "
                    '"apply" for trusted schemas or "ignore" to discard them.',
                    path,
                )
            case "ignore":
                return None
            case "apply":
                try:
                    return _filter(is_ecma_pattern(source))
                except EcmaPatternError as error:
                    raise error_with_path(str(error), path) from None

    def _string_checks(self, schema: JsonSchema, path: Path) -> tuple[N.Check, ...]:
        checks: list[N.Check] = []
        min_length = schema.get("minLength")
        if min_length == 1:
            _add_number(checks, min_length, S.is_min_length)
        else:
            _add_number(checks, min_length, S.is_min_code_points)
        _add_number(checks, schema.get("maxLength"), S.is_max_code_points)
        pattern = schema.get("pattern")
        if isinstance(pattern, str):
            check = self._pattern(pattern, (*path, "pattern"))
            if check is not None:
                checks.append(check)
        return tuple(checks)

    def _object_scope(self, schema: JsonSchema, path: Path) -> N.ObjectScope:
        declared = schema.get("properties")
        source: Mapping[str, object] = declared if K.is_object(declared) else {}
        required = K.strings_of(schema.get("required"))
        properties = {
            name: N.ObjectProperty(
                self.schema(source[name], (*path, "properties", name)) if name in source else None,
                name not in required,
            )
            for name in dict.fromkeys((*source, *required))
        }
        has_properties = bool(source)
        patterns: list[N.ObjectPattern] = []
        declared_patterns = schema.get("patternProperties")
        if K.is_object(declared_patterns):
            for pattern, value in declared_patterns.items():
                at = (*path, "patternProperties", pattern)
                check = self._pattern(pattern, at)
                if check is None:
                    return N.ObjectScope(properties, has_properties, (), N.UNKNOWN)
                parameter = N.String(checks=(check,))
                patterns.append(N.ObjectPattern(pattern, parameter, self.schema(value, at)))
        additional = schema.get("additionalProperties")
        additional_node: N.Node = N.UNKNOWN
        if additional is False:
            additional_node = N.NEVER
        elif K.is_object(additional):
            additional_node = self.schema(additional, (*path, "additionalProperties"))
        return N.ObjectScope(properties, has_properties, tuple(patterns), additional_node)

    def _object_checks(self, schema: JsonSchema, path: Path) -> tuple[N.Check, ...]:
        checks: list[N.Check] = []
        _add_number(checks, schema.get("minProperties"), S.is_min_properties)
        _add_number(checks, schema.get("maxProperties"), S.is_max_properties)
        if "propertyNames" in schema:
            at = (*path, "propertyNames")
            type = self.intersector.intersect(
                N.STRING, self.schema(schema["propertyNames"], at), at
            )
            checks.append(N.PropertyNames(type))
        return tuple(checks)


def _add_number(checks: list[N.Check], value: object, make: Callable[[float], object]) -> None:
    if K.is_number(value):
        checks.append(_filter(make(value)))


def _number_checks(schema: JsonSchema) -> tuple[N.Check, ...]:
    checks: list[N.Check] = []
    _add_number(checks, schema.get("minimum"), S.is_greater_than_or_equal_to)
    _add_number(checks, schema.get("maximum"), S.is_less_than_or_equal_to)
    _add_number(checks, schema.get("exclusiveMinimum"), S.is_greater_than)
    _add_number(checks, schema.get("exclusiveMaximum"), S.is_less_than)
    _add_number(checks, schema.get("multipleOf"), S.is_multiple_of)
    return tuple(checks)
