"""Schema properties over generated schemas and values.

Hypothesis builds a schema (structs with optional and defaulted keys, unions, tagged unions,
arrays, tuples, records, checks, transformations, a recursive schema, classes), then draws
values with ``S.to_strategy`` (Effect's ``toArbitrary``). For each:

- the strategy draws only values the schema accepts, on both sides;
- decoding an encoded value gives it back, through the schema and its JSON codec;
- re-encoding a decoded input decodes to the same value, and gives the input back exactly
  for a schema without normalizing transformations or defaults;
- any input decodes to a value or a ``SchemaError`` holding an issue, never an exception;
- ``errors="all"`` reports every issue ``errors="first"`` does;
- the JSON Schema of the JSON form accepts the encoded values. No JSON Schema validator is a
  dependency, so the document is read back with pyfect's own importer
  (``representation.from_json_schema_document``), which enforces patterns under
  ``patterns="apply"``.

Unions are built from members whose types and encodings are of different kinds, since Effect
promises no round trip for a union whose members overlap (``String | NumberFromString``).
Defects are left out: ``Defect`` reads numbers as JavaScript's (PARITY section 4), which
``tests/test_schema_round_trip.py`` covers.
"""

from __future__ import annotations

import string
from collections.abc import Callable, Hashable, Iterator
from typing import Any, Literal, NotRequired, TypedDict, cast

from hypothesis import given
from hypothesis import strategies as st

import pyfect as fx
from pyfect import schema as S
from pyfect.result import Err, Ok
from pyfect.schema import issue as I
from pyfect.schema import representation as R


class Point(S.Class):
    x: int
    y: int


class Labelled(S.Class):
    label: str
    tags: tuple[str, ...]


class _Tree(TypedDict):
    value: int
    children: tuple[_Tree, ...]


_TREE: S.Bottom[Any, Any, Any, Any] = S.Struct(
    _Tree, children=S.Array(S.suspend(lambda: _TREE)).check(S.is_max_length(2))
)


class Node:
    """A generated schema with what the generator needs to know about it: the kinds of value
    its Type and Encoded sides hold (members of a union must not share one), and whether
    encoding a decoded input gives the input back exactly. Shown by its label alone, so a
    falsified example reads as the schema it is."""

    __slots__ = ("canonical", "encoded", "label", "schema", "types")

    def __init__(
        self,
        schema: S.Bottom[Any, Any, Any, Any],
        types: frozenset[str],
        encoded: frozenset[str],
        canonical: bool,
        label: str,
    ) -> None:
        self.schema = schema
        self.types = types
        self.encoded = encoded
        self.canonical = canonical
        self.label = label

    def __repr__(self) -> str:
        return self.label


def _leaf(
    label: str,
    schema: Any,
    types: str,
    encoded: str | None = None,
    *,
    canonical: bool = True,
) -> Node:
    """``encoded`` holds the kinds of both encoded forms: the schema's own and its JSON
    codec's (a ``HashSet`` is a ``HashSet``, then an array)."""
    return Node(
        cast("S.Bottom[Any, Any, Any, Any]", schema),
        frozenset(types.split()),
        frozenset((encoded or types).split()),
        canonical,
        label,
    )


