"""The codec of a structured output: a schema's canonical JSON form with
the shapes providers' strict JSON Schema modes cannot express rewritten
(Effect's ``internal/structured-output.ts``, ``toCodec``).

A tuple becomes an object with keys ``"0"``, ``"1"``, ... (and
``"__rest__"`` / ``"__tail_N__"`` for its rest), an object with index
signatures an array of ``[key, value]`` pairs, an optional key a required
nullable one, a ``one_of`` union an ``any_of`` one. Each rewrite decodes back
to the original shape, so the original schema's checks still run on the
decoded value; a check that has a JSON Schema fragment is kept, as a no-op,
on the rewritten node for the JSON Schema compiler.
"""

from __future__ import annotations

import operator
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any, NamedTuple, cast

from pyfect.ai import _structured_output_checks as C
from pyfect.json_schema import JsonSchema
from pyfect.option import Option, Some
from pyfect.schema import Bottom, Codec, to_codec_json
from pyfect.schema import ast as A
from pyfect.schema.transformation import (
    Transformation,
    passthrough,
    transform,
    transform_optional,
)

_PASSTHROUGH: Transformation[object, object] = passthrough()
_REST = "__rest__"
_RECORD_DESCRIPTION = (
    "Object encoded as array of [key, value] pairs. Apply object constraints to the decoded object"
)
_TUPLE_DESCRIPTION = (
    "Tuple encoded as an object with numeric string keys ('0', '1', ...). "
    "If present, '__rest__' contains remaining elements"
)
_TUPLE_TAIL_DESCRIPTION = (
    f"{_TUPLE_DESCRIPTION}. Post-rest elements use '__tail_0__', '__tail_1__', and so on"
)


class StructuredOutputCodec[T, RD, RE](NamedTuple):
    """What a provider's structured-output transformer gives: the codec
    decoding the model's output into ``T`` and the JSON Schema to send. The
    codec stays the authority: the JSON Schema may accept more than it."""

    codec: Codec[T, object, RD, RE]
    json_schema: JsonSchema


def _tail(index: int) -> str:
    return f"__tail_{index}__"


def to_codec[T, E, RD, RE](schema: Codec[T, E, RD, RE]) -> Codec[T, object, RD, RE]:
    """``schema`` decoding from the provider-safe shape of its JSON form;
    ``schema`` itself when nothing is rewritten."""
    original = schema.__codec__().ast
    json_codec = to_codec_json(schema)
    encoded = A.to_encoded(json_codec.ast)
    rewritten = _Rewrite()(encoded)
    if rewritten is encoded:
        return schema if json_codec.ast is original else json_codec
    return Bottom[T, object, RD, RE](A.decode_to(rewritten, json_codec.ast, _PASSTHROUGH))


