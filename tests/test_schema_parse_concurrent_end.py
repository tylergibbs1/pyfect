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
from pyfect.schema.issue import Composite, InvalidValue, format_issue


def _decoding(getter: G.Getter[str, str]) -> S.Bottom[str, str]:
    return S.String.pipe(S.decode(T.Transformation(getter, G.passthrough())))


def _messages(cause: Cause[S.SchemaError]) -> list[str]:
    return [r.error.message for r in cause.reasons if isinstance(r, Fail)]


def _echo(value: str, _: object) -> fx.Effect[str]:
    return fx.sync(lambda: value)


@testing.effect
def test_a_child_that_dies_after_the_parse_ended_adds_its_defect():
    boom = RuntimeError("boom")
    released = yield from Deferred[None].make()

    def mismatch(value: str, _: object) -> fx.Effect[str, InvalidValue]:
        return released.wait().and_then(fx.fail(InvalidValue({"message": "bad"})))

    def release_then_die(value: str, _: object) -> fx.Effect[str]:
        # Uninterruptible: it dies even though the mismatch it wakes ends the parse.
        return released.succeed(None).and_then(fx.die(boom)).uninterruptible()

    schema = S.Tuple(
        _decoding(G.transform_effect(mismatch)), _decoding(G.transform_effect(release_then_die))
    )
    exit = yield from S.decode_unknown_effect(schema)(("a", "b"), concurrency=2).exit()

    assert isinstance(exit, Failure)
    reasons = exit.cause.reasons
    assert all(isinstance(r, Die) for r in reasons)
    defects = [r.defect for r in reasons if isinstance(r, Die)]
    assert defects[1:] == [boom]
    issue = defects[0]
    assert isinstance(issue, Composite)
    assert format_issue(issue) == "bad\n  at [0]"


@testing.effect
def test_a_child_that_mismatches_after_the_parse_ended_adds_its_issue():
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
    # As in Effect, the late child's own failure, not placed at its index.
    assert _messages(exit.cause) == ["first\n  at [0]", "second"]


def test_synchronous_children_after_the_last_effectful_one_are_parsed_once():
    schema = S.Tuple(_decoding(G.transform_effect(_echo)), S.String, S.String)
    for concurrency in (2, "unbounded"):
        exit = S.decode_unknown_exit(schema)(("a", 1, 2), concurrency=concurrency, errors="all")
        assert isinstance(exit, Failure)
        assert _messages(exit.cause) == ["Expected string\n  at [1]\nExpected string\n  at [2]"]