_LEAVES = [
    _leaf("String", S.String, "str"),
    _leaf("Int", S.Int, "num"),
    _leaf("Finite", S.Finite, "num"),
    _leaf("Boolean", S.Boolean, "bool"),
    _leaf("Null", S.Null, "null"),
    _leaf('Literal("a")', S.Literal("a"), "str"),
    _leaf("Literals(1, 2)", S.Literals([1, 2]), "num"),
    _leaf("NonEmptyString", S.NonEmptyString, "str"),
    _leaf("Trimmed max 3", S.String.check(S.is_trimmed(), S.is_max_length(3)), "str"),
    _leaf("Int between", S.Int.check(S.is_between(minimum=-5, maximum=5)), "num"),
    _leaf("pattern", S.String.check(S.is_pattern(r"^[a-c]+$")), "str"),
    _leaf("NumberFromString", S.NumberFromString, "num", "str", canonical=False),
    _leaf("FiniteFromString", S.FiniteFromString, "num", "str", canonical=False),
    _leaf("BooleanFromBit", S.BooleanFromBit, "bool", "num"),
    _leaf("BigIntFromString", S.BigIntFromString, "num", "str", canonical=False),
    _leaf("DateTimeUtcFromString", S.DateTimeUtcFromString, "date", "str", canonical=False),
    _leaf("BytesFromBase64", S.BytesFromBase64, "bytes", "str", canonical=False),
    _leaf("Trim", S.Trim, "str", canonical=False),
    _leaf("Point", Point, "Point", "dict"),
    _leaf("Labelled", Labelled, "Labelled", "dict"),
    _leaf("Tree", _TREE, "dict"),
    _leaf("Option(String)", S.Option(S.String), "null some", "null some dict"),
    _leaf("OptionFromNullOr(Int)", S.OptionFromNullOr(S.Int), "null some", "null num"),
    _leaf("Duration", S.Duration, "duration", "duration dict"),
    _leaf("DurationFromString", S.DurationFromString, "duration", "str", canonical=False),
    _leaf("HashSet(Int)", S.HashSet(S.Int), "hashset", "hashset seq"),
    _leaf("HashMap(String, Int)", S.HashMap(S.String, S.Int), "hashmap", "hashmap seq"),
    _leaf("Map(String, Boolean)", S.Map(S.String, S.Boolean), "map", "map seq"),
    _leaf("FrozenSet(String)", S.FrozenSet(S.String), "frozenset", "frozenset seq"),
    _leaf("UniqueArray(Int)", S.UniqueArray(S.Int), "seq"),
    _leaf("Result(Int, String)", S.Result(S.Int, S.String), "result", "result dict"),
    _leaf("Exit(Int, String, String)", S.Exit(S.Int, S.String, S.String), "exit", "exit dict"),
    _leaf("Redacted(String)", S.Redacted(S.String), "redacted", "redacted str"),
    _leaf(
        "TemplateLiteral",
        S.TemplateLiteral(["id-", S.Int, "-", S.Literals(["a", "b"])]),
        "str",
    ),
    _leaf("BigDecimal", S.BigDecimal, "bigdecimal", "bigdecimal str"),
    _leaf("Cause(String, String)", S.Cause(S.String, S.String), "cause", "cause seq"),
    _leaf("Bytes", S.Bytes, "bytes", "bytes str"),
    _leaf("URL", S.URL, "url", "url str"),
]

_names = st.text(string.ascii_lowercase, min_size=1, max_size=3)


def _typed_dict(name: str, keys: dict[str, object]) -> type[Any]:
    """A TypedDict made at run time; pyright only takes literal TypedDict definitions."""
    return cast("Callable[[str, dict[str, object]], type[Any]]", TypedDict)(name, keys)


def _tagged_literal(tag: str) -> object:
    return cast("Any", Literal)[tag]


@st.composite
def _struct(draw: st.DrawFn, children: st.SearchStrategy[Node]) -> Node:
    names = draw(st.lists(_names, min_size=1, max_size=3, unique=True))
    keys: dict[str, object] = {}
    fields: dict[str, Any] = {}
    canonical = True
    parts: list[str] = []
    for name in names:
        child = draw(children)
        kind = draw(st.sampled_from(["required", "optional", "option", "default"]))
        canonical = canonical and child.canonical
        match kind:
            case "required":
                keys[name], fields[name] = object, child.schema
            case "optional":
                keys[name], fields[name] = NotRequired[object], child.schema
            case "option":
                keys[name], fields[name] = object, S.OptionFromOptionalKey(child.schema)
            case _:
                # A missing key decodes to the default, so encoding gives the key back.
                keys[name] = object
                fields[name] = S.String.pipe(S.with_decoding_default_key(fx.succeed("d")))
                child = _LEAVES[0]
                canonical = False
        parts.append(f"{name}: {kind} {child.label}")
    schema = S.Struct(_typed_dict("Generated", keys), **fields)
    return Node(schema, frozenset({"dict"}), frozenset({"dict"}), canonical, f"Struct({parts})")


