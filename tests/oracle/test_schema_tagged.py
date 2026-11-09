"""Ports of Effect's tagged struct and union titles (``tag``,
``tagDefaultOmit``, ``Tagged unions``) and the ``Opaque`` titles from
``schema/Schema.test.ts``. Each test's docstring is the Effect test title,
prefixed by its ``describe`` blocks. ``TestSchema.Asserts`` is
``testing.SchemaAsserts``.

Python mappings: a case is a TypedDict with a ``_tag: Literal["A"]`` key
(``S.TaggedStruct(A)``, Effect's ``TaggedStruct("A", {...})``) or an
``S.TaggedClass``; ``Schema.TaggedUnion({A: {...}, ...})`` is
``S.TaggedUnion(*cases)`` and ``Union([...]).pipe(toTaggedUnion(tag))`` is
``S.Union(...).pipe(S.to_tagged_union(tag))``. ``match`` / ``matchOrElse``
are Python's ``match`` statement (pyright checks it is exhaustive, pinned
in ``tests/type_checks.py``); a ``match`` over the union's cases is ported
as one. ``cases`` holds a case under its literal only (``cases[1]``, not
also ``cases["1"]``). Effect's ``Opaque`` (a nominal struct type) is
``S.Class``: a TypedDict cannot be made nominal (``NewType`` rejects it and
a TypedDict subclass stays structural; ``research/typing/schema_4_tagged.py``).

Omitted:
- The "tag / ..." titles: ported in ``test_schema_constructor_default.py``.
- Symbols: "Tagged unions / toTaggedUnion / should expose a symbol tag";
  the symbol case of "... / should augment a union of structs" is a string.
- "Opaque / returns the original schema": there is no ``Opaque`` to return
  it (see above).
"""

from datetime import UTC, datetime
from typing import Literal, TypedDict, assert_never

import pytest

from pyfect import effect as fx
from pyfect import schema as S
from pyfect.schema import getter as G
from pyfect.schema import transformation as T
from pyfect.testing import SchemaAsserts

# ------------------------------------------------------------------- tag


class _TagA(TypedDict):
    _tag: Literal["a"]
    a: float


def test_tag_decoding_required_encoding_required_constructor_required():
    """tag / decoding: required & encoding: required & constructor: required"""
    asserts = SchemaAsserts(S.Struct(_TagA, a=S.FiniteFromString))
    asserts.make().succeed({"_tag": "a", "a": 1})
    asserts.decoding().succeed({"_tag": "a", "a": "1"}, {"_tag": "a", "a": 1})
    asserts.encoding().succeed({"_tag": "a", "a": 1}, {"_tag": "a", "a": "1"})


def test_tag_decoding_required_encoding_required_constructor_optional():
    """tag / decoding: required & encoding: required & constructor: optional"""
    asserts = SchemaAsserts(S.Struct(_TagA, _tag=S.tag("a"), a=S.FiniteFromString))
    make = asserts.make()
    make.succeed({"_tag": "a", "a": 1})
    make.succeed({"a": 1}, {"_tag": "a", "a": 1})
    asserts.decoding().succeed({"_tag": "a", "a": "1"}, {"_tag": "a", "a": 1})
    asserts.encoding().succeed({"_tag": "a", "a": 1}, {"_tag": "a", "a": "1"})


def test_tag_decoding_default_encoding_omit_constructor_optional():
    """tag / decoding: default & encoding: omit & constructor: optional"""
    tag = S.tag("a").pipe(
        S.encode_to(
            S.optional_key(S.Literal("a")),
            T.Transformation(G.with_default(fx.succeed("a")), G.omit()),
        )
    )
    asserts = SchemaAsserts(S.Struct(_TagA, _tag=tag, a=S.FiniteFromString))
    make = asserts.make()
    make.succeed({"_tag": "a", "a": 1})
    make.succeed({"a": 1}, {"_tag": "a", "a": 1})
    decoding = asserts.decoding()
    decoding.succeed({"_tag": "a", "a": "1"}, {"_tag": "a", "a": 1})
    decoding.succeed({"a": "1"}, {"_tag": "a", "a": 1})
    asserts.encoding().succeed({"_tag": "a", "a": 1}, {"a": "1"})


def test_tagdefaultomit():
    """tagDefaultOmit"""
    asserts = SchemaAsserts(S.Struct(_TagA, _tag=S.tag_default_omit("a"), a=S.FiniteFromString))

    make = asserts.make()
    make.succeed({"_tag": "a", "a": 1})
    make.succeed({"a": 1}, {"_tag": "a", "a": 1})
    make.fail({"_tag": "c", "a": 1}, 'Expected "a"\n  at ["_tag"]')

    decoding = asserts.decoding()
    decoding.succeed({"_tag": "a", "a": "1"}, {"_tag": "a", "a": 1})
    decoding.succeed({"a": "1"}, {"_tag": "a", "a": 1})
    decoding.fail({"_tag": "c", "a": 1}, 'Expected "a"\n  at ["_tag"]')

    encoding = asserts.encoding()
    encoding.succeed({"_tag": "a", "a": 1}, {"a": "1"})
    encoding.succeed({"a": 1}, {"a": "1"})


