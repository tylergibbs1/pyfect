"""Ports of Effect's ``withConstructorDefault`` and ``tag`` titles: the
"withConstructorDefault" block of ``Schema.test.ts`` (the "tag" block is in
``test_schema_tagged.py``), its
"flip / should work with withConstructorDefault", "makeEffect / should
preserve mixed schema issue and defect causes" and the Class "make" titles
about defaults, "product concurrency / applies concurrency to constructor
defaults" of ``SchemaParser.test.ts`` and "stores constructor defaults
directly in the context" of ``SchemaAST.test.ts``. Each test's docstring is
the Effect test title, prefixed by its ``describe`` blocks.

Python mappings: a struct is ``S.Struct(TypedDict, key=schema)``; Effect's
``context.constructorDefault`` is the node's ``constructor_default``; a
class is made with ``A.make(fields)`` (``A(...)`` uses its dataclass
defaults, which are values, not effects).

Omitted:
- "withConstructorDefault / Struct / applies constructor default when
  disableChecks is true" and "Class / make applies defaults, source checks,
  and the constructor once": they build a class whose own constructor
  (``new A({})``) runs the defaults; a pyfect class's ``__init__`` is its
  dataclass's (field defaults are values), so ``A.make`` is ported in the
  nested-class titles instead.
"""

from typing import Literal, Never, NotRequired, TypedDict, cast

from pyfect import effect as fx
from pyfect import schema as S
from pyfect.cause import Cause, Die, Fail
from pyfect.clock import sleep
from pyfect.context import Tag
from pyfect.deferred import Deferred
from pyfect.exit import Failure, Success
from pyfect.option import Some
from pyfect.result import Ok
from pyfect.run import run_sync, run_sync_exit
from pyfect.schema.issue import InvalidValue, Issue, is_issue
from pyfect.testing import SchemaAsserts


class _A(TypedDict):
    a: float


class _OptionalA(TypedDict):
    a: NotRequired[str]


def _finite_or(value: float) -> S.WithConstructorDefault[float, str, Never, Never]:
    return S.FiniteFromString.pipe(S.with_constructor_default(fx.succeed(value)))


def test_flip_should_work_with_with_constructor_default():
    """flip / should work with withConstructorDefault"""
    schema = S.Struct(_A, a=_finite_or(-1))
    make = SchemaAsserts(schema).make()
    make.succeed({"a": 1})
    make.succeed({}, {"a": -1})

    flipped = S.flip(schema)
    assert isinstance(run_sync_exit(flipped.make_effect({})), Failure)
    SchemaAsserts(flipped).make().succeed({"a": "1"})

    flipped2 = S.flip(flipped)
    make2 = SchemaAsserts(flipped2).make()
    make2.succeed({"a": 1})
    make2.succeed({}, {"a": -1})


def test_should_not_apply_defaults_when_decoding_encoding():
    """withConstructorDefault / Struct / should not apply defaults when decoding / encoding"""
    schema = S.Struct(
        _OptionalA,
        a=S.String.pipe(S.with_constructor_default(fx.succeed("a"))),
    )
    asserts = SchemaAsserts(schema)
    asserts.decoding().succeed({}, {})
    asserts.encoding().succeed({}, {})


def test_should_apply_constructor_default_when_the_field_is_not_present():
    """withConstructorDefault / Struct / should apply constructor default when the field is not present"""  # noqa: E501
    make = SchemaAsserts(S.Struct(_A, a=_finite_or(-1))).make()
    make.succeed({"a": 1})
    make.succeed({}, {"a": -1})


class _Row(S.Class):
    a: str


class _ClassField(TypedDict):
    a: _Row


def test_should_construct_a_class_field_from_a_plain_object():
    """withConstructorDefault / Struct / should construct a Class field from a plain object"""
    schema = S.Struct(
        _ClassField,
        a=S.with_constructor_default(fx.succeed(_Row(a="default")))(_Row),
    )
    result = schema.make({"a": {"a": "a"}})  # pyright: ignore[reportArgumentType]
    assert isinstance(result["a"], _Row)
    assert result["a"].a == "a"


class _Inner(TypedDict):
    b: float


class _Outer(TypedDict):
    a: _Inner


EMPTY_INNER = cast("_Inner", {})
"""Effect's ``{}`` default, which ``make`` then fills."""


def test_nested_defaults_struct():
    """withConstructorDefault / Struct / nested defaults / Struct"""
    inner = S.Struct(_Inner, b=_finite_or(-1))
    schema = S.Struct(
        _Outer,
        a=inner.pipe(S.with_constructor_default(fx.succeed(EMPTY_INNER))),
    )
    make = SchemaAsserts(schema).make()
    make.succeed({"a": {"b": 1}})
    make.succeed({"a": {}}, {"a": {"b": -1}})
    make.succeed({}, {"a": {"b": -1}})


class _Nested(S.Class):
    a: _Inner = S.field(
        S.Struct(_Inner, b=_finite_or(-1)).pipe(S.with_constructor_default(fx.succeed(EMPTY_INNER)))
    )