@st.composite
def _tagged_union(draw: st.DrawFn, children: st.SearchStrategy[Node]) -> Node:
    tags = draw(st.lists(_names, min_size=1, max_size=3, unique=True))
    cases: list[Any] = []
    canonical = True
    labels: list[str] = []
    for tag in tags:
        child = draw(children)
        canonical = canonical and child.canonical
        typed_dict = _typed_dict(f"Case_{tag}", {"_tag": _tagged_literal(tag), "value": object})
        cases.append(S.TaggedStruct(typed_dict, value=child.schema))
        labels.append(f"{tag}: {child.label}")
    schema = S.TaggedUnion(*cases)
    return Node(schema, frozenset({"dict"}), frozenset({"dict"}), canonical, f"Tagged{labels}")


@st.composite
def _union(draw: st.DrawFn, children: st.SearchStrategy[Node]) -> Node:
    """A union of up to six members with no type kind or encoded kind in common."""
    members: list[Node] = []
    for candidate in draw(st.lists(children, min_size=2, max_size=6)):
        if all(
            not (candidate.types & m.types) and not (candidate.encoded & m.encoded) for m in members
        ):
            members.append(candidate)
    schema = S.Union(*(m.schema for m in members))
    return Node(
        schema,
        frozenset[str]().union(*(m.types for m in members)),
        frozenset[str]().union(*(m.encoded for m in members)),
        all(m.canonical for m in members),
        f"Union{[m.label for m in members]}",
    )


def _composites(children: st.SearchStrategy[Node]) -> st.SearchStrategy[Node]:
    def wrap(label: str, make: Callable[[Node], Any], kind: str) -> st.SearchStrategy[Node]:
        return children.map(
            lambda c: Node(
                make(c), frozenset({kind}), frozenset({kind}), c.canonical, f"{label}({c})"
            )
        )

    def null_or(c: Node) -> Node:
        if "null" in c.types | c.encoded:
            return c  # already nullable (mapped, not filtered: filtering risks health checks)
        return Node(
            S.NullOr(c.schema),
            c.types | {"null"},
            c.encoded | {"null"},
            c.canonical,
            f"NullOr({c})",
        )

    return st.one_of(
        wrap("Array", lambda c: S.Array(c.schema), "seq"),
        wrap("Array max 2", lambda c: S.Array(c.schema).check(S.is_max_length(2)), "seq"),
        wrap("NonEmptyArray", lambda c: S.NonEmptyArray(c.schema), "seq"),
        wrap("Record", lambda c: S.Record(S.String, c.schema), "dict"),
        wrap(
            "Record max 2",
            lambda c: S.Record(S.String, c.schema).check(S.is_max_properties(2)),
            "dict",
        ),
        st.tuples(children, children).map(
            lambda p: Node(
                S.Tuple(p[0].schema, p[1].schema),
                frozenset({"seq"}),
                frozenset({"seq"}),
                p[0].canonical and p[1].canonical,
                f"Tuple({p[0]}, {p[1]})",
            )
        ),
        children.map(null_or),
        _struct(children),
        _tagged_union(children),
        _union(children),
    )


_schemas: st.SearchStrategy[Node] = st.recursive(
    st.sampled_from(_LEAVES), _composites, max_leaves=5
)


def _round_trip_codecs(node: Node) -> list[Any]:
    return [node.schema, S.to_codec_json(node.schema)]


