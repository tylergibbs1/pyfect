"""The ``concurrency`` parse option with effectful children: what Effect's
``SchemaParser.test.ts`` does not pin (interruption from outside, re-runs,
the asyncio runtime, an invalid limit)."""

from __future__ import annotations

import asyncio

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.cause import Die
from pyfect.deferred import Deferred
from pyfect.exit import Failure
from pyfect.ref import Ref
from pyfect.schema import getter as G
from pyfect.schema import transformation as T


def _decoding(getter: G.Getter[str, str]) -> S.Bottom[str, str]:
    return S.String.pipe(S.decode(T.Transformation(getter, G.passthrough())))


@testing.effect
def test_interrupting_a_concurrent_parse_interrupts_its_running_children():
    started = yield from Ref.make(0)
    both_started = yield from Deferred[None].make()
    interrupted = yield from Ref.make(0)

    def run(value: str, _: object) -> fx.Effect[str]:
        return (
            started.update_and_get(lambda n: n + 1)
            .tap(lambda n: both_started.succeed(None) if n == 2 else fx.void)
            .and_then(fx.never)
            .on_interrupt(interrupted.update(lambda n: n + 1))
        )

    schema = S.Array(_decoding(G.transform_effect(run)))
    fiber = yield from S.decode_unknown_effect(schema)(("a", "b", "c"), concurrency=2).fork()
    yield from both_started.wait()
    yield from fiber.interrupt()
    assert (yield from interrupted.get()) == 2
    assert (yield from started.get()) == 2


@testing.effect
def test_a_concurrent_parse_run_again_starts_from_a_fresh_state():
    counter = yield from Ref.make(0)

    def run(value: str, _: object) -> fx.Effect[str]:
        return counter.update_and_get(lambda n: n + 1).map(lambda n: f"{value}{n}")

    schema = S.Tuple(
        S.String, _decoding(G.transform_effect(run)), _decoding(G.transform_effect(run))
    )
    program = S.decode_unknown_effect(schema)(("x", "a", "b"), concurrency="unbounded")
    assert (yield from program) == ("x", "a1", "b2")
    assert (yield from program) == ("x", "a3", "b4")


@testing.effect
def test_a_defect_in_a_concurrent_child_is_reported_at_its_position():
    boom = RuntimeError("boom")

    def run(value: str, _: object) -> fx.Effect[str]:
        return fx.die(boom) if value == "b" else fx.yield_now().as_(value)

    schema = S.Array(_decoding(G.transform_effect(run)))
    exit = yield from S.decode_unknown_effect(schema)(("a", "b", "c"), concurrency=2).exit()
    assert isinstance(exit, Failure)
    assert [r.defect for r in exit.cause.reasons if isinstance(r, Die)] == [boom]
    assert len(exit.cause.reasons) == 1


def test_concurrent_children_run_on_the_asyncio_runtime():
    async def main() -> tuple[str, ...]:
        def upper(value: str, _: object) -> fx.Effect[str]:
            return fx.sleep(0.01).as_(value.upper())

        async_getter: G.Getter[str, str] = G.transform_effect(upper)
        schema = S.Array(_decoding(async_getter))
        return await fx.run_async(
            S.decode_unknown_effect(schema)(("a", "b", "c"), concurrency="unbounded").or_die()
        )

    assert asyncio.run(main()) == ("A", "B", "C")


def test_a_concurrency_below_one_is_rejected_when_parsing():
    with pytest.raises(ValueError, match="concurrency must be at least 1, got 0"):
        S.decode_unknown_exit(S.String)("a", concurrency=0)


@testing.effect
def test_concurrent_elements_keep_their_positions_whatever_order_they_finish_in():
    second_done = yield from Deferred[None].make()

    def run(value: str, _: object) -> fx.Effect[str]:
        if value == "a":
            return second_done.wait().as_(value)
        return second_done.succeed(None).as_(value)

    schema = S.Array(_decoding(G.transform_effect(run)))
    assert (yield from S.decode_unknown_effect(schema)(("a", "b"), concurrency=2)) == ("a", "b")
