"""A producer that never waits gives a waiting consumer the turns Effect gives it.

A forked producer offers 20,000 items one at a time to a queue that never
makes it wait (sliding, dropping, unbounded); a forked consumer takes them.
The consumer runs only when the producer pauses for its step budget
(``MaxOpsBeforeYield``, 2048), so what it receives shows where the producer
pauses. Effect 4.1.2 under Node (``Queue.offer`` in a ``for`` loop of
``Effect.gen``, ``Queue.take`` in another) receives exactly these items: the
producer pauses after 1023 offers (two steps each, a pause before the step
that reaches 2048), and after each pause 1023 again (the resumed run starts
with the pause's own continuation). pyfect used to pause after 683 (an offer
took three steps), and a bounded queue of 1024 then ping-ponged between the
two fibers on every item.
"""

from typing import Any

import pytest

import pyfect as fx
from pyfect.queue import Queue

N = 20_000
SLICE = 1023


def _received(make: fx.Effect[Queue[int]]) -> list[int]:
    @fx.gen
    def body():
        queue = yield from make
        got: list[int] = []

        @fx.gen
        def consume():
            while True:
                n = yield from queue.take()
                got.append(n)
                if n == N - 1:
                    return

        @fx.gen
        def produce():
            for i in range(N):
                yield from queue.offer(i)

        consumer = yield from consume.fork()
        yield from produce.fork()
        yield from consumer.join().race_first(fx.sleep("2 seconds"))
        return got

    return fx.run_blocking(body)


def _blocks(starts: Any, size: int) -> list[int]:
    return [n for start in starts for n in range(start, start + size)]


def test_a_dropping_queue_keeps_the_first_items_of_each_slice_as_in_effect():
    expected = _blocks(range(0, N, SLICE), 16)
    expected = [n for n in expected if n < N]
    assert _received(Queue[int].dropping(16)) == expected


def test_a_sliding_queue_keeps_the_last_items_of_each_slice_as_in_effect():
    expected = _blocks(range(SLICE - 16, N - 16, SLICE), 16)
    assert _received(Queue[int].sliding(16)) == [*expected, *range(N - 16, N)]


@pytest.mark.parametrize(
    "make",
    [Queue[int].sliding(1024), Queue[int].dropping(1024), Queue[int].unbounded()],
    ids=["sliding(1024)", "dropping(1024)", "unbounded"],
)
def test_a_consumer_keeps_up_with_a_producer_that_never_waits(make: fx.Effect[Queue[int]]):
    """A buffer of 1024 holds a whole slice, so nothing is lost (as in Effect)."""
    assert _received(make) == list(range(N))
