"""Mapping schemas: ``Struct`` (a TypedDict), ``Record`` and ``suspend``.

``Struct(UserDict)`` takes its keys and their schemas from the TypedDict:
a ``NotRequired`` key is optional, a ``ReadOnly`` one is read-only for the
type checker only (the decoded value is a new ``dict``, as Effect's
readonly keys are a TypeScript notion). A key whose annotation is not its
schema's Type (a transformation, a check) gets its schema as a keyword
argument. TypedDict inheritance, ``total=False`` and a second TypedDict
spell Effect's ``extend``, ``partial`` / ``required`` and ``pick`` / ``omit``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Generic, Never, TypeVar, overload

from pyfect.schema import ast
from pyfect.schema._derive import typed_dict_ast, typed_dict_fields
from pyfect.schema._record import RecordSchema
from pyfect.schema._schema import Bottom, Codec

# Explicit covariant parameters: a frozen dataclass's fields would make
# inferred ones invariant (``tests/test_schema_variance.py``).
TD_co = TypeVar("TD_co", bound=Mapping[str, object], covariant=True)
RD_co = TypeVar("RD_co", covariant=True)
RE_co = TypeVar("RE_co", covariant=True)


@dataclass(frozen=True, slots=True, eq=False)
class StructSchema(Bottom[TD_co, Mapping[str, object], RD_co, RE_co], Generic[TD_co, RD_co, RE_co]):
    """The schema of a TypedDict; ``fields`` maps each key to its schema."""

    fields: Mapping[str, Bottom[object, object, RD_co, RE_co]]


@overload
def Struct[TD: Mapping[str, object]](typed_dict: type[TD], /) -> StructSchema[TD, Never, Never]: ...
@overload
def Struct[TD: Mapping[str, object], RD, RE](
    typed_dict: type[TD], /, **fields: Codec[object, object, RD, RE]
) -> StructSchema[TD, RD, RE]: ...
def Struct(
    typed_dict: type[Mapping[str, object]], /, **fields: Codec[object, object, object, object]
) -> StructSchema[Any, Any, Any]:
    """A mapping with the keys of ``typed_dict`` (Effect's ``Struct``).
    Each key's schema comes from its annotation unless given here; a name
    the TypedDict lacks raises ``TypeError``, as does an annotation with no
    schema (see ``pyfect.schema`` for which annotations have one)."""
    given = {name: codec.__codec__() for name, codec in fields.items()}
    schemas = typed_dict_fields(typed_dict, given)
    node = typed_dict_ast(typed_dict, schemas if given else None)
    return StructSchema(node, schemas)


@dataclass(frozen=True, slots=True, eq=False)
class StructWithRestSchema(
    Bottom[TD_co, Mapping[str, object], RD_co, RE_co], Generic[TD_co, RD_co, RE_co]
):
    """A struct whose other keys ``records`` take."""

    schema: StructSchema[TD_co, RD_co, RE_co]
    records: tuple[RecordSchema[Any, Any, Any, Any, RD_co, RE_co], ...]


def StructWithRest[TD: Mapping[str, object], RD, RE](
    schema: StructSchema[TD, RD, RE], /, *records: RecordSchema[Any, Any, Any, Any, RD, RE]
) -> StructWithRestSchema[TD, RD, RE]:
    """``schema``'s keys, and any other key one of ``records`` takes, with
    its value (Effect's ``StructWithRest``); the checks of all of them run.
    A TypedDict is open, so its type allows the other keys; declare their
    type with ``extra_items=`` (PEP 728, ``typing_extensions.TypedDict``),
    which ``Struct`` reads as a string record by itself. A key both declare
    raises ``ValueError``, as does a struct or record with an encoding of
    its own."""
    nodes = [schema.ast, *(r.ast for r in records)]
    objects = [node for node in nodes if isinstance(node, ast.Objects)]
    if len(objects) != len(nodes):
        raise ValueError("StructWithRest does not support encodings")
    node = ast.struct_with_rest(objects[0], objects[1:])
    return StructWithRestSchema(node, schema, records)


def suspend[T, E, RD, RE](f: Callable[[], Codec[T, E, RD, RE]], /) -> Bottom[T, E, RD, RE]:
    """The schema ``f`` returns, made on first use: for a schema that
    refers to itself (Effect's ``suspend``)."""
    return Bottom(ast.Suspend(lambda: f().__codec__().ast))