@given(_schemas, st.data())
def test_decoding_an_encoded_value_gives_it_back(node: Node, data: st.DataObject):
    value = data.draw(S.to_strategy(node.schema), label="value")
    assert S.is_(node.schema)(value)
    same = S.to_equivalence(node.schema)
    for codec in _round_trip_codecs(node):
        encoded = S.encode_sync(codec)(value)
        assert same(S.decode_unknown_sync(codec)(encoded), value)


@given(_schemas, st.data())
def test_re_encoding_a_decoded_input_keeps_its_meaning(node: Node, data: st.DataObject):
    encoded_side = S.to_encoded(node.schema)
    raw = data.draw(S.to_strategy(encoded_side), label="input")
    assert S.is_(encoded_side)(raw)
    decoded = S.decode_unknown_result(node.schema)(raw)
    if not isinstance(decoded, Ok):
        return  # a check or transformation of the Type side rejected it
    again = S.encode_sync(node.schema)(decoded.value)
    assert S.to_equivalence(node.schema)(S.decode_unknown_sync(node.schema)(again), decoded.value)
    if node.canonical:
        assert S.to_equivalence(encoded_side)(again, raw)


_json: st.SearchStrategy[object] = st.recursive(
    st.one_of(
        st.none(),
        st.booleans(),
        st.integers(-(2**60), 2**60),
        st.floats(),
        st.text(max_size=4),
    ),
    lambda inner: st.one_of(
        st.lists(inner, max_size=3),
        st.tuples(inner, inner),
        st.dictionaries(st.one_of(_names, st.just("_tag"), st.just("value")), inner, max_size=3),
    ),
    max_leaves=8,
)
_anything = st.one_of(_json, st.binary(max_size=3), st.just(object()), st.just(Point(x=1, y=2)))


def _leaves(issue: I.Issue, path: tuple[Hashable, ...] = ()) -> Iterator[tuple[object, ...]]:
    match issue:
        case I.Pointer(path=more, issue=inner):
            yield from _leaves(inner, path + more)
        case I.Composite(issues=issues) | I.AnyOf(issues=issues):
            for inner in issues:
                yield from _leaves(inner, path)
        case I.Encoding(issue=inner) | I.Filter(issue=inner):
            yield from _leaves(inner, path)
        case _:
            yield (path, type(issue).__name__, I.leaf_message(issue))


@given(_schemas, _anything)
def test_any_input_decodes_to_a_value_or_an_issue(node: Node, raw: object):
    first = S.decode_unknown_result(node.schema)(raw)
    every = S.decode_unknown_result(node.schema, errors="all")(raw)
    match first, every:
        case Ok(value=a), Ok(value=b):
            assert S.is_(node.schema)(a)
            assert S.to_equivalence(node.schema)(a, b)
        case Err(error=a), Err(error=b):
            assert I.is_issue(a.issue)
            assert I.is_issue(b.issue)
            assert set(_leaves(a.issue)) <= set(_leaves(b.issue))
            assert str(a)
        case _:
            raise AssertionError(f"errors='first' gave {first}, errors='all' gave {every}")


@given(_schemas, st.data())
def test_the_json_schema_accepts_the_json_form_of_every_value(node: Node, data: st.DataObject):
    value = data.draw(S.to_strategy(node.schema), label="value")
    document = S.to_json_schema_document(node.schema)
    validator = R.from_json_schema_document(document, patterns="apply")
    encoded = S.encode_sync(S.to_codec_json(node.schema))(value)
    assert S.is_(validator)(encoded), (document, encoded)


@given(st.sampled_from(_LEAVES), st.data())
def test_a_leaf_round_trips_through_a_struct_key_that_may_be_missing(
    leaf: Node, data: st.DataObject
):
    keyed = S.Struct(_typed_dict("Holder", {"k": NotRequired[object]}), k=leaf.schema)
    holder = data.draw(S.to_strategy(keyed))
    assert S.is_(keyed)(holder)
    assert S.to_equivalence(keyed)(
        S.decode_unknown_sync(keyed)(S.encode_sync(keyed)(holder)), holder
    )
