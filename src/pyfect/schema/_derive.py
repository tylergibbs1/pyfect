"""The schema an annotation stands for, used by ``Struct`` and the schema
classes: ``str`` String, ``int`` Int, ``float`` Number, ``bool`` Boolean,
``None`` Null, ``object`` Unknown, ``Any`` Any, ``Literal[x]`` Literal, ``Literal[x, y]`` Literals,
``X | Y`` Union, an ``Enum`` Enum, a ``TypedDict`` Struct, ``dict[K, V]`` /
``Mapping[K, V]`` Record, ``list[X]`` List, ``tuple[X, ...]`` /
``Sequence[X]`` Array, ``tuple[X, Y]`` Tuple, ``frozenset[X]`` /
``AbstractSet[X]`` FrozenSet, ``Redacted[X]`` Redacted, ``timedelta``
Duration, ``JsonValue`` Json, a schema class itself; ``Annotated[T, ...]`` and
a ``NewType`` stand for ``T``, a ``type`` alias for its value. Anything
else raises ``TypeError``: give such a field its schema explicitly.
"""

from __future__ import annotations

import collections.abc
import datetime
import enum
import sys
import types
import typing
from collections.abc import Callable, Mapping
from typing import Any, cast, get_args, get_origin, get_type_hints, is_typeddict
from weakref import WeakKeyDictionary

from pyfect.redacted import Redacted as _Redacted
from pyfect.schema import ast
from pyfect.schema._arrays import Array, List, Tuple
from pyfect.schema._collections import FrozenSet
from pyfect.schema._data import Redacted
from pyfect.schema._literals import Enum, Literal, Literals, Union
from pyfect.schema._primitives import Any as AnySchema
from pyfect.schema._primitives import Boolean, Int, Null, Number, String, Unknown
from pyfect.schema._record import Record
from pyfect.schema._schema import Bottom, Codec
from pyfect.schema._values import Duration, Json, JsonValue

type AnyBottom = Bottom[Any, Any, Any, Any]

_SIMPLE: dict[object, AnyBottom] = {
    str: String,
    int: Int,
    float: Number,
    bool: Boolean,
    None: Null,
    type(None): Null,
    object: Unknown,
    Any: AnySchema,
    datetime.timedelta: Duration,
    JsonValue: Json,
}

_MAPPINGS = frozenset({dict, collections.abc.Mapping, collections.abc.MutableMapping})
_OF_ONE: dict[object, Callable[[AnyBottom], AnyBottom]] = {
    list: List,
    collections.abc.Sequence: Array,
    frozenset: FrozenSet,
    collections.abc.Set: FrozenSet,
    _Redacted: Redacted,
}
"""The schemas of the one-argument generic forms (``list[X]``, ...)."""


def schema_of(annotation: object, expanding: frozenset[object] = frozenset()) -> AnyBottom:
    """The schema ``annotation`` stands for; ``TypeError`` when none does.
    ``expanding`` holds the type aliases this annotation sits inside: one
    that refers to itself has no derived schema."""
    aliases, annotation = _unwrap(annotation)
    for alias in aliases:
        if alias in expanding:
            raise TypeError(f"The type alias {alias!r} refers to itself: give the field its schema")
    inner = expanding.union(aliases)
    simple = _SIMPLE.get(annotation) if _hashable(annotation) else None
    found = simple or _of_form(annotation, inner) or _of_class(annotation)
    if found is None:
        raise TypeError(f"No schema for the annotation {annotation!r}: give the field its schema")
    return found


def _of_form(annotation: object, expanding: frozenset[object]) -> AnyBottom | None:
    """The schema of a generic form (``Literal[...]``, ``X | Y``, ...)."""
    origin = get_origin(annotation)
    args = get_args(annotation)

    def of(arg: object) -> AnyBottom:
        return schema_of(arg, expanding)

    if origin is typing.Literal:
        return Literal(args[0]) if len(args) == 1 else Literals(*args)
    if origin is typing.Union or origin is types.UnionType:
        return Union(*map(of, args))
    if origin in _MAPPINGS and len(args) == 2:
        return Record(of(args[0]), of(args[1]))
    if origin is tuple:
        return _of_tuple(args, of)
    one = _OF_ONE.get(origin) if _hashable(origin) else None
    if one is not None and len(args) == 1:
        return one(of(args[0]))
    return None


def _of_tuple(args: tuple[object, ...], of: Callable[[object], AnyBottom]) -> AnyBottom | None:
    """``tuple[X, ...]`` an Array, ``tuple[X, Y]`` / ``tuple[()]`` a Tuple."""
    if len(args) == 2 and args[1] is Ellipsis:
        return Array(of(args[0]))
    if any(_unpacked(a) or a is Ellipsis for a in args):
        return None
    return Tuple(*map(of, args))


def _unpacked(annotation: object) -> bool:
    """``*tuple[X, ...]`` or ``Unpack[...]`` (a rest: no schema is derived)."""
    return (
        bool(getattr(annotation, "__unpacked__", False)) or get_origin(annotation) is typing.Unpack
    )


def _unwrap(annotation: object) -> tuple[tuple[object, ...], object]:
    """The type ``Annotated[T, ...]``, a ``NewType`` or a ``type`` alias
    stands for, and the aliases passed through. An alias with a schema of
    its own (``JsonValue``) is kept."""
    aliases: list[object] = []
    while True:
        if get_origin(annotation) is typing.Annotated:
            annotation = get_args(annotation)[0]
        elif isinstance(annotation, typing.NewType):
            annotation = annotation.__supertype__
        elif isinstance(annotation, typing.TypeAliasType) and annotation not in _SIMPLE:
            aliases.append(annotation)
            annotation = annotation.__value__
        else:
            return tuple(aliases), annotation


