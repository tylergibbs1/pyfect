"""``SynchronizedRef`` and ``SubscriptionRef`` behavior beyond Effect's
tests: updates take turns, a failed or interrupted update stores nothing,
and a ``SubscriptionRef`` publishes exactly the values it stores."""

from collections.abc import Callable
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.option import Option


def _slow_increment(n: int) -> fx.Effect[int]:
    return fx.yield_now().as_(n + 1)


@testing.effect
def test_concurrent_effectful_updates_take_turns():
    ref = yield from fx.SynchronizedRef.make(0)
    yield from fx.for_each(range(50), lambda _: ref.update_effect(_slow_increment), concurrency=50)
    assert (yield from ref.get()) == 50


@testing.effect
def test_get_reads_the_stored_value_while_an_update_runs():
    ref = yield from fx.SynchronizedRef.make(0)
    gate = yield from fx.Deferred[None].make()
    fiber = yield from ref.update_effect(lambda n: gate.wait().as_(n + 1)).fork(
        start_immediately=True
    )
    assert (yield from ref.get()) == 0
    yield from gate.succeed(None)
    yield from fiber.join()
    assert (yield from ref.get()) == 1


@testing.effect
def test_an_interrupted_update_stores_nothing_and_releases_the_lock():
    ref = yield from fx.SynchronizedRef.make(0)
    fiber = yield from ref.update_effect(lambda n: fx.never.as_(n + 1)).fork(start_immediately=True)
    yield from fiber.interrupt()
    assert (yield from ref.update_and_get(lambda n: n + 10)) == 10


@testing.effect
def test_an_update_waits_for_the_running_effectful_update():
    ref = yield from fx.SynchronizedRef.make("a")
    gate = yield from fx.Deferred[None].make()
    slow = yield from ref.update_effect(lambda s: gate.wait().as_(s + "b")).fork(
        start_immediately=True
    )
    fast = yield from ref.update(lambda s: s + "c").fork(start_immediately=True)
    assert fast.poll_unsafe() is None
    yield from gate.succeed(None)
    yield from slow.join()
    yield from fast.join()
    assert (yield from ref.get()) == "abc"


def _take(ref: fx.SubscriptionRef[int], n: int) -> fx.Effect[list[int]]:
    @fx.gen
    def body():
        subscription = yield from ref.subscribe()
        values: list[int] = []
        while len(values) < n:
            values.append((yield from subscription.take()))
        return values

    return fx.scoped(body)


def _keep_even(n: int) -> Option[int]:
    return fx.Some(n + 1) if n % 2 == 0 else None


@testing.effect
def test_a_subscription_starts_at_the_current_value_and_sees_each_stored_value():
    ref = yield from fx.SubscriptionRef.make(0)
    yield from ref.set(1)
    reader = yield from _take(ref, 6).fork(start_immediately=True)
    yield from ref.update(lambda n: n + 1)
    yield from ref.set(2)
    yield from ref.modify(lambda n: ("ignored", n + 1))
    yield from ref.update_effect(_slow_increment)
    yield from ref.set_and_get(5)
    assert (yield from reader.join()) == [1, 2, 2, 3, 4, 5]


@testing.effect
def test_an_update_that_keeps_the_value_publishes_nothing():
    ref = yield from fx.SubscriptionRef.make(1)
    reader = yield from _take(ref, 2).fork(start_immediately=True)
    yield from ref.update_some(_keep_even)
    yield from ref.modify_some(lambda n: ("kept", None))
    yield from ref.update_some_effect(lambda n: fx.succeed(_keep_even(n)))
    yield from ref.set(7)
    assert (yield from reader.join()) == [1, 7]


@testing.effect
def test_a_failed_effectful_update_publishes_nothing():
    ref = yield from fx.SubscriptionRef.make(1)
    reader = yield from _take(ref, 2).fork(start_immediately=True)
    failed = yield from ref.update_effect(lambda _: fx.fail("boom")).exit()
    assert isinstance(failed, fx.Failure)
    yield from ref.set(2)
    assert (yield from reader.join()) == [1, 2]


