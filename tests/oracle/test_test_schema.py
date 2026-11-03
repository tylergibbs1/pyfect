"""Ports of Effect's ``testing/TestSchema.test.ts``.

``TestSchema.Asserts`` is ``testing.SchemaAsserts``; the Promise methods are
the synchronous ``succeed`` / ``fail``, the ``Effect`` methods
``succeed_effect`` / ``fail_effect``. JavaScript's ``undefined`` is
``None``; ``parseOptions`` are keyword arguments.

Omitted, with the reason:

- the ``ast.fields.equals`` titles ("compares string and symbol fields by
  AST", "rejects missing or structurally different symbol fields",
  "preserves symbol identity even with equal descriptions", "preserves own
  __proto__ and constructor fields", "uses the Struct own-key contract for
  non-enumerable fields"): they test JavaScript's symbol keys and own-key
  rules for a field-comparison helper pyfect does not have; a struct's
  fields are a ``dict``.
- "verifyGeneration bounds residual discards": fast-check's ``maxDiscards``;
  Hypothesis's own ``filter_too_much`` health check plays that part.
- "make uses constructor defaults from the test environment and honors
  disableChecks" and "make preserves mixed causes from constructor
  defaults": ``withConstructorDefault`` is not ported (docs/coverage/schema.md).
- the ``make`` case of "forwards parsing options": a filter sees only the
  value in pyfect; the decoding and encoding cases read the options through
  ``check_effect``.
- the ``verifyRoundTripEffect`` titles ("round trips preserve mixed causes
  from ${method}", "round trips use both decoding and encoding services
  lazily", "round-trip assertion defects report shrunk inputs and replay",
  "round trips preserve schema defects", "roundTrip propagates interruption
  and runs finalizers"): ``verify_round_trip`` runs synchronously under
  Hypothesis's ``given``; an effect form needs a property runner that draws
  inside a fiber (deferred, docs/PARITY.md M11).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal, Never, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.cause import (
    Cause,
    Die,
    Fail,
    Interrupt,
    UnhandledError,
    from_reasons,
    reason_annotations,
)
from pyfect.exit import Failure
from pyfect.option import Option
from pyfect.schema import SchemaError
from pyfect.schema import getter as G
from pyfect.schema import transformation as T
from pyfect.schema.issue import InvalidType, InvalidValue, Issue
from pyfect.testing import SchemaAsserts, SchemaCheck

type Method = Literal["decoding", "encoding", "make"]
type Direction = Literal["decoding", "encoding"]


def _check[R](asserts: SchemaAsserts[R, R], method: Method) -> SchemaCheck[R]:
    return getattr(asserts, method)()


class Service(fx.Tag[str], key="Service"):
    pass


def _not_empty_with_service(
    text: str, _options: S.ParseOptions
) -> fx.Effect[G.CheckOutput, Never, Service]:
    return Service().map(
        lambda _: (
            InvalidValue({"message": "input should not be empty string"}) if text == "" else None
        )
    )


def test_decoding() -> None:
    """decoding"""
    decoding = SchemaAsserts(S.FiniteFromString.check(S.is_greater_than(0))).decoding()
    decoding.succeed("1", 1)
    decoding.fail("-1", "Expected a value greater than 0")
    decoding.fail("a", "Expected a finite number")


def test_decoding_provide() -> None:
    """decoding.provide"""
    schema = S.String.pipe(
        S.decode(T.Transformation(G.check_effect(_not_empty_with_service), G.passthrough()))
    )
    decoding = SchemaAsserts(schema).decoding().provide(Service, "b")
    decoding.succeed("a")
    decoding.fail("", "input should not be empty string")


def test_encoding() -> None:
    """encoding"""
    encoding = SchemaAsserts(S.FiniteFromString.check(S.is_greater_than(0))).encoding()
    encoding.succeed(1, "1")
    encoding.fail(-1, "Expected a value greater than 0")


def test_encoding_provide() -> None:
    """encoding.provide"""
    schema = S.String.pipe(
        S.decode(T.Transformation(G.passthrough(), G.check_effect(_not_empty_with_service)))
    )
    encoding = SchemaAsserts(schema).encoding().provide(Service, "b")
    encoding.succeed("a")
    encoding.fail("", "input should not be empty string")


def test_verify_round_trip() -> None:
    """verifyRoundTrip"""
    SchemaAsserts(S.FiniteFromString.check(S.is_greater_than(0))).verify_round_trip(runs=20, seed=1)


class _A(TypedDict):
    a: str


def test_round_trips_accept_equivalent_struct_objects_regardless_of_prototype() -> None:
    """round trips accept equivalent struct objects regardless of prototype"""
    SchemaAsserts(S.Struct(_A)).verify_round_trip(runs=100, seed=1)


def test_number_from_string_round_trips_accept_equivalent_signed_zeros() -> None:
    """NumberFromString round trips accept equivalent signed zeros"""
    SchemaAsserts(S.NumberFromString).verify_round_trip(runs=100, seed=1)


def test_verify_round_trip_reports_a_shrunk_input_and_replay() -> None:
    """verifyRoundTrip reports a shrunk input and replay"""
    lossy = S.Number.pipe(
        S.decode_to(S.Number, T.transform(decode=lambda value: value, encode=lambda _: 0.0))
    )
    with pytest.raises(AssertionError, match="did not round-trip") as raised:
        SchemaAsserts(lossy).verify_round_trip(runs=20, seed=1)
    # Hypothesis shrinks to the smallest failing value and notes it, for a
    # replay (fast-check's "Shrunk input" and "Replay").
    notes = "\n".join(getattr(raised.value, "__notes__", []))
    assert "check(" in notes and "value=" in notes


# --- the Effect assertions, per method ----------------------------------------------


@pytest.mark.parametrize("method", ["decoding", "encoding", "make"])
@testing.effect
def test_defers_parsing_and_reruns_it_on_every_execution(method: Method):
    """${method} Effect assertions: defers parsing and reruns it on every execution"""
    calls: list[str] = []

    def ok(value: str) -> bool | str:
        calls.append(value)
        return value == "ok" or "Expected ok"

    assertions = _check(SchemaAsserts(S.String.check(S.make_filter(ok))), method)
    success = assertions.succeed_effect("ok")
    failure = assertions.fail_effect("bad", "Expected ok")
    assert calls == []
    yield from success
    yield from success
    yield from failure
    assert len(calls) == 3


def _assertion_defect(ex: fx.Exit[None, Never]) -> AssertionError:
    assert isinstance(ex, Failure)
    assert not ex.cause.has_fails
    error = ex.cause.squash()
    assert isinstance(error, AssertionError)
    return error


@pytest.mark.parametrize("method", ["decoding", "encoding", "make"])
@testing.effect
def test_preserves_explicit_undefined_and_reports_mismatches_as_defects(method: Method):
    """preserves explicit undefined and reports mismatches as defects"""
    assertions = _check(SchemaAsserts(S.Unknown), method)
    yield from assertions.succeed_effect("value")
    yield from assertions.succeed_effect(None)
    error = _assertion_defect((yield from assertions.succeed_effect("value", None).exit()))
    assert str(error) == "expected Ok(value=None), got Ok(value='value')"

    strings = _check(
        SchemaAsserts(
            S.String.check(S.make_filter(lambda v: len(v) > 0 or "Expected nonempty string"))
        ),
        method,
    )
    for eff in (
        strings.succeed_effect(""),
        strings.fail_effect("valid", "Expected string"),
        strings.fail_effect(123, "wrong message"),
    ):
        _assertion_defect((yield from eff.exit()))


@pytest.mark.parametrize("method", ["decoding", "encoding", "make"])
def test_preserves_promise_assertion_errors_and_explicit_undefined(method: Method) -> None:
    """${method} Effect assertions: preserves Promise assertion errors and explicit undefined"""
    assertions = _check(SchemaAsserts(S.Unknown), method)
    assertions.succeed("value")
    with pytest.raises(AssertionError):
        assertions.succeed("value", None)
    with pytest.raises(AssertionError):
        assertions.fail("value", "wrong message")


def _all_errors(_value: str, options: S.ParseOptions) -> fx.Effect[G.CheckOutput]:
    return fx.succeed(
        None if options.get("errors") == "all" else InvalidValue({"message": "Expected all errors"})
    )


@pytest.mark.parametrize("method", ["decoding", "encoding"])
@testing.effect
def test_forwards_parsing_options(method: Direction):
    """${method} Effect assertions: forwards parsing options"""
    check = G.check_effect(_all_errors)
    asserts = SchemaAsserts(S.String.pipe(S.decode(T.Transformation(check, check))))
    yield from getattr(asserts, method)(errors="all").succeed_effect("value")
    yield from getattr(asserts, method)().fail_effect("value", "Expected all errors")


class SchemaDefect(Exception):
    pass


@pytest.mark.parametrize("method", ["decoding", "encoding", "make"])
@testing.effect
def test_preserves_thrown_schema_defects_in_success_and_failure_assertions(method: Method):
    """preserves thrown schema defects in success and failure assertions"""
    defect = SchemaDefect("schema defect")

    def raising(_value: str) -> Never:
        raise defect

    assertions = _check(SchemaAsserts(S.String.check(S.make_filter(raising))), method)
    for eff in (
        assertions.succeed_effect("value"),
        assertions.fail_effect("value", "schema defect"),
    ):
        ex = yield from eff.exit()
        assert isinstance(ex, Failure)
        assert ex.cause.find_defect() is defect
        assert not ex.cause.has_fails


@testing.effect
def test_asserts_decoded_and_encoded_transformations():
    """asserts decoded and encoded transformations"""
    asserts = SchemaAsserts(S.NumberFromString)
    yield from asserts.decoding().succeed_effect("42", 42)
    yield from asserts.encoding().succeed_effect(42, "42")
    yield from asserts.decoding().fail_effect(None, "Expected string")
    yield from asserts.encoding().fail_effect(None, "Expected number")


# --- decoding and encoding ----------------------------------------------------------


type _Wrap = Callable[
    [fx.Effect[Option[str], Issue], S.ParseOptions], fx.Effect[Option[str], Issue]
]


def _middleware(method: Direction, f: _Wrap) -> S.Codec[str, str]:
    if method == "decoding":
        return S.String.pipe(S.middleware_decoding(f))
    return S.String.pipe(S.middleware_encoding(f))


class CleanupFailed(Exception):
    pass


@pytest.mark.parametrize("method", ["decoding", "encoding"])
@testing.effect
def test_preserves_validation_failures_and_defective_finalizers(method: Direction):
    """${method} preserves validation failures and defective finalizers"""
    defect = CleanupFailed("cleanup failed")

    def finalize(
        eff: fx.Effect[Option[str], Issue], _options: S.ParseOptions
    ) -> fx.Effect[Option[str], Issue]:
        return eff.ensuring(fx.die(defect))

    schema = _middleware(method, finalize)
    assertions: SchemaCheck[Never] = getattr(SchemaAsserts(schema), method)()
    for eff in (
        assertions.succeed_effect(123, "value"),
        assertions.fail_effect(123, "Expected string"),
    ):
        ex = yield from eff.exit()
        assert isinstance(ex, Failure)
        validation, cleanup = ex.cause.reasons
        # The finalizer's defect elects the issue to a defect where it
        # happens, wrapped so it can be raised (section 4, ``Cause.squash``).
        assert isinstance(validation, Die)
        assert isinstance(validation.defect, UnhandledError)
        assert isinstance(validation.defect.error, InvalidType)
        assert cleanup == Die(defect)
    with pytest.raises(AssertionError):
        assertions.fail(123, "Expected string")


class Metadata(fx.Tag[str], key="Metadata"):
    pass


@pytest.mark.parametrize("method", ["decoding", "encoding"])
@testing.effect
def test_preserves_interruption_alongside_annotated_validation_failures(method: Direction):
    """${method} preserves interruption alongside annotated validation failures"""
    annotations = fx.Context.make(Metadata, "validation")
    issue = InvalidValue({"message": "schema issue"})
    interrupt = Interrupt(123)
    failure: Cause[Issue] = from_reasons([Fail(issue).annotate(annotations), interrupt])

    def fail_with(
        _eff: fx.Effect[Option[str], Issue], _options: S.ParseOptions
    ) -> fx.Effect[Option[str], Issue]:
        return fx.fail_cause(failure)

    assertions: SchemaCheck[Never] = getattr(
        SchemaAsserts(_middleware(method, fail_with)), method
    )()
    for eff in (
        assertions.succeed_effect("value"),
        assertions.fail_effect("value", "schema issue"),
    ):
        ex = yield from eff.exit()
        assert isinstance(ex, Failure)
        validation, interruption = ex.cause.reasons
        assert isinstance(validation, Die)
        assert isinstance(validation.defect, SchemaError)
        assert validation.defect.message == "schema issue"
        assert reason_annotations(validation).get_or_none(Metadata) == "validation"
        assert interruption == interrupt


def _expected_check(
    value: str, _options: S.ParseOptions
) -> fx.Effect[G.CheckOutput, Never, Service]:
    return Service().map(
        lambda expected: (
            None if value == expected else InvalidValue({"message": "Unexpected value"})
        )
    )


@pytest.mark.parametrize("method", ["decoding", "encoding"])
@testing.effect
def test_inherits_layer_services_and_supports_provide(method: Direction):
    """${method} inherits layer services and supports provide"""
    check = G.check_effect(_expected_check)
    schema = S.String.pipe(S.decode(T.Transformation(check, check)))
    assertions: SchemaCheck[Service] = getattr(SchemaAsserts(schema), method)()

    @fx.gen
    def provided():
        yield from assertions.succeed_effect("provided")
        yield from assertions.fail_effect("wrong", "Unexpected value")

    yield from provided.pipe(fx.provide(fx.layer.succeed(Service, "provided")))
    yield from assertions.provide(Service, "local").succeed_effect("local")
    yield from assertions.provide(Service, "local").fail_effect("wrong", "Unexpected value")


def _now_check(value: float, _options: S.ParseOptions) -> fx.Effect[G.CheckOutput]:
    return fx.clock.now().map(
        lambda now: (
            None if value == round(now * 1000) else InvalidValue({"message": "Unexpected time"})
        )
    )


@pytest.mark.parametrize("method", ["decoding", "encoding"])
@testing.effect
def test_reads_the_test_clock(method: Direction):
    """${method} reads the test clock"""
    check = G.check_effect(_now_check)
    schema = S.Number.pipe(S.decode(T.Transformation(check, check)))
    assertions: SchemaCheck[Never] = getattr(SchemaAsserts(schema), method)()
    yield from testing.set_time(0.123)
    yield from assertions.succeed_effect(123)
    yield from assertions.fail_effect(0, "Unexpected time")


@pytest.mark.parametrize("method", ["decoding", "encoding"])
@testing.effect
def test_propagates_interruption_and_runs_finalizers(method: Direction):
    """${method} propagates interruption and runs finalizers"""
    started = yield from fx.Deferred[None].make()
    finalized = yield from fx.Ref.make(False)

    def hang(_value: str, _options: S.ParseOptions) -> fx.Effect[G.CheckOutput]:
        return started.succeed(None).and_then(fx.never).ensuring(finalized.set(True))

    check = G.check_effect(hang)
    schema = S.String.pipe(S.decode(T.Transformation(check, check)))
    assertions: SchemaCheck[Never] = getattr(SchemaAsserts(schema), method)()
    fiber = yield from assertions.fail_effect("value", "should not pass").fork()
    yield from started.wait()
    yield from fiber.interrupt()
    assert (yield from finalized.get())
    ex = yield from fiber.await_exit()
    assert isinstance(ex, Failure)
    assert ex.cause.has_interrupts_only