def test_nested_defaults_class():
    """withConstructorDefault / Struct / nested defaults / Class"""
    make = SchemaAsserts(_Nested).make()
    make.succeed({"a": {"b": 1}}, _Nested(a={"b": 1}))
    make.succeed({"a": {}}, _Nested(a={"b": -1}))
    make.succeed({}, _Nested(a={"b": -1}))
    assert _Nested.make({"a": {}}) == _Nested(a={"b": -1})  # pyright: ignore[reportArgumentType]
    assert _Nested.make({}) == _Nested(a={"b": -1})  # pyright: ignore[reportArgumentType]


def test_struct_effect_sync():
    """withConstructorDefault / Struct / Struct & Effect sync"""
    make = SchemaAsserts(S.Struct(_A, a=_finite_or(-1))).make()
    make.succeed({"a": 1})
    make.succeed({}, {"a": -1})


def test_struct_effect_async():
    """withConstructorDefault / Struct / Struct & Effect async"""
    default = sleep(0.01).as_(-1.0)
    schema = S.Struct(_A, a=S.FiniteFromString.pipe(S.with_constructor_default(default)))
    make = SchemaAsserts(schema).make()
    make.succeed({"a": 1})
    make.succeed({}, {"a": -1})


def test_effect_failing_with_schema_issue_propagates_as_parse_failure():
    """withConstructorDefault / Struct / Effect failing with SchemaIssue propagates as parse failure"""  # noqa: E501
    failing = fx.fail(InvalidValue({"message": "ctor default failed"}))
    schema = S.Struct(_A, a=S.FiniteFromString.pipe(S.with_constructor_default(failing)))
    make = SchemaAsserts(schema).make()
    make.succeed({"a": 1})
    make.fail({}, 'ctor default failed\n  at ["a"]')


class _N(TypedDict):
    n: float


def test_effect_failing_via_another_schemas_make_effect_propagates_as_parse_failure():
    """withConstructorDefault / Struct / Effect failing via another schema's makeEffect propagates as parse failure"""  # noqa: E501
    inner = S.Struct(_N, n=S.FiniteFromString.check(S.is_greater_than(0)))
    default = inner.make_effect({"n": -1}).map(lambda s: s["n"])
    schema = S.Struct(_A, a=S.FiniteFromString.pipe(S.with_constructor_default(default)))
    make = SchemaAsserts(schema).make()
    make.succeed({"a": 1})
    make.fail({}, 'Expected a value greater than 0\n  at ["a"]["n"]')


class _Service(Tag[fx.Effect[float]], key="Service"):
    pass


def test_struct_effect_async_service():
    """withConstructorDefault / Struct / Struct & Effect async & service"""

    def value(service: Some[fx.Effect[float]] | None) -> fx.Effect[float]:
        return fx.succeed(-1.0) if service is None else service.value

    default = sleep(0.01).and_then(fx.service_option(_Service)).flat_map(value)
    schema = S.Struct(_A, a=S.FiniteFromString.pipe(S.with_constructor_default(default)))
    make = SchemaAsserts(schema).make()
    make.succeed({"a": 1})
    make.succeed({}, {"a": -1})
    made = schema.make_effect({})  # pyright: ignore[reportArgumentType]
    provided = made.pipe(fx.provide_service(_Service, fx.succeed(0.0)))
    assert run_sync_exit(provided) == Success({"a": 0})


def test_tuple_some():
    """withConstructorDefault / Tuple / Tuple & Some"""
    make = SchemaAsserts(S.Tuple(_finite_or(-1))).make()
    make.succeed((1,))
    make.succeed((), (-1,))


def test_tuple_nested_defaults_struct():
    """withConstructorDefault / Tuple / nested defaults (Struct)"""
    inner = S.Struct(_Inner, b=_finite_or(-1))
    schema = S.Tuple(inner.pipe(S.with_constructor_default(fx.succeed(EMPTY_INNER))))
    make = SchemaAsserts(schema).make()
    make.succeed(({"b": 1},))
    make.succeed((EMPTY_INNER,), ({"b": -1},))
    make.succeed((), ({"b": -1},))


def test_tuple_inner_defaults_tuple():
    """withConstructorDefault / Tuple / inner defaults (Tuple)"""
    make = SchemaAsserts(S.Tuple(S.Tuple(_finite_or(-1)))).make()
    make.succeed(((1,),))
    make.succeed(((),), ((-1,),))


def test_tuple_nested_defaults_tuple():
    """withConstructorDefault / Tuple / nested defaults (Tuple)"""
    empty = cast("tuple[float]", ())
    inner = S.Tuple(_finite_or(-1)).pipe(S.with_constructor_default(fx.succeed(empty)))
    make = SchemaAsserts(S.Tuple(inner)).make()
    make.succeed(((1,),))
    make.succeed(((),), ((-1,),))
    make.succeed((), ((-1,),))


class _Tagged(TypedDict):
    _tag: Literal["A"]
    value: float


