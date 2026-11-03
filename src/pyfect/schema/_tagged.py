"""Tagged structs and unions (Effect's ``TaggedStruct``, ``tagDefaultOmit``,
``toTaggedUnion`` and ``TaggedUnion``).

A case of a tagged union is a schema whose values hold a literal under the
tag key: a ``TaggedClass`` (its ``_tag`` attribute) or a struct of a
TypedDict with a ``_tag: Literal["A"]`` key (a ``TaggedStruct``). The
union keeps each case by its literal (``cases``, ``guards``,
``is_any_of``); a value is matched with Python's ``match`` statement,
which pyright checks for exhaustiveness (``case _: assert_never(shape)``)::

    Shape = S.TaggedUnion(Circle, Square)  # TaggedClass cases
    match shape:
        case Circle(radius=r): ...
        case Square(): ...

A TypedDict case is matched on its tag alone (``case {"_tag": "Circle"}:``):
pyright does not narrow a mapping pattern that also captures keys.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import (
    Any,
    Generic,
    Never,
    TypeGuard,
    TypeVar,
    cast,
    get_args,
    get_origin,
    get_type_hints,
    overload,
)
from typing import Literal as TypingLiteral

from pyfect._js import js_number
from pyfect.effect import succeed
from pyfect.schema._constructor_default import tag
from pyfect.schema._derive import optional_keys
from pyfect.schema._literals import LiteralValue as LiteralInput
from pyfect.schema._literals import Union, UnionSchema
from pyfect.schema._middleware import with_decoding_default_key
from pyfect.schema._parse import is_
from pyfect.schema._schema import Codec
from pyfect.schema._struct import Struct, StructSchema
from pyfect.schema._transform import DecodeToSchema, to_type
from pyfect.schema.ast import LiteralValue
from pyfect.schema.ast._candidates import sentinels

# Explicit covariant parameters: a frozen dataclass's fields would make
# inferred ones invariant (``tests/test_schema_variance.py``).
TD_co = TypeVar("TD_co", bound=Mapping[str, object], covariant=True)
A_co = TypeVar("A_co", covariant=True)
I_co = TypeVar("I_co", covariant=True)
RD_co = TypeVar("RD_co", covariant=True)
RE_co = TypeVar("RE_co", covariant=True)


@dataclass(frozen=True, slots=True, eq=False)
class TaggedStructSchema(StructSchema[TD_co, RD_co, RE_co], Generic[TD_co, RD_co, RE_co]):
    """A struct whose ``"_tag"`` key holds ``tag``."""

    tag: LiteralValue


@overload
def TaggedStruct[TD: Mapping[str, object]](
    typed_dict: type[TD], /
) -> TaggedStructSchema[TD, Never, Never]: ...
@overload
def TaggedStruct[TD: Mapping[str, object], RD, RE](
    typed_dict: type[TD], /, **fields: Codec[object, object, RD, RE]
) -> TaggedStructSchema[TD, RD, RE]: ...
def TaggedStruct(
    typed_dict: type[Mapping[str, object]], /, **fields: Codec[object, object, object, object]
) -> TaggedStructSchema[Any, Any, Any]:
    """``Struct(typed_dict, **fields)`` of a TypedDict whose ``_tag`` key
    is one literal (``_tag: Literal["A"]``), a case of a tagged union
    (Effect's ``TaggedStruct``); ``make`` fills the tag in (``S.tag``)
    unless ``fields`` give the ``_tag`` schema. Any other ``_tag`` raises
    ``TypeError``."""
    hint = get_type_hints(typed_dict).get("_tag")
    literals = get_args(hint) if get_origin(hint) is TypingLiteral else ()
    if len(literals) != 1 or "_tag" in optional_keys(typed_dict):
        raise TypeError(f'{typed_dict.__name__} needs a required "_tag" key of one literal')
    struct = Struct(typed_dict, **{"_tag": tag(literals[0]), **fields})
    return TaggedStructSchema(struct.ast, struct.fields, literals[0])


def tag_default_omit[L: LiteralInput](literal: L, /) -> DecodeToSchema[L, L, Never, Never]:
    """A ``"_tag"`` field holding ``literal``, filled in when decoding a
    mapping without it and left out when encoding (Effect's
    ``tagDefaultOmit``): ``S.Struct(A, _tag=S.tag_default_omit("A"))``;
    ``make`` fills it in too (``S.tag``)."""
    return tag(literal).pipe(with_decoding_default_key(succeed(literal), encoding_strategy="omit"))


@dataclass(frozen=True, slots=True, eq=False)
class TaggedUnionSchema(UnionSchema[A_co, I_co, RD_co, RE_co], Generic[A_co, I_co, RD_co, RE_co]):
    """A union of cases told apart by the literal under ``tag``:
    ``discriminants`` are the literals in member order, ``cases`` and
    ``guards`` the case schema and its type guard by literal."""

    tag: str
    discriminants: tuple[LiteralValue, ...]
    cases: Mapping[LiteralValue, Codec[A_co, I_co, RD_co, RE_co]]
    guards: Mapping[LiteralValue, Callable[[object], TypeGuard[A_co]]]

    def is_any_of[A](
        self: TaggedUnionSchema[A, Any, Any, Any], *literals: LiteralValue
    ) -> Callable[[A], bool]:
        """Whether a value of the union is one of the cases of ``literals``."""
        tag = self.tag

        def test(value: A) -> bool:
            found = _tag_of(value, tag)
            return any(type(found) is type(lit) and found == lit for lit in literals)

        return test


def _tag_of(value: object, tag: str) -> object:
    if isinstance(value, Mapping):
        return cast("Mapping[object, object]", value).get(tag)
    return getattr(value, tag, None)


def _key(literal: object) -> str | None:
    """A literal's key as a property key (Effect's: ``1`` and ``"1"`` are
    one key); ``None`` for a literal that is no key (a boolean, ``None``)."""
    if isinstance(literal, str):
        return literal
    if isinstance(literal, int | float) and not isinstance(literal, bool):
        return js_number(literal)
    return None


def _guard[A](member: Codec[A, object, object, object]) -> Callable[[object], TypeGuard[A]]:
    test = is_(to_type(member))

    def guard(value: object, /) -> TypeGuard[A]:
        return test(value)

    return guard


class ToTaggedUnion:
    """``to_tagged_union(tag)``: apply with ``.pipe`` to a ``UnionSchema``."""

    __slots__ = ("_tag",)

    def __init__(self, tag: str) -> None:
        self._tag = tag

    def __call__[A, I, RD, RE](
        self, union: UnionSchema[A, I, RD, RE], /
    ) -> TaggedUnionSchema[A, I, RD, RE]:
        tag = self._tag
        discriminants: list[LiteralValue] = []
        cases: dict[LiteralValue, Codec[A, I, RD, RE]] = {}
        keys: set[str] = set()

        def walk(member: Codec[A, I, RD, RE]) -> None:
            if isinstance(member, UnionSchema):
                nested: UnionSchema[A, I, RD, RE] = member
                for inner in nested.members:
                    walk(inner)
                return
            found = [lit for key, lit in sentinels(member.__codec__().ast) if key == tag]
            key = _key(found[0]) if found else None
            if key is None:
                raise ValueError("No literal or unique symbol found")
            if key in keys:
                raise ValueError(f"Duplicate discriminant: {key}")
            keys.add(key)
            discriminants.append(found[0])
            cases[found[0]] = member

        for member in union.members:
            walk(member)
        guards = {literal: _guard(case) for literal, case in cases.items()}
        return TaggedUnionSchema(union.ast, union.members, tag, tuple(discriminants), cases, guards)


def to_tagged_union(tag: str, /) -> ToTaggedUnion:
    """The union with its cases kept by the literal each holds under
    ``tag``, nested unions' cases included (Effect's ``toTaggedUnion``).
    A case without a string or number literal there raises ``ValueError``,
    as does a literal two cases share (``1`` and ``"1"`` are one)."""
    return ToTaggedUnion(tag)


def TaggedUnion[A = Never, I = Never, RD = Never, RE = Never](
    *cases: Codec[A, I, RD, RE],
) -> TaggedUnionSchema[A, I, RD, RE]:
    """The union of ``cases`` told apart by ``"_tag"`` (Effect's
    ``TaggedUnion``): each a ``TaggedClass``, a ``TaggedStruct`` or any
    schema with a ``"_tag"`` literal."""
    return to_tagged_union("_tag")(Union(*cases))