class _Rewrite:
    def __init__(self) -> None:
        self._suspended: dict[int, A.Suspend] = {}

    def __call__(self, node: A.AST) -> A.AST:
        match node:
            case A.Union():
                mode = "any_of" if node.mode == "one_of" else node.mode
                return _rebuild(node, types=tuple(map(self, node.types)), mode=mode)
            case A.Arrays():
                if node.elements or len(node.rest) > 1:
                    return self._tuple_to_object(node)
                return _rebuild(node, rest=tuple(map(self, node.rest)))
            case A.Objects():
                return self._objects(node)
            case A.Suspend():
                return self._suspend(node)
            case _:
                return _rebuild(node)

    def _objects(self, node: A.Objects) -> A.AST:
        if _is_empty_params(node):
            return node
        if node.index_signatures:
            return self._object_to_entries(node)
        return _rebuild(node, properties=tuple(map(self._property, node.properties)))

    def _suspend(self, node: A.Suspend) -> A.Suspend:
        """One rewritten copy per node, so a recursive schema stays a
        finite graph."""
        cached = self._suspended.get(id(node))
        if cached is None:

            def thunk() -> A.AST:
                return self(node.target)

            cached = replace(node, thunk=thunk)
            self._suspended[id(node)] = cached
        return cached

    def _property(self, prop: A.PropertySignature) -> A.PropertySignature:
        type = self(prop.type)
        if prop.optional:
            return A.PropertySignature(prop.name, _optional_to_nullable(type), True, None, False)
        return prop if type is prop.type else replace(prop, type=type)

    def _tuple_to_object(self, node: A.Arrays) -> A.AST:
        elements, rest = node.elements, node.rest
        properties = [
            A.PropertySignature(str(i), element.type, element.optional)
            for i, element in enumerate(elements)
        ]
        if rest:
            properties.append(A.PropertySignature(_REST, _list(rest[0])))
            properties.extend(
                A.PropertySignature(_tail(i), rest[i + 1]) for i in range(len(rest) - 1)
            )
        description = _TUPLE_TAIL_DESCRIPTION if len(rest) > 1 else _TUPLE_DESCRIPTION
        from_ = self(
            A.Objects(
                properties=tuple(properties),
                annotations=C.structural_annotations(node, description),
                checks=C.compiler_checks(node.checks),
            )
        )
        tail_length = max(len(rest) - 1, 0)

        def decode(obj: Mapping[str, object]) -> list[object]:
            out = [obj[str(i)] for i in range(len(elements)) if str(i) in obj]
            if _REST in obj:
                out.extend(cast("Sequence[object]", obj[_REST]))
            out.extend(obj[_tail(i)] for i in range(tail_length))
            return out

        def encode(values: Sequence[object]) -> dict[str, object]:
            out: dict[str, object] = {
                str(i): values[i] for i in range(min(len(elements), len(values)))
            }
            if rest:
                end = max(len(elements), len(values) - tail_length)
                out[_REST] = list(values[len(elements) : end])
                for i in range(tail_length):
                    out[_tail(i)] = values[end + i]
            return out

        return A.decode_to(from_, node, transform(decode=decode, encode=encode))

    def _object_to_entries(self, node: A.Objects) -> A.AST:
        key = _union_or_single(
            [A.Literal(cast("str", p.name)) for p in node.properties]
            + [i.parameter for i in node.index_signatures]
        )
        value = _union_or_single(
            [p.type for p in node.properties] + [i.type for i in node.index_signatures]
        )
        from_ = self(
            A.Arrays(
                rest=(A.Arrays(elements=(A.Element(key), A.Element(value)), mutable=True),),
                mutable=True,
                annotations=C.structural_annotations(node, _RECORD_DESCRIPTION),
                checks=A.join_checks(C.record_checks(node.checks), C.compiler_checks(node.checks)),
            )
        )

        def decode(entries: Sequence[Sequence[object]]) -> dict[object, object]:
            return {entry[0]: entry[1] for entry in entries}

        def encode(obj: Mapping[object, object]) -> list[list[object]]:
            return [[k, v] for k, v in obj.items()]

        return A.decode_to(from_, node, transform(decode=decode, encode=encode))


def _rebuild[N: A.AST](node: N, **parts: Any) -> N:
    """``node`` with ``parts`` and its checks prepared; ``node`` itself when
    each part is the one it has."""
    parts["checks"] = C.prepare_checks(node.checks)
    if all(_same(getattr(node, name), part) for name, part in parts.items()):
        return node
    return replace(node, **parts)


def _same(a: object, b: object) -> bool:
    if isinstance(a, tuple) and isinstance(b, tuple):
        items_a, items_b = cast("tuple[object, ...]", a), cast("tuple[object, ...]", b)
        return len(items_a) == len(items_b) and all(map(operator.is_, items_a, items_b))
    return a is b


def _list(item: A.AST) -> A.Arrays:
    return A.Arrays(rest=(item,), mutable=True)


def _is_empty_params(node: A.Objects) -> bool:
    """Effect's ``Tool.isEmptyParamsRecord``: ``Record(String, Never)``."""
    if node.properties or len(node.index_signatures) != 1:
        return False
    index = node.index_signatures[0]
    return index.parameter is A.string and isinstance(index.type, A.Never)


def _union_or_single(types: list[A.AST]) -> A.AST:
    unique = list({id(t): t for t in types}.values())
    return unique[0] if len(unique) == 1 else A.Union(tuple(unique))


def _optional_to_nullable(type: A.AST) -> A.AST:
    """``type`` as an optional key decoded from a required nullable one."""

    def decode(value: Option[object]) -> Option[object]:
        return None if value is None or value.value is None else value

    def encode(value: Option[object]) -> Option[object]:
        return Some(None) if value is None else value

    return A.decode_to(
        A.Union((type, A.null)), type, transform_optional(decode=decode, encode=encode)
    )
