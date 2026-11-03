"""Struct key transformations (Effect's ``encodeKeys`` and ``extendTo``)::

S.Struct(A).pipe(S.encode_keys({"a": "c"}))  # {"a": 1} <-> {"c": "1"}
S.Struct(A).pipe(S.extend_to(B, {"c": lambda a: Some(a["a"])}))
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from pyfect._equal import dedupe
from pyfect._json_text import stringify
from pyfect.option import Option, is_some
from pyfect.schema import ast
from pyfect.schema._schema import Bottom, Codec
from pyfect.schema._struct import Struct, StructSchema
from pyfect.schema._transform import DecodeToSchema, to_type
from pyfect.schema.transformation import transform


def _renamed(mapping: Mapping[str, str], value: Mapping[str, object]) -> dict[str, object]:
    return {mapping.get(key, key): item for key, item in value.items()}


class EncodeKeys:
    """``encode_keys(mapping)``: apply with ``.pipe`` to a struct or class."""

    __slots__ = ("_mapping",)

    def __init__(self, mapping: Mapping[str, str]) -> None:
        self._mapping = dict(mapping)

    def __call__[T, RD, RE](
        self, schema: Codec[T, Mapping[str, object], RD, RE], /
    ) -> Bottom[T, Mapping[str, object], RD, RE]:
        node = schema.__codec__().ast
        encoded = ast.to_encoded(node)
        if isinstance(encoded, ast.Class):
            encoded = encoded.shape.encoded
        if not isinstance(encoded, ast.Objects):
            msg = f"encode_keys needs a struct or class, got {encoded.tag}"
            raise TypeError(msg)
        unknown = [key for key in self._mapping if all(p.name != key for p in encoded.properties)]
        if unknown:
            msg = f"Unknown keys in encode_keys mapping: {stringify(unknown)}"
            raise ValueError(msg)
        names = [self._mapping.get(str(p.name), p.name) for p in encoded.properties]
        if len(dedupe(names)) != len(names):
            msg = f"Duplicate encoded keys in {stringify(self._mapping)}"
            raise ValueError(msg)
        source = replace(
            encoded,
            properties=tuple(
                replace(p, name=name) for p, name in zip(encoded.properties, names, strict=True)
            ),
        )
        back = {encoded_name: name for name, encoded_name in self._mapping.items()}
        renaming = transform(
            decode=lambda value: _renamed(back, value),
            encode=lambda value: _renamed(self._mapping, value),
        )
        return Bottom(ast.decode_to(source, node, renaming))


def encode_keys(mapping: Mapping[str, str], /) -> EncodeKeys:
    """The struct's keys renamed on the encoded side, ``{key: encoded
    key}`` (Effect's ``encodeKeys``). Two keys encoding to one name, or a
    mapping key that is not a field, raise ``ValueError``."""
    return EncodeKeys(mapping)


class ExtendTo[TD: Mapping[str, object], A: Mapping[str, object]]:
    """``extend_to(typed_dict, derive)``: apply with ``.pipe`` to a struct."""

    __slots__ = ("_derive", "_fields", "_typed_dict")

    def __init__(
        self,
        typed_dict: type[TD],
        derive: Mapping[str, Callable[[A], Option[object]]],
        fields: Mapping[str, Codec[object, object, Any, Any]],
    ) -> None:
        self._typed_dict = typed_dict
        self._derive = dict(derive)
        self._fields = dict(fields)

    def _decode(self, value: A) -> TD:
        out: dict[str, object] = dict(value)
        for key, derive in self._derive.items():
            derived = derive(value)
            if is_some(derived):
                out[key] = derived.value
        return out  # pyright: ignore[reportReturnType]  # checked by the target struct

    def _encode(self, value: TD) -> A:
        out = {key: item for key, item in value.items() if key not in self._derive}
        return out  # pyright: ignore[reportReturnType]  # checked by the source struct

    def __call__[RD, RE](
        self, schema: StructSchema[A, RD, RE], /
    ) -> DecodeToSchema[TD, Mapping[str, object], RD, RE]:
        kept = {name: to_type(field) for name, field in schema.fields.items()}
        target = Struct(self._typed_dict, **kept, **self._fields)
        new = [key for key in target.fields if key not in kept]
        if set(new) != set(self._derive):
            msg = (
                f"extend_to derives {stringify(list(self._derive))}, new keys are {stringify(new)}"
            )
            raise ValueError(msg)
        transformation = transform(decode=self._decode, encode=self._encode)
        node = ast.decode_to(schema.__codec__().ast, target.__codec__().ast, transformation)
        return DecodeToSchema(node, schema, target)


def extend_to[TD: Mapping[str, object], A: Mapping[str, object]](
    typed_dict: type[TD],
    derive: Mapping[str, Callable[[A], Option[object]]],
    /,
    **fields: Codec[object, object, Any, Any],
) -> ExtendTo[TD, A]:
    """The struct decoded into ``typed_dict``, a struct with its keys and
    more, each new key ``derive[key](value)`` when that is ``Some``; the
    new keys are dropped when encoding (Effect's ``extendTo``). A new key's
    schema comes from its annotation unless given in ``fields``; ``derive``
    must have exactly the new keys (else ``ValueError``)."""
    return ExtendTo(typed_dict, derive, fields)
