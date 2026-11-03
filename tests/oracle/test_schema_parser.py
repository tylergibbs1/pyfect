"""Ports of Effect's ``SchemaParser.test.ts``. Each test's docstring is the
Effect test title, prefixed by its ``describe`` block.

``SchemaParser``'s functions fail with the bare ``SchemaIssue`` (and throw
an ``Error`` whose cause is the issue); pyfect has one family of adapters,
``Schema``'s, failing with ``SchemaError``, which holds the issue. These
ports go through them, and ``Bottom.make`` raises ``SchemaError``.

Ported through ``ast.parse``: "keeps synchronous transformations eager" and
"keeps synchronous product parsers eager". Effect's ``Exit`` is an
``Effect``, so its eager parse is visible through ``decodeUnknownEffect``;
pyfect's ``Exit`` is not, so the port checks that the AST parse returns an
``Exit`` rather than an effect.

The ``make`` / ``makeOption`` defect titles fail a ``withConstructorDefault``
in Effect; pyfect's field defaults are plain values, so a declaration's
parser gives the same cause. Titles Effect builds for two causes ("not an
Issue" and "both an Issue and a defect") are one parametrized test.

Omitted: "makeEffect / defers deriving the type AST until the maker is
called and derives it once" (``make_effect`` is a method of an immutable
schema: there is no maker whose ``ast`` could be swapped); the
``decodeUnknownPromise`` titles and "Promise adapters reject with defects
instead of throwing" (pyfect has no Promise adapters; ``run_async`` of
``decode_unknown_effect`` is the asyncio form); "product concurrency /
applies concurrency to constructor defaults" (field defaults are plain
values, not effects); the inherited-property titles ("decodes inherited
struct properties", "decodes inherited string, number, and symbol fields",
"distinguishes an inherited undefined property from a missing property",
"selects union members using inherited discriminants", "decodes inherited
Object.prototype properties", "requires __proto__ to be an own property",
"keeps dynamic record properties own-only while finite record keys are
declared": a Python ``Mapping`` has no prototype chain); "distinguishes
missing tuple elements from undefined" (Python has no ``undefined``);
"preserves missing optional template literals" is in
``test_schema_template_literal.py``.
"""

from collections.abc import Callable, Generator, Iterator, Mapping
from typing import Any, Literal, Never, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.cause import Cause, Die, Fail
from pyfect.deferred import Deferred
from pyfect.exit import Exit, Failure, Success, die, fail, succeed
from pyfect.option import Option, Some
from pyfect.ref import Ref
from pyfect.result import Ok
from pyfect.schema import getter as G
from pyfect.schema import transformation as T
from pyfect.schema.issue import AnyOf, Composite, InvalidValue, Issue, Pointer


def test_make_should_throw_an_error_when_the_input_is_invalid():
    """make / should throw an error when the input is invalid"""
    with pytest.raises(S.SchemaError, match=r"^Expected string$"):
        S.String.make(None)  # pyright: ignore[reportArgumentType]


def test_sync_should_throw_an_error_when_the_input_is_invalid():
    """decodeUnknownSync / encodeUnknownSync / should throw an error when the input is invalid"""
    with pytest.raises(S.SchemaError, match=r"^Expected string$"):
        S.decode_unknown_sync(S.String)(None)
    with pytest.raises(S.SchemaError, match=r"^Expected string$"):
        S.encode_unknown_sync(S.String)(None)


def test_option_should_return_none_when_the_input_is_invalid():
    """decodeUnknownOption / encodeUnknownOption / should return none when the input is invalid"""
    assert S.decode_unknown_option(S.String)("a") == Some("a")
    assert S.decode_unknown_option(S.String)(None) is None
    assert S.encode_unknown_option(S.String)("a") == Some("a")
    assert S.encode_unknown_option(S.String)(None) is None


def test_is_should_return_false_when_the_input_is_invalid():
    """is / should return false when the input is invalid"""
    is_string = S.is_(S.String)
    assert is_string("a") is True
    assert is_string(None) is False


def test_decode_unknown_exit_preserves_values_that_use_effect_data_protocols():
    """decodeUnknownExit / preserves values that use Effect data protocols"""
    executions = 0

    def run() -> str:
        nonlocal executions
        executions += 1
        return "a"

    decode = S.decode_unknown_exit(S.Unknown)
    values: list[object] = [None, Some("a"), succeed("a"), fail("a"), fx.sync(run)]

    for value in values:
        result = decode(value)
        assert isinstance(result, Success)
        assert result.value is value
    assert executions == 0

    failure = fail("a")
    union_result = S.decode_unknown_exit(S.Union(S.Unknown))(failure)
    assert isinstance(union_result, Success)
    assert union_result.value is failure


# ------------------------------------------------- effectful parsing (M8 transformations)


class _Defect(Exception):
    pass


_DEFECT = _Defect("callback defect")


def _raise(*_: object) -> Never:
    raise _DEFECT


def _declaration() -> S.Bottom[object]:
    return S.declare_constructor((), lambda _: _raise)