# --------------------------------------------------------- Tagged unions


class _A(TypedDict):
    _tag: Literal["A"]
    a: str


class _B(TypedDict):
    _tag: Literal["B"]
    b: float


class _One(TypedDict):
    _tag: Literal[1]
    c: bool


class _D(TypedDict):
    _tag: Literal["D"]
    d: datetime


type _Case = _A | _B | _One | _D


def _match(value: _Case) -> str:
    match value:
        case {"_tag": "A"}:
            return "A"
        case {"_tag": "B"}:
            return "B"
        case {"_tag": 1}:
            return "C"
        case {"_tag": "D"}:
            return "D"
        case _:
            assert_never(value)


def _match_or_else(value: _Case) -> object:
    match value:
        case {"_tag": "A"}:
            return "A"
        case _:
            return value["_tag"]


def test_tagged_unions_totaggedunion_should_augment_a_union_of_structs():
    """Tagged unions / toTaggedUnion / should augment a union of structs"""
    b = S.Struct(_B, b=S.FiniteFromString)
    nested = S.Union(S.Struct(_One), S.Struct(_D, d=S.DateTimeUtc))
    schema = S.Union(S.Struct(_A), b, nested).pipe(S.to_tagged_union("_tag"))
    date = datetime(2021, 1, 1, tzinfo=UTC)

    assert schema.discriminants == ("A", "B", 1, "D")

    # cases
    assert schema.cases["A"] is schema.members[0]
    assert schema.cases["B"] is b
    assert schema.cases[1] is nested.members[0]
    assert schema.cases["D"] is nested.members[1]

    # isAnyOf
    is_a_or_1 = schema.is_any_of("A", 1)
    assert is_a_or_1({"_tag": "A", "a": "a"})
    assert is_a_or_1({"_tag": 1, "c": True})
    assert not is_a_or_1({"_tag": "D", "d": date})
    assert not is_a_or_1({"_tag": "B", "b": 1})

    # guards
    assert schema.guards["A"]({"_tag": "A", "a": "a"})
    assert not schema.guards["A"]({"_tag": "A", "a": 1})
    assert schema.guards["B"]({"_tag": "B", "b": 1})
    assert not schema.guards["B"]({"_tag": "B", "b": "b"})
    assert schema.guards[1]({"_tag": 1, "c": True})
    assert not schema.guards[1]({"_tag": 1, "c": 1})
    assert schema.guards["D"]({"_tag": "D", "d": date})
    assert not schema.guards["D"]({"_tag": "D", "d": "d"})

    # match
    assert _match({"_tag": "A", "a": "a"}) == "A"
    assert _match({"_tag": "B", "b": 1}) == "B"
    assert _match({"_tag": 1, "c": True}) == "C"
    assert _match({"_tag": "D", "d": date}) == "D"

    # matchOrElse
    assert _match_or_else({"_tag": "A", "a": "a"}) == "A"
    assert _match_or_else({"_tag": "B", "b": 1}) == "B"


class _TypeA(TypedDict):
    _tag: Literal["A"]
    type: Literal["TypeA"]
    a: str


class _TypeB(TypedDict):
    _tag: Literal["B"]
    type: Literal["TypeB"]
    b: float


def test_tagged_unions_totaggedunion_should_support_multiple_tags():
    """Tagged unions / toTaggedUnion / should support multiple tags"""
    a, b = S.Struct(_TypeA), S.Struct(_TypeB, b=S.FiniteFromString)
    schema = S.Union(a, b).pipe(S.to_tagged_union("type"))
    assert schema.tag == "type"
    assert schema.cases["TypeA"] is a
    assert schema.cases["TypeB"] is b


class _EventA(TypedDict):
    event: Literal["A"]
    a: str


class _EventB(TypedDict):
    event: Literal["B"]
    b: str


class _EventAgain(TypedDict):
    event: Literal["A"]
    c: str


class _Event1(TypedDict):
    event: Literal[1]


class _EventText1(TypedDict):
    event: Literal["1"]