def _of_class(annotation: object) -> AnyBottom | None:
    if not isinstance(annotation, type):
        return None
    annotation = cast("type[object]", annotation)
    if issubclass(annotation, enum.Enum):
        return Enum(annotation)
    if is_typeddict(annotation):
        return Bottom(typed_dict_ast(cast("type[Mapping[str, object]]", annotation)))
    if hasattr(annotation, "__codec__"):
        return cast("Codec[Any, Any, Any, Any]", annotation).__codec__()
    return None


def _hashable(value: object) -> bool:
    try:
        hash(value)
    except TypeError:
        return False
    return True


_STRUCTS: WeakKeyDictionary[type, ast.Objects] = WeakKeyDictionary()
_BUILDING: set[type] = set()


def typed_dict_ast(
    typed_dict: type[Mapping[str, object]], fields: Mapping[str, AnyBottom] | None = None
) -> ast.AST:
    """The struct node of a TypedDict, its fields derived from its
    annotations unless given in ``fields``. A TypedDict met again while
    deriving its own fields becomes a ``Suspend`` of it."""
    if fields is None:
        cached = _STRUCTS.get(typed_dict)
        if cached is not None:
            return cached
        if typed_dict in _BUILDING:
            return ast.Suspend(lambda: _STRUCTS[typed_dict])
        _BUILDING.add(typed_dict)
        try:
            node = objects_of(typed_dict, typed_dict_fields(typed_dict, {}))
        finally:
            _BUILDING.discard(typed_dict)
        _STRUCTS[typed_dict] = node
        return node
    return objects_of(typed_dict, fields)


def typed_dict_fields(
    typed_dict: type[Mapping[str, object]], overrides: Mapping[str, AnyBottom]
) -> dict[str, AnyBottom]:
    """The schema of each key: the given one, else its annotation's."""
    hints = get_type_hints(typed_dict)
    unknown = [name for name in overrides if name not in hints]
    if unknown:
        raise TypeError(f"{typed_dict.__name__} has no key {unknown[0]!r}")
    return {
        name: overrides[name] if name in overrides else schema_of(hint)
        for name, hint in hints.items()
    }


def optional_keys(typed_dict: type[Mapping[str, object]]) -> frozenset[str]:
    """The keys that may be missing. Python's ``__optional_keys__`` misses a
    ``NotRequired`` / ``Required`` written as a string (``from __future__
    import annotations``), so the evaluated annotations decide."""
    optional = set(getattr(typed_dict, "__optional_keys__", frozenset[str]()))
    for name, hint in get_type_hints(typed_dict, include_extras=True).items():
        match _requiredness(hint):
            case "required":
                optional.discard(name)
            case "not_required":
                optional.add(name)
            case None:
                pass
    return frozenset(optional)


def _requiredness(hint: object) -> typing.Literal["required", "not_required"] | None:
    """The ``Required`` / ``NotRequired`` wrapper of a key's annotation,
    looking through ``ReadOnly`` and ``Annotated``."""
    origin = get_origin(hint)
    if origin is typing.NotRequired:
        return "not_required"
    if origin is typing.Required:
        return "required"
    if origin is typing.ReadOnly or origin is typing.Annotated:
        return _requiredness(get_args(hint)[0])
    return None


def objects_of(
    typed_dict: type[Mapping[str, object]], fields: Mapping[str, AnyBottom]
) -> ast.Objects:
    optional = optional_keys(typed_dict)
    extra = extra_items(typed_dict)
    return ast.Objects(
        tuple(
            ast.PropertySignature(name, schema.ast, optional=name in optional)
            for name, schema in fields.items()
        ),
        () if extra is None else (_extra_items_signature(frozenset(fields), extra),),
    )


def _extra_items_signature(declared: frozenset[str], extra: object) -> ast.IndexSignature:
    """The keys ``declared`` leaves out, with values of ``extra`` (PEP 728:
    unlike a TypeScript index signature, it does not cover the declared
    keys)."""

    def undeclared(key: str) -> bool:
        return key not in declared

    key = ast.append_checks(
        ast.string, (ast.make_filter(undeclared, expected="an undeclared key"),)
    )
    return ast.IndexSignature(key, schema_of(extra).ast)


def _no_extra_items() -> tuple[object, ...]:
    """PEP 728's ``NoExtraItems`` markers (``typing`` from Python 3.15, else
    ``typing_extensions``, when loaded)."""
    modules = (typing, sys.modules.get("typing_extensions"))
    markers = (getattr(m, "NoExtraItems", None) for m in modules)
    return tuple(marker for marker in markers if marker is not None)


def extra_items(typed_dict: type[Mapping[str, object]]) -> object | None:
    """The type of the keys ``typed_dict`` does not declare (PEP 728's
    ``extra_items=``, Effect's ``StructWithRest`` of a string record), or
    ``None`` when it declares none (or is ``closed``)."""
    extra = getattr(typed_dict, "__extra_items__", None)
    if extra is None or extra is typing.Never or extra in _no_extra_items():
        return None
    return get_args(extra)[0] if get_origin(extra) is typing.ReadOnly else extra