def _raising_middleware(
    effect: fx.Effect[Option[str], Issue], options: S.ParseOptions
) -> fx.Effect[Option[str], Issue]:
    raise _DEFECT


def _callback_schemas() -> dict[str, S.Bottom[Any, Any]]:
    getter: G.Getter[str, str] = G.transform(_raise)
    declaration = _declaration()
    transformation: T.Transformation[str, str] = T.Transformation(getter, getter)
    decoded = S.String.pipe(S.middleware_decoding(_raising_middleware))
    return {
        "transformation": S.String.pipe(S.decode_to(S.String, transformation)),
        "filter": S.String.check(S.make_filter(_raise)),
        "declaration filter": S.declare_constructor((), lambda _: _succeed).check(
            S.make_filter(_raise)
        ),
        "middleware": decoded.pipe(S.middleware_encoding(_raising_middleware)),
        "declaration": declaration,
        "wrapped declaration": S.NullOr(S.suspend(lambda: declaration)),
    }


def _succeed(input: object, *_: object) -> fx.Effect[object, Never]:
    return fx.succeed(input)


@pytest.mark.parametrize("name", list(_callback_schemas()))
def test_preserves_callback_defects_when_decoding_and_encoding(name: str):
    """synchronous root callback defects / preserves ${name} defects when decoding and encoding"""
    schema = _callback_schemas()[name]
    assert S.decode_unknown_exit(schema)("value") == die(_DEFECT)
    assert S.encode_unknown_exit(schema)("value") == die(_DEFECT)


@testing.effect
def test_effect_adapters_return_defects_instead_of_throwing():
    """synchronous root callback defects / Effect adapters return defects instead of throwing"""
    declaration = _declaration()
    decoding = S.decode_unknown_effect(declaration)("value")
    encoding = S.encode_unknown_effect(declaration)("value")
    assert (yield from decoding.exit()) == die(_DEFECT)
    assert (yield from encoding.exit()) == die(_DEFECT)


class _AB(TypedDict):
    a: str
    b: str


class _ABC(TypedDict):
    a: str
    b: str
    c: str


type _Make = Callable[[S.Bottom[str, str]], S.Bottom[Any, Any]]

_SEQUENTIAL: dict[str, tuple[_Make, object]] = {
    "Struct": (lambda item: S.Struct(_AB, a=item, b=item), {"a": "a", "b": "b"}),
    "Tuple": (lambda item: S.Tuple(item, item), ("a", "b")),
    "Array": (S.Array, ("a", "b")),
    "Record": (lambda item: S.Record(S.String, item), {"a": "a", "b": "b"}),
}


def _both_ways(getter: G.Getter[str, str]) -> T.Transformation[str, str]:
    return T.Transformation(getter, getter)


@pytest.mark.parametrize("errors", ["first", "all"])
@pytest.mark.parametrize("name", list(_SEQUENTIAL))
@testing.effect
def test_decodes_and_encodes_asynchronous_children_sequentially(
    name: str, errors: Literal["first", "all"]
):
    """sequential parsing / ${name} decodes and encodes asynchronous children sequentially (${errors})"""  # noqa: E501
    calls: list[str] = []

    def run(value: str, _: object) -> fx.Effect[str]:
        calls.append(f"start {value}")

        def body() -> Generator[fx.Effect[Any], Any, str]:
            yield from fx.yield_now()
            calls.append(f"end {value}")
            return value

        return fx.gen(body)

    make, input = _SEQUENTIAL[name]
    schema = make(S.String.pipe(S.decode(_both_ways(G.transform_effect(run)))))
    assert (yield from S.decode_unknown_effect(schema)(input, errors=errors)) == input
    assert calls == ["start a", "end a", "start b", "end b"]
    calls.clear()
    assert (yield from S.encode_unknown_effect(schema)(input, errors=errors)) == input
    assert calls == ["start a", "end a", "start b", "end b"]


_CONCURRENT: dict[str, tuple[_Make, object]] = {
    "Struct": (lambda item: S.Struct(_ABC, a=item, b=item, c=item), {"a": "a", "b": "b", "c": "c"}),
    "Tuple": (lambda item: S.Tuple(item, item, item), ("a", "b", "c")),
    "Array": (S.Array, ("a", "b", "c")),
    "Record": (lambda item: S.Record(S.String, item), {"a": "a", "b": "b", "c": "c"}),
}


def _deferred(_: int) -> fx.Effect[Deferred[None]]:
    return Deferred[None].make()


def _deferreds(n: int) -> fx.Effect[list[Deferred[None]]]:
    return fx.for_each(range(n), _deferred)


