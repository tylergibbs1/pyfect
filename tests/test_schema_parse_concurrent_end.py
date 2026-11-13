"""How a concurrent parse ends (Effect's ``iterateConcurrent``): the first
child that ends the parse decides it, children still running are
interrupted, and a child that fails after that adds its own cause (its
interruption aside), its typed errors elected to defects beside a defect."""

from __future__ import annotations

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.cause import Cause, Die, Fail
from pyfect.deferred import Deferred
from pyfect.exit import Failure
from pyfect.schema import getter as G
from pyfect.schema import transformation as T
from pyfect.schema.issue import InvalidValue


def _decoding(getter: G.Getter[str, str]) -> S.Bottom[str, str]:
    return S.String.pipe(S.decode(T.Transformation(getter, G.passthrough())))


def _messages(cause: Cause[S.SchemaError]) -> list[str]:
    return [r.error.message for r in cause.reasons if isinstance(r, Fail)]


def _echo(value: str, _: object) -> fx.Effect[str]:
    return fx.sync(lambda: value)


# Each child starts at once (Effect's ``forkUnsafe`` with ``startImmediately``).
# The second wakes the first, which runs at once, nested in the second's run, and
# ends the parse; the second's own failure, still in that run, is not added. The
# outcomes were recorded from Effect 4.1.2 under Node with the same schemas.


@testing.effect
def test_a_child_that_wakes_the_deciding_one_and_dies_adds_nothing():
    released = yield from Deferred[None].make()

    def mismatch(value: str, _: object) -> fx.Effect[str, InvalidValue]:
        return released.wait().and_then(fx.fail(InvalidValue({"message": "bad"})))

    def release_then_die(value: str, _: object) -> fx.Effect[str]:
        return released.succeed(None).and_then(fx.die(RuntimeError("boom"))).uninterruptible()

    schema = S.Tuple(
        _decoding(G.transform_effect(mismatch)), _decoding(G.transform_effect(release_then_die))
    )
    exit = yield from S.decode_unknown_effect(schema)(("a", "b"), concurrency=2).exit()

    assert isinstance(exit, Failure)
    assert _messages(exit.cause) == ["bad\n  at [0]"]
    assert not any(isinstance(r, Die) for r in exit.cause.reasons)


@testing.effect
def test_a_child_that_wakes_the_deciding_one_and_mismatches_adds_nothing():
    released = yield from Deferred[None].make()

    def first(value: str, _: object) -> fx.Effect[str, InvalidValue]:
        return released.wait().and_then(fx.fail(InvalidValue({"message": "first"})))

    def second(value: str, _: object) -> fx.Effect[str, InvalidValue]:
        return (
            released.succeed(None)
            .and_then(fx.fail(InvalidValue({"message": "second"})))
            .uninterruptible()
        )

    schema = S.Tuple(_decoding(G.transform_effect(first)), _decoding(G.transform_effect(second)))
    exit = yield from S.decode_unknown_effect(schema)(("a", "b"), concurrency=2).exit()

    assert isinstance(exit, Failure)
    assert _messages(exit.cause) == ["first\n  at [0]"]


def test_synchronous_children_after_the_last_effectful_one_are_parsed_once():
    schema = S.Tuple(_decoding(G.transform_effect(_echo)), S.String, S.String)
    for concurrency in (2, "unbounded"):
        exit = S.decode_unknown_exit(schema)(("a", 1, 2), concurrency=concurrency, errors="all")
        assert isinstance(exit, Failure)
        assert _messages(exit.cause) == ["Expected string\n  at [1]\nExpected string\n  at [2]"]
