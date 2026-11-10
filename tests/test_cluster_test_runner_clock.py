"""``test_runner.layer`` under the test clock behaves as Effect 4.1.2's ``TestRunner.layer``
under ``it.effect`` (checked in Node): the runner takes its shards in background fibers, so a
request sent before they ran is retried ``send_retry_interval`` later on the clock, so it
waits for the test to move time, while a request sent after them (one yield later, or from a
forked fiber) answers at once."""

from __future__ import annotations

from typing import Any

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.cluster import test_runner
from pyfect.cluster.entity import Entity
from pyfect.rpc import make as make_rpc

# A stalled test warns that it uses time without moving the clock, as in Effect.
_stalls = pytest.mark.filterwarnings("ignore::pyfect.testing.ClockNotAdvancedWarning")


class Ask(Entity, type="Ask"):
    ask = make_rpc("Ask", success=S.Int)


_layer = Ask.to_layer(Ask.handlers().handle(Ask.ask)(lambda _: fx.succeed(1))).pipe(
    fx.layer.provide_merge(test_runner.layer)
)


@fx.gen
def _ask_body():
    make_client = yield from Ask.client()
    return (yield from make_client("a").ask())


_ask = _ask_body.or_die()


@_stalls
def test_request_before_the_runner_took_its_shards_waits_for_the_clock() -> None:
    with pytest.raises(testing.StalledError):
        testing.run_test(_ask.pipe(fx.provide(_layer)))


def test_request_after_a_yield_answers_without_moving_the_clock() -> None:
    @fx.gen
    def program():
        yield from fx.yield_now()
        return (yield from _ask)

    assert testing.run_test(program.pipe(fx.provide(_layer))) == 1


def test_request_from_a_forked_fiber_answers_without_moving_the_clock() -> None:
    @fx.gen
    def program():
        fiber = yield from _ask.fork()
        return (yield from fiber.join())

    assert testing.run_test(program.pipe(fx.provide(_layer))) == 1


def _ask_after(moved: str) -> fx.Effect[int, Any, Any]:
    @fx.gen
    def program():
        fiber = yield from _ask.fork(start_immediately=True)
        yield from testing.adjust(moved)
        return (yield from fiber.join())

    return program.pipe(fx.provide(_layer))


@_stalls
def test_request_before_the_shards_is_retried_after_the_send_retry_interval() -> None:
    """``send_retry_interval`` (100 milliseconds) later, as in Effect."""
    assert testing.run_test(_ask_after("100 millis")) == 1
    with pytest.raises(testing.StalledError):
        testing.run_test(_ask_after("99 millis"))