@pytest.mark.parametrize("name", list(_CONCURRENT))
@testing.effect
def test_uses_bounded_concurrency_when_decoding_and_encoding(name: str):
    """product concurrency / ${name} uses Effect.forEach bounded concurrency when decoding and encoding"""  # noqa: E501
    make, input = _CONCURRENT[name]
    for operation in ("decode", "encode"):
        started = yield from _deferreds(3)
        releases = yield from _deferreds(3)

        def run(
            value: str,
            _: object,
            started: list[Deferred[None]] = started,
            releases: list[Deferred[None]] = releases,
        ) -> fx.Effect[str]:
            index = ord(value) - 97
            return started[index].succeed(None).and_then(releases[index].wait()).as_(value)

        schema = make(S.String.pipe(S.decode(_both_ways(G.transform_effect(run)))))
        parse = (
            S.decode_unknown_effect(schema)
            if operation == "decode"
            else S.encode_unknown_effect(schema)
        )
        fiber = yield from parse(input, concurrency=2).fork()

        yield from started[0].wait()
        yield from started[1].wait()
        assert not (yield from started[2].is_done())

        yield from releases[0].succeed(None)
        yield from started[2].wait()
        yield from releases[1].succeed(None)
        yield from releases[2].succeed(None)

        assert (yield from fiber.join()) == input


@testing.effect
def test_supports_concurrency_unbounded():
    """product concurrency / supports concurrency: "unbounded\""""
    started = yield from _deferreds(3)
    release = yield from Deferred[None].make()

    def run(value: str, _: object) -> fx.Effect[str]:
        return started[ord(value) - 97].succeed(None).and_then(release.wait()).as_(value)

    schema = S.Array(S.String.pipe(S.decode(_both_ways(G.transform_effect(run)))))
    fiber = yield from S.decode_unknown_effect(schema)(
        ("a", "b", "c"), concurrency="unbounded"
    ).fork()

    for deferred in started:
        yield from deferred.wait()
    yield from release.succeed(None)
    assert (yield from fiber.join()) == ("a", "b", "c")


def _decoding(getter: G.Getter[str, str]) -> S.Bottom[str, str]:
    return S.String.pipe(S.decode(T.Transformation(getter, G.passthrough())))


@testing.effect
def test_uses_the_first_concurrent_failure_and_interrupts_pending_children():
    """product concurrency / uses the first concurrent failure to complete and interrupts pending children"""  # noqa: E501
    first_started = yield from Deferred[None].make()
    first_interrupted = yield from Deferred[None].make()
    first = _decoding(
        G.transform_effect(
            lambda _, __: (
                first_started.succeed(None)
                .and_then(fx.never)
                .on_interrupt(first_interrupted.succeed(None))
            )
        )
    )
    second = _decoding(
        G.transform_effect(
            lambda _, __: first_started.wait().and_then(
                fx.fail(InvalidValue({"message": "second failed"}))
            )
        )
    )

    exit = yield from S.decode_unknown_effect(S.Tuple(first, second))(
        ("a", "b"), concurrency=2
    ).exit()

    assert isinstance(exit, Failure)
    assert (yield from first_interrupted.is_done())
    issue = _issue(exit)
    assert isinstance(issue, Composite)
    assert isinstance(issue.issues[0], Pointer)
    assert issue.issues[0].path == (1,)


@testing.effect
def test_accumulates_concurrent_errors_in_completion_order():
    """product concurrency / accumulates concurrent errors in completion order with errors: "all\""""  # noqa: E501
    release_first = yield from Deferred[None].make()
    second_completed = yield from Deferred[None].make()

    def failing(effect: fx.Effect[Any]) -> S.Bottom[str, str]:
        return _decoding(G.transform_effect(lambda _, __: effect.and_then(fx.fail(InvalidValue()))))

    schema = S.Tuple(failing(release_first.wait()), failing(second_completed.succeed(None)))
    fiber = yield from (
        S.decode_unknown_effect(schema)(("a", "b"), concurrency=2, errors="all").exit().fork()
    )

    yield from second_completed.wait()
    yield from fx.yield_now()
    yield from release_first.succeed(None)
    exit = yield from fiber.join()

    assert isinstance(exit, Failure)
    issue = _issue(exit)
    assert isinstance(issue, Composite)
    assert [i.path for i in issue.issues if isinstance(i, Pointer)] == [(1,), (0,)]


@testing.effect
def test_uses_completion_order_for_colliding_transformed_record_keys():
    """product concurrency / uses completion order for colliding transformed Record keys"""
    release_first = yield from Deferred[None].make()
    second_completed = yield from Deferred[None].make()

    def run(value: str, _: object) -> fx.Effect[str]:
        if value == "first":
            return release_first.wait().as_(value)
        return second_completed.succeed(None).as_(value)

    schema = S.Record(
        S.String.pipe(S.decode(T.snake_to_camel())), _decoding(G.transform_effect(run))
    )
    fiber = yield from S.decode_unknown_effect(schema)(
        {"a_b": "first", "aB": "second"}, concurrency=2
    ).fork()

    yield from second_completed.wait()
    yield from fx.yield_now()
    yield from release_first.succeed(None)
    assert (yield from fiber.join()) == {"aB": "first"}