def test_tagged_struct_make_fills_the_tag():
    """TaggedStruct (pyfect): make fills the tag, as Effect's TaggedStruct uses ``tag``"""
    schema = S.TaggedStruct(_Tagged)
    assert schema.make({"value": 42}) == {"_tag": "A", "value": 42}  # pyright: ignore[reportArgumentType]
    assert isinstance(S.decode_unknown_exit(schema)({"value": 42}), Failure)


def test_make_effect_should_preserve_mixed_schema_issue_and_defect_causes():
    """makeEffect / should preserve mixed schema issue and defect causes"""
    boom = RuntimeError("defect")
    cause: Cause[Issue] = Cause((Fail(InvalidValue({"message": "schema issue"})), Die(boom)))
    schema = S.Struct(_OptionalA, a=S.String.pipe(S.with_constructor_default(fx.fail_cause(cause))))
    exit = run_sync_exit(schema.make_effect({}))
    assert isinstance(exit, Failure)
    assert any(isinstance(r, Die) for r in exit.cause.reasons)
    error = exit.cause.find_error()
    assert isinstance(error, Ok)
    assert is_issue(error.value)


class _Value(TypedDict):
    value: str


class _UnionValue(TypedDict):
    value: str | float


def test_make_applies_constructor_defaults_only_at_a_field_occurrence():
    """Class / make applies constructor defaults only at a field occurrence"""
    calls: list[None] = []

    def count() -> str:
        calls.append(None)
        return "default"

    defaulted = S.String.pipe(S.with_constructor_default(fx.sync(count)))
    field = S.Struct(_Value, value=defaulted)
    member = S.Struct(_UnionValue, value=S.Union(defaulted, S.Number))
    assert defaulted.make_option(None) is None  # pyright: ignore[reportArgumentType]
    assert calls == []
    assert field.make({}) == {"value": "default"}  # pyright: ignore[reportArgumentType]
    assert len(calls) == 1
    assert member.make_option({}) is None  # pyright: ignore[reportArgumentType]
    assert member.make_option({"value": None}) is None  # pyright: ignore[reportArgumentType]
    assert len(calls) == 1


class _HasRow(TypedDict):
    a: _Row


def test_struct_with_nested_class():
    """Class / Struct with nested Class"""
    schema = S.Struct(_HasRow, a=S.with_constructor_default(fx.succeed(_Row(a="default")))(_Row))
    make = SchemaAsserts(schema).make()
    make.succeed({"a": _Row(a="a")})
    make.succeed({}, {"a": _Row(a="default")})


class _B(S.Class):
    a: _Row = S.field(S.with_constructor_default(fx.succeed(_Row(a="default")))(_Row))


def test_class_with_nested_class():
    """Class / Class with nested Class"""
    make = SchemaAsserts(_B).make()
    make.succeed({"a": _Row(a="a")}, _B(a=_Row(a="a")))
    make.succeed({}, _B(a=_Row(a="default")))


class _AB(TypedDict):
    a: str
    b: str


def test_applies_concurrency_to_constructor_defaults():
    """product concurrency / applies concurrency to constructor defaults"""

    def program() -> fx.Effect[_AB, Issue]:
        first = run_sync(Deferred[None].make())
        second = run_sync(Deferred[None].make())
        release = run_sync(Deferred[None].make())

        def field(
            value: str, started: Deferred[None]
        ) -> S.WithConstructorDefault[str, str, Never, Never]:
            default = started.succeed(None).and_then(release.wait()).as_(value)
            return S.String.pipe(S.with_constructor_default(default))

        schema = S.Struct(_AB, a=field("a", first), b=field("b", second))
        return (
            schema.make_effect({}, concurrency=2)  # pyright: ignore[reportArgumentType]
            .fork()
            .flat_map(
                lambda fiber: (
                    first.wait()
                    .and_then(second.wait())
                    .and_then(release.succeed(None))
                    .and_then(fiber.join())
                )
            )
        )

    assert run_sync_exit(program()) == Success({"a": "a", "b": "b"})


def test_stores_constructor_defaults_directly_in_the_context():
    """stores constructor defaults directly in the context"""
    default = fx.succeed("default")
    node = S.ast.with_constructor_default(S.ast.string, default)
    assert node.constructor_default is default


class _TaggedA(TypedDict):
    _tag: Literal["A"]
    a: str


class _TaggedB(TypedDict):
    _tag: Literal["B"]
    b: float


def test_union_make_tries_every_tagged_member_when_the_tag_is_missing():
    """A union's ``make`` treats a missing discriminator as unconstrained
    (Effect's constructor mode of ``getCandidateIndex``), so a member's
    ``tag`` default fills it in"""
    union = S.Union(S.Struct(_TaggedA, _tag=S.tag("A")), S.Struct(_TaggedB, _tag=S.tag("B")))
    make = SchemaAsserts(union).make()
    make.succeed({"a": "x"}, {"_tag": "A", "a": "x"})
    make.succeed({"b": 1}, {"_tag": "B", "b": 1})
    make.succeed({"_tag": "B", "b": 1})
    SchemaAsserts(union).decoding().fail(
        {"a": "x"}, 'Expected { readonly "_tag": "A", ... } | { readonly "_tag": "B", ... }'
    )