@testing.effect
def test_concurrent_subscribers_see_consecutive_values():
    ref = yield from fx.SubscriptionRef.make(0)
    producer = yield from ref.update(lambda n: n + 1).forever().fork_scoped()
    results = yield from fx.for_each([5, 50, 120], lambda n: _take(ref, n), concurrency="unbounded")
    yield from producer.interrupt()
    for values in results:
        assert values == list(range(values[0], values[0] + len(values)))


# Every SynchronizedRef / SubscriptionRef operation, plain or effectful,
# must return and store what the matching ``Ref`` operation does.

type _Locked = fx.SynchronizedRef[int] | fx.SubscriptionRef[int]
type _Plain = Callable[[fx.Ref[int] | _Locked], fx.Effect[object]]
type _Effectful = Callable[[_Locked], fx.Effect[object]]


def _inc(n: int) -> int:
    return n + 1


def _lift[A, B](f: Callable[[A], B]) -> Callable[[A], fx.Effect[B]]:
    return lambda a: fx.succeed(f(a))


def _some_cases(
    name: str, pf: Callable[[int], Option[int]]
) -> list[tuple[str, _Plain, _Effectful]]:
    def with_result(n: int) -> tuple[str, Option[int]]:
        return "result", pf(n)

    return [
        (
            f"update_some/{name}",
            lambda r: r.update_some(pf),
            lambda r: r.update_some_effect(_lift(pf)),
        ),
        (
            f"update_some_and_get/{name}",
            lambda r: r.update_some_and_get(pf),
            lambda r: r.update_some_and_get_effect(_lift(pf)),
        ),
        (
            f"get_and_update_some/{name}",
            lambda r: r.get_and_update_some(pf),
            lambda r: r.get_and_update_some_effect(_lift(pf)),
        ),
        (
            f"modify_some/{name}",
            lambda r: r.modify_some(with_result),
            lambda r: r.modify_some_effect(_lift(with_result)),
        ),
    ]


def _modified(n: int) -> tuple[str, int]:
    return "result", n + 1


_OPS: list[tuple[str, _Plain, _Effectful]] = [
    ("set", lambda r: r.set(5), lambda r: r.set(5)),
    ("set_and_get", lambda r: r.set_and_get(5), lambda r: r.set_and_get(5)),
    ("get_and_set", lambda r: r.get_and_set(5), lambda r: r.get_and_set(5)),
    ("update", lambda r: r.update(_inc), lambda r: r.update_effect(_lift(_inc))),
    (
        "update_and_get",
        lambda r: r.update_and_get(_inc),
        lambda r: r.update_and_get_effect(_lift(_inc)),
    ),
    (
        "get_and_update",
        lambda r: r.get_and_update(_inc),
        lambda r: r.get_and_update_effect(_lift(_inc)),
    ),
    ("modify", lambda r: r.modify(_modified), lambda r: r.modify_effect(_lift(_modified))),
    *_some_cases("some", lambda n: fx.Some(n + 10)),
    *_some_cases("none", lambda _: None),
]


@pytest.mark.parametrize("make", [fx.SynchronizedRef[int], fx.SubscriptionRef[int]])
@pytest.mark.parametrize(("name", "plain", "effectful"), _OPS, ids=[op[0] for op in _OPS])
def test_operations_match_ref(
    make: Callable[[int], _Locked], name: str, plain: _Plain, effectful: _Effectful
):
    def outcome(ref: fx.Ref[int] | _Locked, op: Callable[[Any], fx.Effect[object]]):
        return fx.run_sync(op(ref)), ref.get_unsafe()

    expected = outcome(fx.Ref(1), plain)
    assert outcome(make(1), plain) == expected, name
    assert outcome(make(1), effectful) == expected, name