@testing.effect
def test_applies_the_concurrency_limit_independently_to_nested_products():
    """product concurrency / applies the concurrency limit independently to nested products"""
    started = yield from Ref.make(0)
    all_started = yield from Deferred[None].make()
    release = yield from Deferred[None].make()

    def run(value: str, _: object) -> fx.Effect[str]:
        return (
            started.update_and_get(lambda n: n + 1)
            .tap(lambda n: all_started.succeed(None) if n == 4 else fx.void)
            .and_then(release.wait())
            .as_(value)
        )

    schema = S.Array(S.Array(_decoding(G.transform_effect(run))))
    input = (("a", "b"), ("c", "d"))
    fiber = yield from S.decode_unknown_effect(schema)(input, concurrency=2).fork()

    yield from all_started.wait()
    assert (yield from started.get()) == 4
    yield from release.succeed(None)
    assert (yield from fiber.join()) == input


@testing.effect
def test_keeps_union_member_evaluation_sequential():
    """product concurrency / keeps Union member evaluation sequential"""
    first_started = yield from Deferred[None].make()
    release_first = yield from Deferred[None].make()
    second_started = yield from Deferred[None].make()
    first = _decoding(
        G.transform_effect(
            lambda _, __: first_started.succeed(None).and_then(release_first.wait()).as_("first")
        )
    )
    second = _decoding(G.transform_effect(lambda _, __: second_started.succeed(None).as_("second")))
    fiber = yield from S.decode_unknown_effect(S.Union(first, second))(
        "value", concurrency="unbounded"
    ).fork()

    yield from first_started.wait()
    yield from fx.yield_now()
    assert not (yield from second_started.is_done())
    yield from release_first.succeed(None)
    assert (yield from fiber.join()) == "first"
    assert not (yield from second_started.is_done())


def test_keeps_synchronous_product_parsers_eager():
    """product concurrency / keeps synchronous product parsers eager"""
    # An ``Exit`` is not an ``Effect`` in pyfect: the parse itself is one.
    result = S.Array(S.String).ast.parse(("a", "b"), {"concurrency": "unbounded"})
    assert result == succeed(("a", "b"))


def test_keeps_synchronous_transformations_eager():
    """decodeUnknownExit / keeps synchronous transformations eager"""
    assert S.NumberFromString.ast.parse("1", {}) == succeed(1)


def test_rejects_a_missing_root_output():
    """decodeUnknownExit / rejects a missing root output"""
    missing: G.Getter[str, str] = G.transform_optional_effect(lambda _, __: succeed(None))
    schema = S.String.pipe(S.decode(T.Transformation(missing, G.passthrough())))
    assert isinstance(S.decode_unknown_exit(schema)("value"), Failure)


def test_rejects_a_missing_root_output_after_parsing_structural_schemas():
    """decodeUnknownExit / rejects a missing root output after parsing structural schemas"""
    missing: G.Getter[Any, Any] = G.transform_optional_effect(lambda _, __: succeed(None))

    class Value(TypedDict):
        value: str

    array = S.Array(S.String).pipe(S.decode(T.Transformation(missing, missing)))
    struct = S.Struct(Value).pipe(S.decode(T.Transformation(missing, missing)))
    assert isinstance(S.decode_unknown_exit(array)(["value"]), Failure)
    assert isinstance(S.encode_unknown_exit(array)(["value"]), Failure)
    assert isinstance(S.decode_unknown_exit(struct)({"value": "value"}), Failure)
    assert isinstance(S.encode_unknown_exit(struct)({"value": "value"}), Failure)


@testing.effect
def test_preserves_unchanged_values_through_asynchronous_middleware():
    """decodeUnknownExit / preserves unchanged values through asynchronous middleware"""

    def delay(effect: fx.Effect[Option[str], Issue], _: object) -> fx.Effect[Option[str], Issue]:
        return fx.yield_now().and_then(effect)

    schema = S.String.pipe(S.middleware_decoding(delay))
    assert (yield from S.decode_unknown_effect(schema)("value")) == "value"


def _issue(exit: Failure[Any]) -> object:
    reason: Any = exit.cause.reasons[0]
    return reason.error.issue


def _delayed_failure() -> S.Bottom[str, str]:
    return _decoding(
        G.transform_optional_effect(lambda _, __: fx.yield_now().and_then(fx.fail(InvalidValue())))
    )


@testing.effect
def test_wraps_an_asynchronous_failure_from_a_uniquely_selected_union_member():
    """decodeUnknownExit / wraps an asynchronous failure from a uniquely selected union member"""

    class KindA(TypedDict):
        kind: Literal["a"]
        value: str

    class KindB(TypedDict):
        kind: Literal["b"]
        value: str

    schema = S.Union(S.Struct(KindA), S.Struct(KindB, value=_delayed_failure()))
    exit = yield from S.decode_unknown_effect(schema)({"kind": "b", "value": "value"}).exit()
    assert isinstance(exit, Failure)
    assert isinstance(_issue(exit), AnyOf)


@testing.effect
def test_resolves_an_unchanged_union_candidate_after_an_asynchronous_failure():
    """decodeUnknownExit / resolves an unchanged union candidate after an asynchronous failure"""
    schema = S.Union(_delayed_failure(), S.String)
    assert (yield from S.decode_unknown_effect(schema)("value")) == "value"


