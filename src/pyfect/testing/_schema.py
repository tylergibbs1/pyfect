"""Schema test assertions (Effect's ``TestSchema.Asserts``)::

    asserts = testing.SchemaAsserts(S.String)
    asserts.decoding().succeed("a")
    asserts.decoding().fail(1, "Expected string")
    asserts.encoding(report_input=True).fail(1, "Expected string, got 1")

``succeed(input)`` expects the input back; ``succeed(input, expected)`` a
given value. ``fail(input, message)`` expects a schema failure whose issue
prints as ``message``. A defect fails the assertion with the whole cause.
``succeed_effect`` / ``fail_effect`` are the same assertions as effects
that parse each time they run, with the running fiber's services: a
mismatch is an ``AssertionError`` defect. ``verify_generation()`` checks
the values ``to_strategy`` draws; ``verify_round_trip()`` that each one
encodes and decodes back to an equivalent value.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, Never, TypeVar, Unpack

from pyfect._core import Effect
from pyfect._extras import missing_extra
from pyfect.cause import Cause, Die, Fail, from_reasons
from pyfect.context import Context, TagLike
from pyfect.effect import context, fail_cause, provide_service, succeed, suspend, sync, void
from pyfect.exit import Exit, Failure, Success
from pyfect.result import Err, Ok, Result
from pyfect.run import run_sync, run_sync_exit
from pyfect.schema import (
    Codec,
    ParseOptions,
    SchemaError,
    decode_unknown_effect,
    encode_unknown_effect,
    is_,
    to_equivalence,
    to_strategy,
)
from pyfect.testing._assertions import describe_exit

_SAME = object()
R_co = TypeVar("R_co", covariant=True)
RD_co = TypeVar("RD_co", covariant=True)
RE_co = TypeVar("RE_co", covariant=True)


def _schema_result[R](
    eff: Effect[object, SchemaError, R],
) -> Effect[Result[object, str], Never, R]:
    """``Ok(value)``, or ``Err(message)`` for a failure made only of schema
    errors; any other cause stays a failure, its typed errors made defects
    (Effect's ``schemaResult``)."""

    def from_exit(ex: Exit[object, SchemaError]) -> Effect[Result[object, str], Never, R]:
        if isinstance(ex, Success):
            return succeed(Ok(ex.value))
        reasons = ex.cause.reasons
        if reasons and all(isinstance(r, Fail) for r in reasons):
            first = reasons[0]
            assert isinstance(first, Fail)
            return succeed(Err(first.error.message))
        return fail_cause(_as_defects(ex.cause))

    return eff.exit().flat_map(from_exit)


def _as_defects(cause: Cause[SchemaError]) -> Cause[Never]:
    return from_reasons(
        Die(r.error, annotations=r.annotations) if isinstance(r, Fail) else r for r in cause.reasons
    )


def _assert_result(actual: Result[object, str], expected: Result[object, str]) -> None:
    if actual != expected:
        raise AssertionError(f"expected {expected!r}, got {actual!r}")


@dataclass(frozen=True, slots=True)
class SchemaCheck(Generic[R_co]):
    """Assertions on one direction of a schema: make, decode or encode,
    needing the services ``R``. Assertions run once none are left:
    ``provide(tag, service)`` gives a direction its one service."""

    parse: Callable[[object], Effect[object, SchemaError, R_co]]

    def run(self: SchemaCheck[Never], input: object) -> Exit[object, SchemaError]:
        return run_sync_exit(self.parse(input))

    def provide[S, T](self: SchemaCheck[T], tag: TagLike[S, T], service: S) -> SchemaCheck[Never]:
        parse = self.parse
        return SchemaCheck(lambda input: parse(input).pipe(provide_service(tag, service)))

    def succeed(self: SchemaCheck[Never], input: object, expected: object = _SAME) -> None:
        want = input if expected is _SAME else expected
        ex = self.run(input)
        if not (isinstance(ex, Success) and ex.value == want):
            raise AssertionError(f"expected Success({want!r}), got {describe_exit(ex)}")

    def succeed_effect(self, input: object, expected: object = _SAME) -> Effect[None, Never, R_co]:
        """``succeed`` as an effect, parsing each time it runs."""
        want: Result[object, str] = Ok(input if expected is _SAME else expected)
        return self._assert_effect(input, want)

    def fail_effect(self, input: object, message: str) -> Effect[None, Never, R_co]:
        """``fail`` as an effect, parsing each time it runs."""
        return self._assert_effect(input, Err(message))

    def _assert_effect(
        self, input: object, expected: Result[object, str]
    ) -> Effect[None, Never, R_co]:
        parse = self.parse
        return suspend(lambda: _schema_result(parse(input))).flat_map(
            lambda actual: sync(lambda: _assert_result(actual, expected))
        )

    def fail(self: SchemaCheck[Never], input: object, message: str) -> None:
        ex = self.run(input)
        if isinstance(ex, Failure) and len(ex.cause.reasons) == 1:
            match ex.cause.find_error():
                case Ok(error) if error.message == message:
                    return
                case _:
                    pass
        raise AssertionError(f"expected a SchemaError {message!r}, got {describe_exit(ex)}")


class _Abort(BaseException):
    """Ends a Hypothesis run at once (it shrinks on an ``Exception``) with
    a round trip's cause that is not an assertion failure."""

    def __init__(self, cause: Cause[Never]) -> None:
        self.cause = cause


@dataclass(frozen=True, slots=True)
class SchemaAsserts(Generic[RD_co, RE_co]):
    """Assertions for one schema; a schema needing services to decode
    (``RD``) or encode (``RE``) gets them from ``provide`` on each direction."""

    schema: Codec[object, object, RD_co, RE_co]

    def make(self, **options: Unpack[ParseOptions]) -> SchemaCheck[RD_co]:
        """Construction: the decoded side, with constructor defaults."""
        schema = self.schema.__codec__()

        def parse(input: object) -> Effect[object, SchemaError, RD_co]:
            return schema.make_effect(input, **options).map_error(SchemaError)

        return SchemaCheck(parse)

    def decoding(self, **options: Unpack[ParseOptions]) -> SchemaCheck[RD_co]:
        return SchemaCheck(decode_unknown_effect(self.schema, **options))

    def encoding(self, **options: Unpack[ParseOptions]) -> SchemaCheck[RE_co]:
        return SchemaCheck(encode_unknown_effect(self.schema, **options))

    def verify_round_trip(
        self: SchemaAsserts[Never, Never], *, runs: int = 100, seed: int | None = None
    ) -> None:
        """Each value ``to_strategy`` draws encodes, then decodes to a value
        the schema's equivalence calls equal (Effect's ``verifyRoundTrip``;
        needs Hypothesis). A failing value is shrunk and reported."""
        verify: Effect[None] = self.verify_round_trip_effect(runs=runs, seed=seed)
        run_sync(verify)

    def verify_round_trip_effect[R](
        self: SchemaAsserts[R, R], *, runs: int = 100, seed: int | None = None
    ) -> Effect[None, Never, R]:
        """``verify_round_trip`` as an effect with the running fiber's
        services (Effect's ``verifyRoundTripEffect``): a mismatch is an
        ``AssertionError`` defect; any other failure than a schema error
        ends the check and fails the effect with its cause. Hypothesis
        draws synchronously, so each value's round trip runs to its end in
        a nested synchronous run (no asyncio, no interruption midway)."""
        try:
            from hypothesis import HealthCheck, given, settings
            from hypothesis import seed as hypothesis_seed
        except ImportError as error:
            raise missing_extra("verify_round_trip", "hypothesis") from error

        schema = self.schema

        # The services are the running fiber's: whatever ``R`` it was given.
        def verify(ctx: Context[Any]) -> Effect[None]:
            encode = encode_unknown_effect(schema)
            decode = decode_unknown_effect(schema)
            equivalent = to_equivalence(schema)

            @settings(
                max_examples=runs,
                database=None,
                deadline=None,
                suppress_health_check=[HealthCheck.too_slow],
            )
            @given(to_strategy(schema))
            def check(value: object) -> None:
                round_trip = _schema_result(encode(value).flat_map(decode))
                ex = run_sync_exit(round_trip, context=ctx)
                if not isinstance(ex, Success):
                    raise _Abort(ex.cause)
                match ex.value:
                    case Ok(back) if equivalent(back, value):
                        return
                    case result:
                        raise AssertionError(f"{value!r} did not round-trip: {result!r}")

            try:
                (check if seed is None else hypothesis_seed(seed)(check))()
            except _Abort as abort:
                return fail_cause(abort.cause)
            return void

        return context().flat_map(lambda ctx: suspend(lambda: verify(ctx)))

    def verify_generation(self, count: int = 30) -> None:
        """``to_strategy`` draws ``count`` values, each one of the schema's
        (Effect's ``arbitrary().verifyGeneration()``; needs Hypothesis)."""
        try:
            from hypothesis import HealthCheck, given, settings
        except ImportError as error:
            raise missing_extra("verify_generation", "hypothesis") from error

        is_value = is_(self.schema)

        @settings(
            max_examples=count,
            database=None,
            deadline=None,
            suppress_health_check=[HealthCheck.too_slow],
        )
        @given(to_strategy(self.schema))
        def check(value: object) -> None:
            assert is_value(value), f"generated a value the schema refuses: {value!r}"

        check()