def test_tagged_unions_totaggedunion_should_throw_on_duplicate_discriminants():
    """Tagged unions / toTaggedUnion / should throw on duplicate discriminants"""
    with pytest.raises(ValueError, match=r"^Duplicate discriminant: A$"):
        S.Union(S.Struct(_EventA), S.Union(S.Struct(_EventB), S.Struct(_EventAgain))).pipe(
            S.to_tagged_union("event")
        )
    with pytest.raises(ValueError, match=r"^Duplicate discriminant: 1$"):
        S.Union(S.Struct(_Event1), S.Struct(_EventText1)).pipe(S.to_tagged_union("event"))


def test_tagged_unions_totaggedunion_should_collect_no_discriminants_from_an_empty_union():
    """Tagged unions / toTaggedUnion / should collect no discriminants from an empty union"""
    assert S.Union().pipe(S.to_tagged_union("event")).discriminants == ()


class _Proto(TypedDict):
    event: Literal["__proto__"]
    value: str


def test_tagged_unions_totaggedunion_should_support_proto_as_a_discriminant():
    """Tagged unions / toTaggedUnion / should support __proto__ as a discriminant"""
    member = S.Struct(_Proto)
    schema = S.Union(member).pipe(S.to_tagged_union("event"))
    assert schema.cases["__proto__"] is member
    assert schema.guards["__proto__"]({"event": "__proto__", "value": "a"})


class _ClassA(S.TaggedClass, tag="A"):
    a: str


class _ClassB(S.TaggedClass, tag="B"):
    b: float = S.field(S.FiniteFromString)


def test_tagged_unions_totaggedunion_should_augment_a_union_of_classes():
    """Tagged unions / toTaggedUnion / should augment a union of classes"""
    schema = S.Union(_ClassA, _ClassB).pipe(S.to_tagged_union("_tag"))
    assert schema.cases["A"] is _ClassA
    assert schema.cases["B"] is _ClassB


class _CaseA(TypedDict):
    _tag: Literal["A"]
    a: str


class _CaseC(TypedDict):
    _tag: Literal["C"]
    c: bool


class _CaseB(TypedDict):
    _tag: Literal["B"]
    b: float


type _Cases = _CaseA | _CaseC | _CaseB


def test_tagged_unions_taggedunion_should_create_a_tagged_union():
    """Tagged unions / TaggedUnion / should create a tagged union"""
    schema = S.TaggedUnion(
        S.TaggedStruct(_CaseA), S.TaggedStruct(_CaseC), S.TaggedStruct(_CaseB, b=S.FiniteFromString)
    ).annotate()

    assert schema.tag == "_tag"

    a, c, b = schema.members
    assert (schema.cases["A"], schema.cases["B"], schema.cases["C"]) == (a, b, c)

    # cases
    for case, tag in ((a, "A"), (b, "B"), (c, "C")):
        assert isinstance(case, S.TaggedStructSchema)
        assert case.tag == tag
    assert isinstance(b, S.TaggedStructSchema)
    assert b.fields["b"] is S.FiniteFromString
    assert isinstance(a, S.TaggedStructSchema)
    assert a.fields["a"] is S.String

    # isAnyOf
    is_a_or_b = schema.is_any_of("A", "B")
    assert is_a_or_b({"_tag": "A", "a": "a"})
    assert is_a_or_b({"_tag": "B", "b": 1})
    assert not is_a_or_b({"_tag": "C", "c": True})

    # guards
    assert schema.guards["A"]({"_tag": "A", "a": "a"})
    assert schema.guards["B"]({"_tag": "B", "b": 1})
    assert schema.guards["C"]({"_tag": "C", "c": True})
    assert not schema.guards["A"]({"_tag": "A", "b": 1})
    assert not schema.guards["B"]({"_tag": "B", "a": "a"})
    assert not schema.guards["C"]({"_tag": "C", "c": 1})

    # match
    def match(value: _Cases) -> str:
        match value:
            case {"_tag": "A"}:
                return "A"
            case {"_tag": "B"}:
                return "B"
            case {"_tag": "C"}:
                return "C"
            case _:
                assert_never(value)

    assert match({"_tag": "A", "a": "a"}) == "A"
    assert match({"_tag": "B", "b": 1}) == "B"
    assert match({"_tag": "C", "c": True}) == "C"

    # matchOrElse
    def match_or_else(value: _Cases) -> str:
        match value:
            case {"_tag": "A", "a": a}:
                return a
            case _:
                return value["_tag"]

    assert match_or_else({"_tag": "A", "a": "a"}) == "a"
    assert match_or_else({"_tag": "B", "b": 1}) == "B"


# ---------------------------------------------------------------- Opaque


class _Opaque(S.Class):
    a: str


def test_opaque_struct():
    """Opaque / Struct"""
    instance = _Opaque.make(_Opaque(a="a"))
    assert instance.a == "a"
    assert dict(_Opaque.fields()) == {"a": S.String}
