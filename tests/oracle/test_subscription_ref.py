"""Ports of Effect's ``SubscriptionRef.test.ts``.

Each test's docstring is the Effect test title. Effect's module functions
are methods (``SubscriptionRef.getAndUpdateEffect(ref, f)`` is
``ref.get_and_update_effect(f)``).

Adapted, with the reason:

- "multiple subscribers can receive changes", "subscriptions are
  interruptible", "concurrent subscribes and unsubscribes are handled
  correctly": Effect reads ``SubscriptionRef.changes``, a ``Stream``, and
  Stream is M6. The ports read the subscription ``changes`` is built on:
  ``ref.subscribe()`` and ``n`` takes stand for ``Stream.take(n)`` and
  ``Stream.runCollect``, and a latch opened after each take for
  ``Stream.tap``.

Omitted, with the reason:

- "isSubscriptionRef": ``isinstance(x, SubscriptionRef)`` is the guard.
"""

from typing import Any

import pyfect as fx
from pyfect import testing


def _collect(ref: fx.SubscriptionRef[int], n: int, latch: fx.Latch | None = None):
    """``changes(ref).pipe(Stream.tap(latch.open), Stream.take(n), Stream.runCollect)``."""

    @fx.gen
    def body():
        subscription = yield from ref.subscribe()
        values: list[int] = []
        for _ in range(n):
            values.append((yield from subscription.take()))
            if latch is not None:
                yield from latch.open()
        return values

    return fx.scoped(body)


def _interrupted_only(ex: fx.Exit[Any, Any]) -> bool:
    return isinstance(ex, fx.Failure) and ex.cause.has_interrupts_only


@testing.effect
def test_get_and_update_effect():
    """getAndUpdateEffect"""
    ref = yield from fx.SubscriptionRef.make(1)
    assert (yield from ref.get_and_update_effect(lambda value: fx.succeed(value + 1))) == 1
    assert (yield from ref.get()) == 2


@testing.effect
def test_get_and_update_some_returns_the_current_value_when_no_update_is_selected():
    """getAndUpdateSome returns the current value when no update is selected"""
    ref = yield from fx.SubscriptionRef.make(1)
    assert (yield from ref.get_and_update_some(lambda _: None)) == 1
    assert (yield from ref.get()) == 1


@testing.effect
def test_multiple_subscribers_can_receive_changes():
    """multiple subscribers can receive changes"""
    ref = yield from fx.SubscriptionRef.make(0)
    latch1 = yield from fx.Latch.make()
    latch2 = yield from fx.Latch.make()
    fiber1 = yield from _collect(ref, 3, latch1).fork_scoped()
    yield from latch1.wait()
    yield from ref.update(lambda n: n + 1)
    fiber2 = yield from _collect(ref, 2, latch2).fork_scoped()
    yield from latch2.wait()
    yield from ref.update(lambda n: n + 1)
    assert (yield from fiber1.join()) == [0, 1, 2]
    assert (yield from fiber2.join()) == [1, 2]


@testing.effect
def test_subscriptions_are_interruptible():
    """subscriptions are interruptible"""
    ref = yield from fx.SubscriptionRef.make(0)
    latch1 = yield from fx.Latch.make()
    latch2 = yield from fx.Latch.make()
    fiber1 = yield from _collect(ref, 5, latch1).fork_scoped()
    yield from latch1.wait()
    yield from ref.update(lambda n: n + 1)
    fiber2 = yield from _collect(ref, 2, latch2).fork_scoped()
    yield from latch2.wait()
    yield from ref.update(lambda n: n + 1)
    yield from fiber1.interrupt()
    assert _interrupted_only((yield from fiber1.await_exit()))
    assert (yield from fiber2.join()) == [1, 2]


@testing.effect
def test_concurrent_subscribes_and_unsubscribes_are_handled_correctly():
    """concurrent subscribes and unsubscribes are handled correctly"""

    @fx.gen
    def consumer():
        n = yield from fx.random.next_int_between(0, 200)
        return (yield from _collect(ref, n))

    ref = yield from fx.SubscriptionRef.make(0)
    producer = yield from ref.update(lambda n: n + 1).forever().fork_scoped()
    result1, result2 = yield from fx.all(consumer, consumer, concurrency=2)
    yield from producer.interrupt()
    assert result1 == sorted(result1)
    assert result2 == sorted(result2)