def test_does_not_replay_eager_fields_after_a_suspended_transformation():
    """decodeUnknownExit / does not replay eager fields after encountering a suspended transformation"""  # noqa: E501
    calls: list[str] = []

    def field(name: str, suspended: bool = False) -> S.Bottom[str, str]:
        def run(input: Option[str], _: object) -> fx.Effect[Option[str]] | Exit[Option[str], Any]:
            calls.append(name)
            return fx.suspend(lambda: fx.succeed(input)) if suspended else succeed(input)

        return _decoding(G.transform_optional_effect(run))

    schema = S.Struct(_ABC, a=field("a"), b=field("b", True), c=field("c"))
    exit = S.decode_unknown_exit(schema)({"a": "a", "b": "b", "c": "c"})
    assert isinstance(exit, Success)
    assert ",".join(calls) == "a,b,c"


@testing.effect
def test_keeps_earlier_results_intact_when_a_suspended_struct_decoder_is_run_again():
    """decodeUnknownExit / keeps earlier results intact when a suspended Struct decoder is run again"""  # noqa: E501
    ids = 0
    names = 0

    def next_id() -> float:
        nonlocal ids
        ids += 1
        return ids

    def upper(name: str) -> str:
        nonlocal names
        names += 1
        return name.upper()

    class Ids(TypedDict):
        name: str
        id: float
        nextId: float

    id = S.Number.pipe(
        S.decode(
            T.Transformation(G.transform_effect(lambda _, __: fx.sync(next_id)), G.passthrough())
        )
    )
    name = S.String.pipe(S.decode(T.Transformation(G.transform(upper), G.passthrough())))
    program = S.decode_unknown_effect(S.Struct(Ids, name=name, id=id, nextId=id))(
        {"name": "a", "id": 0, "nextId": 0}
    )
    first = yield from program
    second = yield from program
    assert [first, second] == [
        {"name": "A", "id": 1, "nextId": 2},
        {"name": "A", "id": 3, "nextId": 4},
    ]
    assert names == 1


def test_keeps_encoding_link_parser_compilation_lazy_for_suspend():
    """decodeUnknownExit / keeps encoding-link parser compilation lazy for Suspend"""
    evaluations = 0

    def make() -> S.Bottom[str]:
        nonlocal evaluations
        evaluations += 1
        return S.String

    passthrough: T.Transformation[str, str] = T.passthrough()
    schema = S.suspend(make).pipe(S.decode(passthrough))
    decode = S.decode_unknown_exit(schema)
    assert evaluations == 0
    assert isinstance(decode("a"), Success)
    assert evaluations == 1
    assert isinstance(decode("b"), Success)
    assert evaluations == 1


# ------------------------------------------------- adapters meeting a defect

_MIXED: Cause[Issue] = Cause((Fail(InvalidValue({"message": "schema issue"})), Die(_DEFECT)))


def _failing_declaration(cause: Cause[Issue]) -> S.Bottom[str]:
    def parser(input: object, node: object, options: object) -> fx.Effect[str, Issue]:
        return fx.fail_cause(cause)

    return S.declare_constructor((), lambda _: parser)


_DIES = Cause[Issue]((Die(_DEFECT),))


def _raises_with_defect(message: str, run: Callable[[], object]) -> None:
    with pytest.raises(RuntimeError) as raised:
        run()
    assert raised.value.args == (message,)
    assert raised.value.__cause__ is _DEFECT


def _transformed(cause: Cause[Issue]) -> tuple[S.Bottom[str, str], S.Bottom[str, str]]:
    getter: G.Getter[str, str] = G.transform_optional_effect(lambda _, __: fx.fail_cause(cause))
    decoding = S.String.pipe(S.decode(T.Transformation(getter, G.passthrough())))
    encoding = S.String.pipe(S.encode(T.Transformation(G.passthrough(), getter)))
    return decoding, encoding


def test_make_should_throw_an_error_when_the_cause_contains_both_an_issue_and_a_defect():
    """make / should throw an error when the cause contains both an Issue and a defect"""
    # Effect fails a ``withConstructorDefault``; pyfect's field defaults are
    # plain values, so a declaration's parser gives the mixed cause.
    schema = _failing_declaration(_MIXED)
    _raises_with_defect(
        "Constructor adapter can only throw schema issues", lambda: schema.make("a")
    )


def test_make_option_should_throw_an_error_when_the_cause_is_not_an_issue():
    """makeOption / should throw an error when the cause is not an Issue"""
    schema = _failing_declaration(_DIES)
    _raises_with_defect(
        "Option adapter can only return none for schema issues", lambda: schema.make_option("a")
    )


def test_make_option_should_throw_an_error_when_the_cause_contains_both_an_issue_and_a_defect():
    """makeOption / should throw an error when the cause contains both an Issue and a defect"""
    schema = _failing_declaration(_MIXED)
    _raises_with_defect(
        "Option adapter can only return none for schema issues", lambda: schema.make_option("a")
    )


def test_sync_should_throw_an_error_when_the_cause_contains_both_an_issue_and_a_defect():
    """decodeUnknownSync / encodeUnknownSync / should throw an error when the cause contains both an Issue and a defect"""  # noqa: E501
    decoding, encoding = _transformed(_MIXED)
    message = "Sync adapter can only throw schema errors"
    _raises_with_defect(message, lambda: S.decode_unknown_sync(decoding)("a"))
    _raises_with_defect(message, lambda: S.encode_unknown_sync(encoding)("a"))


@pytest.mark.parametrize("cause", [_DIES, _MIXED], ids=["not an Issue", "an Issue and a defect"])
def test_option_should_throw_an_error_when_the_cause_is_not_only_issues(cause: Cause[Issue]):
    """decodeUnknownOption / encodeUnknownOption / should throw an error when the cause is not an Issue
    decodeUnknownOption / encodeUnknownOption / should throw an error when the cause contains both an Issue and a defect"""  # noqa: E501
    decoding, encoding = _transformed(cause)
    message = "Option adapter can only return none for schema issues"
    _raises_with_defect(message, lambda: S.decode_unknown_option(decoding)("a"))
    _raises_with_defect(message, lambda: S.encode_unknown_option(encoding)("a"))


@pytest.mark.parametrize("cause", [_DIES, _MIXED], ids=["not an Issue", "an Issue and a defect"])
def test_is_should_throw_an_error_when_the_cause_is_not_only_issues(cause: Cause[Issue]):
    """is / should throw an error when the cause is not an Issue
    is / should throw an error when the cause contains both an Issue and a defect"""
    guard = S.is_(_failing_declaration(cause))
    _raises_with_defect(
        "Type guard adapter can only return false for schema issues", lambda: guard("a")
    )


class _StringsAB(TypedDict):
    a: str
    b: str


def test_asserts_should_use_the_default_parse_options():
    """asserts / should use the default parse options"""
    schema = S.Struct(_StringsAB)
    # ``errors="all"`` would report both keys.
    with pytest.raises(S.SchemaError, match=r'^Expected string\n  at \["a"\]$'):
        S.asserts(schema, {"a": 1, "b": 2})
    # ``on_excess_property="error"`` would reject the excess key.
    S.asserts(schema, {"a": "a", "b": "b", "c": 1})


class _FiniteA(TypedDict):
    a: float


def test_asserts_should_assert_the_type_side_of_the_schema():
    """asserts / should assert the type side of the schema"""
    schema = S.Struct(_FiniteA, a=S.FiniteFromString)
    S.asserts(schema, {"a": 1})
    with pytest.raises(S.SchemaError, match=r'^Expected number\n  at \["a"\]$'):
        S.asserts(schema, {"a": "1"})


@pytest.mark.parametrize("cause", [_DIES, _MIXED], ids=["not an Issue", "an Issue and a defect"])
def test_asserts_should_throw_an_error_when_the_cause_is_not_only_issues(cause: Cause[Issue]):
    """asserts / should throw an error when the cause is not an Issue
    asserts / should throw an error when the cause contains both an Issue and a defect"""
    schema = _failing_declaration(cause)
    _raises_with_defect(
        "Assertion adapter can only throw schema issues", lambda: S.asserts(schema, "a")
    )


@pytest.mark.parametrize("cause", [_DIES, _MIXED], ids=["not an Issue", "an Issue and a defect"])
def test_result_should_throw_an_error_when_the_cause_is_not_only_issues(cause: Cause[Issue]):
    """decodeUnknownResult / encodeUnknownResult / should throw an error when the cause is not an Issue
    decodeUnknownResult / encodeUnknownResult / should throw an error when the cause contains both an Issue and a defect"""  # noqa: E501
    decoding, encoding = _transformed(cause)
    message = "Result adapter can only return schema issues"
    _raises_with_defect(message, lambda: S.decode_unknown_result(decoding)("a"))
    _raises_with_defect(message, lambda: S.encode_unknown_result(encoding)("a"))


# ------------------------------------------------- decodeUnknownExit internals


class _CountingMapping(Mapping[str, object]):
    """A mapping whose ``value`` is ``"a"`` on its first read only (Effect's
    getter property)."""

    def __init__(self) -> None:
        self.reads = 0

    def __getitem__(self, key: str) -> object:
        if key != "value":
            raise KeyError(key)
        self.reads += 1
        return "a" if self.reads == 1 else 1

    def __contains__(self, key: object) -> bool:
        return key == "value"

    def __iter__(self) -> Iterator[str]:
        return iter(("value",))

    def __len__(self) -> int:
        return 1


class _Value(TypedDict):
    value: str


def test_reads_property_and_index_values_once():
    """decodeUnknownExit / reads property and index values once"""
    property = _CountingMapping()
    assert S.decode_unknown_exit(S.Struct(_Value))(property) == succeed({"value": "a"})
    assert property.reads == 1

    index = _CountingMapping()
    assert S.decode_unknown_exit(S.Record(S.String, S.String))(index) == succeed({"value": "a"})
    assert index.reads == 1

    rejected_getter: G.Getter[str, str] = G.transform_optional_effect(
        lambda _, __: fx.fail(InvalidValue())
    )
    rejected_key = S.String.pipe(S.decode(T.Transformation(rejected_getter, G.passthrough())))
    rejected = _CountingMapping()
    exit = S.decode_unknown_exit(S.Record(rejected_key, S.String))(rejected)
    assert isinstance(exit, Failure)
    assert rejected.reads == 0


class _Nested(TypedDict):
    value: object


def test_rejects_an_invalid_root_without_compiling_deeply_nested_structural_parsers():
    """decodeUnknownExit / rejects an invalid root without compiling deeply nested structural parsers"""  # noqa: E501
    array: S.Bottom[Any, Any] = S.String
    struct: S.Bottom[Any, Any] = S.String
    for _ in range(5_000):
        array = S.Array(array)
        struct = S.Struct(_Nested, value=struct)
    assert isinstance(S.decode_unknown_exit(array)(None), Failure)
    assert isinstance(S.decode_unknown_exit(struct)(None), Failure)


def test_stops_outer_checks_after_an_aborting_check_in_a_filter_group():
    """decodeUnknownExit / stops outer checks after an aborting check in a FilterGroup"""
    inner_runs = 0
    outer_runs = 0

    def inner(_: str) -> bool:
        nonlocal inner_runs
        inner_runs += 1
        return False

    def outer(_: str) -> bool:
        nonlocal outer_runs
        outer_runs += 1
        return False

    def fails(_: str) -> bool:
        return False

    group = S.make_filter(fails).abort().and_(S.make_filter(inner))
    schema = S.String.check(group, S.make_filter(outer))
    assert isinstance(S.decode_unknown_exit(schema, errors="all")("value"), Failure)
    assert inner_runs == 0
    assert outer_runs == 0


class _Field(TypedDict):
    field: str


def test_converts_synchronous_property_parser_throws_into_defects():
    """decodeUnknownExit / converts synchronous property parser throws into defects"""
    field: S.Bottom[str] = S.declare_constructor((), lambda _: _raise)
    exit = S.decode_unknown_exit(S.Struct(_Field, field=field))({"field": "value"})
    assert exit == die(_DEFECT)


def test_keeps_direct_suspend_parser_compilation_lazy():
    """decodeUnknownExit / keeps direct Suspend parser compilation lazy"""
    evaluations = 0

    def make() -> S.Bottom[str]:
        nonlocal evaluations
        evaluations += 1
        return S.String

    decode = S.decode_unknown_exit(S.suspend(make))
    assert evaluations == 0
    assert isinstance(decode("a"), Success)
    assert evaluations == 1
    assert isinstance(decode("b"), Success)
    assert evaluations == 1


class _A(TypedDict):
    _tag: Literal["A"]
    next: "str | _B"


class _B(TypedDict):
    _tag: Literal["B"]
    next: "str | _A"


def test_supports_mutually_recursive_suspend_parsers():
    """decodeUnknownExit / supports mutually recursive Suspend parsers"""
    a: S.Bottom[_A, Any] = S.Struct(_A, next=S.Union(S.String, S.suspend(lambda: b)))
    b: S.Bottom[_B, Any] = S.Struct(_B, next=S.Union(S.String, S.suspend(lambda: a)))
    input = {"_tag": "A", "next": {"_tag": "B", "next": {"_tag": "A", "next": "end"}}}
    assert S.decode_unknown_exit(a)(input) == succeed(input)


def _unchanged(input: object, *_: object) -> Exit[object, Never]:
    return succeed(input)


def _counting_declaration() -> tuple[S.Bottom[object], Callable[[], int]]:
    evaluations = 0

    def run(_: object) -> Callable[..., Exit[object, Never]]:
        nonlocal evaluations
        evaluations += 1
        return _unchanged

    return S.declare_constructor((), run), lambda: evaluations


def test_keeps_declaration_parser_compilation_lazy_and_shared_by_ast_identity():
    """decodeUnknownExit / keeps Declaration parser compilation lazy and shared by AST identity"""
    schema, evaluations = _counting_declaration()
    decode = S.decode_unknown_exit(schema)
    decode_again = S.decode_unknown_exit(schema)
    assert evaluations() == 0
    assert isinstance(decode("a"), Success)
    assert evaluations() == 1
    assert isinstance(decode_again("b"), Success)
    assert evaluations() == 1


def test_keeps_untried_declaration_union_members_lazy():
    """decodeUnknownExit / keeps untried Declaration union members lazy"""
    declaration, evaluations = _counting_declaration()
    decode = S.decode_unknown_exit(S.Union(S.Literal("a"), declaration))
    assert isinstance(decode("a"), Success)
    assert evaluations() == 0
    assert isinstance(decode("b"), Success)
    assert evaluations() == 1


def test_keeps_encode_side_declaration_and_suspend_parser_compilation_lazy():
    """decodeUnknownExit / keeps encode-side Declaration and Suspend parser compilation lazy"""
    declaration, declaration_evaluations = _counting_declaration()
    suspend_evaluations = 0

    def make() -> S.Bottom[str]:
        nonlocal suspend_evaluations
        suspend_evaluations += 1
        return S.String

    encode_declaration = S.encode_unknown_exit(declaration)
    encode_suspend = S.encode_unknown_exit(S.suspend(make))
    assert (declaration_evaluations(), suspend_evaluations) == (0, 0)
    assert isinstance(encode_declaration("a"), Success)
    assert isinstance(encode_suspend("a"), Success)
    assert (declaration_evaluations(), suspend_evaluations) == (1, 1)
    assert isinstance(encode_declaration("b"), Success)
    assert isinstance(encode_suspend("b"), Success)
    assert (declaration_evaluations(), suspend_evaluations) == (1, 1)


class _FactoryDefect(Exception):
    pass


@pytest.mark.parametrize("operation", ["decode", "encode"])
def test_retries_failed_factories_and_reuses_eager_parsers_after_defects(operation: str):
    """decodeUnknownExit / ${operation} retries failed factories and reuses eager parsers after defects"""  # noqa: E501
    factory_defect = _FactoryDefect("factory defect")
    parser_defect = _Defect("parser defect")
    factories = 0
    calls: list[object] = []

    def parser(input: object, *_: object) -> Exit[object, Never]:
        calls.append(input)
        if input == "bad":
            raise parser_defect
        return succeed(input)

    def run(_: object) -> Callable[..., Exit[object, Never]]:
        nonlocal factories
        factories += 1
        if factories == 1:
            raise factory_defect
        return parser

    def passes(_: object) -> bool:
        return True

    declared: S.Bottom[object] = S.declare_constructor((), run)
    schema = declared.check(S.make_filter(passes))
    parse = (
        S.decode_unknown_effect(schema)
        if operation == "decode"
        else S.encode_unknown_effect(schema)
    )
    assert factories == 0
    with pytest.raises(_FactoryDefect) as raised:
        parse("value")
    assert raised.value is factory_defect
    assert S.decode_unknown_exit(schema)("bad") == die(parser_defect)
    assert S.decode_unknown_exit(schema)("good") == succeed("good")
    assert calls == ["bad", "good"]
    assert factories == 2


@pytest.mark.parametrize("kind", ["Declaration", "Suspend"])
@pytest.mark.parametrize("operation", ["decode", "encode"])
def test_retries_failed_child_factories_inside_option_callbacks(operation: str, kind: str):
    """decodeUnknownExit / ${operation} retries failed child ${kind} factories inside Option callbacks"""  # noqa: E501
    factory_defect = _FactoryDefect("factory defect")
    factories = 0

    def failing_first() -> None:
        nonlocal factories
        factories += 1
        if factories == 1:
            raise factory_defect

    def run(_: object) -> Callable[..., Exit[object, Never]]:
        failing_first()
        return _unchanged

    def thunk() -> S.Bottom[str]:
        failing_first()
        return S.String

    child: S.Bottom[object] = (
        S.declare_constructor((), run) if kind == "Declaration" else S.suspend(thunk)
    )
    schema = S.Option(child)
    parse = (
        S.decode_unknown_exit(schema) if operation == "decode" else S.encode_unknown_exit(schema)
    )
    assert factories == 0
    assert parse(Some("value")) == die(factory_defect)
    assert factories == 1
    assert parse(Some("value")) == succeed(Some("value"))
    assert factories == 2


def test_retries_lazy_suspend_parser_compilation_after_a_synchronous_thunk_failure():
    """decodeUnknownExit / retries lazy Suspend parser compilation after a synchronous thunk failure"""  # noqa: E501
    evaluations = 0

    def thunk() -> S.Bottom[str]:
        nonlocal evaluations
        evaluations += 1
        if evaluations == 1:
            raise _Defect("thunk failure")
        return S.String

    decode = S.decode_unknown_exit(S.suspend(thunk))
    with pytest.raises(_Defect, match=r"^thunk failure$"):
        decode("a")
    assert isinstance(decode("b"), Success)
    assert isinstance(decode("c"), Success)
    assert evaluations == 2


class _KindA(TypedDict):
    kind: Literal["a"]
    value: str


class _KindB(TypedDict):
    kind: Literal["b"]
    value: str


def test_should_preserve_mixed_causes_in_union_candidates_instead_of_trying_later_candidates():
    """decodeUnknownExit / should preserve mixed causes in union candidates instead of trying later candidates"""  # noqa: E501
    failure, _ = _transformed(_MIXED)
    schema = S.Union(failure, S.Literal("a"))
    tagged = S.Union(S.Struct(_KindA, value=failure), S.Struct(_KindB))
    for exit in (
        S.decode_unknown_exit(schema)("a"),
        S.decode_unknown_exit(tagged)({"kind": "a", "value": "a"}),
    ):
        assert isinstance(exit, Failure)
        assert any(isinstance(r, Die) for r in exit.cause.reasons)
        assert isinstance(exit.cause.find_error(), Ok)
