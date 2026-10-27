"""Ports of Effect's ``PubSub.test.ts``.

Each test's docstring is the Effect test title. Effect's module functions
are methods (``PubSub.take(sub)`` is ``sub.take()``); ``makeAtomicBounded``
/ ``makeAtomicUnbounded`` are ``Atomic.bounded`` / ``Atomic.unbounded``, and
a capacity of ``Infinity`` is ``None``. Effect's step budget counts differ
from pyfect's, so the ports that place a yield with ``MaxOpsBeforeYield``
sweep every budget instead of using Effect's number. Effect's ``retains``
walks object properties; the port walks ``gc.get_referents``.

Adapted, with the reason:

- "makeAtomicBounded rejects invalid capacity %s": counts are ``int``, so
  the invalid capacities are 0 and -1 (``ValueError``), not NaN or
  fractions; the options form is a keyword.
- "normalizes low-level polling and replay counts": no fraction or NaN to
  normalize; counts of 1, 0 and -1 are checked.
- "polls MutableList.Empty as a value": ``poll`` returns an ``Option``;
  the port publishes ``None``, the value Python could mistake for "empty".
- "does not retain values through a dropped replay node": the replay
  buffer is a deque, not linked nodes; the port checks that the store keeps
  nothing that fell out of the replay window.

Omitted, with the reason:

- "isPubSub type guard": ``isinstance(x, PubSub)`` is the guard.
- "unbounded rounds up fractional replay", "takeUpTo and takeBetween
  normalize message counts": counts are ``int``, so there is no fraction or
  NaN to normalize (pyright rejects them); ``tests/test_pubsub.py`` checks
  counts of 0 and less.
- "Stream.fromPubSub completes after shutdown": Stream is not ported yet
  (M6).
"""

import gc
from collections.abc import Callable
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.pubsub import Atomic, PubSub, ReplayWindow, Subscription


def _interrupted(ex: fx.Exit[Any, Any] | None) -> bool:
    return isinstance(ex, fx.Failure) and ex.cause.has_interrupts


def _budget[A](eff: fx.Effect[A], ops: int) -> fx.Effect[A]:
    return eff.pipe(fx.provide_service(fx.MaxOpsBeforeYield, ops))


def _taking(pubsub: PubSub[int], n: int) -> fx.Effect[fx.Fiber[list[int]]]:
    """A subscriber, started now, that takes ``n`` messages."""
    return fx.scoped(
        pubsub.subscribe().flat_map(lambda sub: fx.for_each(range(n), lambda _: sub.take()))
    ).fork(start_immediately=True)


def _retains(root: object, target: object) -> bool:
    """Whether ``target`` is reachable from ``root``."""
    pending = [root]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if current is target:
            return True
        if id(current) in seen or isinstance(current, type):
            continue
        seen.add(id(current))
        pending.extend(gc.get_referents(current))
    return False


class _Box:
    """A distinct object, as Effect's tests use ``{}``."""


VALUES_0_TO_64 = list(range(65))
VALUES_1_TO_64 = list(range(1, 65))


@testing.effect
def test_take_between_returns_a_large_backlog():
    """takeBetween returns a large backlog"""
    values = list(range(200_000))
    pubsub = yield from PubSub[int].unbounded()
    subscription = yield from pubsub.subscribe()
    yield from pubsub.publish_all(values)
    assert (yield from subscription.take_between(1, len(values))) == values


@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize("capacity", [1, 2, 3])
@testing.effect
def test_sliding_capacity_delivers_each_retained_message_once_per_subscriber(
    capacity: int, batch: bool
):
    """sliding capacity %s delivers each retained message once per subscriber (batch: ${batch})"""
    pubsub = yield from PubSub[int].sliding(capacity)
    first = yield from pubsub.subscribe()
    second = yield from pubsub.subscribe()
    values = list(range(1, capacity + 3))
    retained = values[-capacity:]
    yield from pubsub.publish_all(values)

    if batch:
        received = yield from first.take_all()
    else:
        received = yield from fx.for_each(retained, lambda _: first.take())
    duplicate = yield from first.take_up_to(capacity)
    other = yield from second.take_up_to(capacity)

    assert [received, duplicate, other] == [retained, [], retained]


@pytest.mark.parametrize("capacity", [1, 2, 3])
@testing.effect
def test_unsubscribing_after_a_slide_preserves_the_other_subscribers_messages(capacity: int):
    """unsubscribing after a slide preserves the other subscriber's messages (capacity: %s)"""
    pubsub = yield from PubSub[int].sliding(capacity)
    scope = fx.CloseableScope()
    first = yield from pubsub.subscribe().pipe(fx.provide_service(fx.Scope, scope))
    second = yield from pubsub.subscribe()
    values = list(range(1, capacity + 3))
    retained = values[-capacity:]
    yield from pubsub.publish_all(values)
    yield from first.take_all()
    yield from scope.close(fx.Success(None))

    assert (yield from second.take_up_to(capacity)) == retained


@pytest.mark.parametrize(
    "capacity",
    [
        pytest.param(2, id="publishAll - capacity 2 (BoundedPubSubPow2)"),
        pytest.param(4, id="publishAll - capacity 4 (BoundedPubSubPow2)"),
        pytest.param(3, id="publishAll - capacity 3 (BoundedPubSubArb)"),
    ],
)
@testing.effect
def test_publish_all(capacity: int):
    """publishAll - capacity 2 (BoundedPubSubPow2); publishAll - capacity 4
    (BoundedPubSubPow2); publishAll - capacity 3 (BoundedPubSubArb)"""
    messages = [1, 2]
    pubsub = yield from PubSub[int].bounded(capacity)
    sub1 = yield from pubsub.subscribe()
    sub2 = yield from pubsub.subscribe()
    yield from pubsub.publish_all(messages)
    assert (yield from sub1.take_all()) == messages
    assert (yield from sub2.take_all()) == messages


@testing.effect
def test_sequential_publishers_and_subscribers_with_one_publisher_and_one_subscriber():
    """sequential publishers and subscribers with one publisher and one subscriber"""
    values = list(range(10))
    latch = yield from fx.Latch.make()
    pubsub = yield from PubSub[int].bounded(10)
    subscriber = yield from fx.scoped(
        pubsub.subscribe().flat_map(
            lambda sub: latch.wait().and_then(fx.for_each(values, lambda _: sub.take()))
        )
    ).fork(start_immediately=True)
    yield from pubsub.publish_all(values)
    yield from latch.open()
    assert (yield from subscriber.join()) == values


@testing.effect
def test_sequential_publishers_and_subscribers_with_one_publisher_and_two_subscribers():
    """sequential publishers and subscribers with one publisher and two subscribers"""
    values = list(range(10))
    latch = yield from fx.Latch.make()
    pubsub = yield from PubSub[int].bounded(10)

    def subscriber() -> fx.Effect[fx.Fiber[list[int]]]:
        return fx.scoped(
            pubsub.subscribe().flat_map(
                lambda sub: latch.wait().and_then(fx.for_each(values, lambda _: sub.take()))
            )
        ).fork(start_immediately=True)

    subscriber1 = yield from subscriber()
    subscriber2 = yield from subscriber()
    yield from pubsub.publish_all(values)
    yield from latch.open()
    assert (yield from subscriber1.join()) == values
    assert (yield from subscriber2.join()) == values


type _Make = Callable[[int], fx.Effect[PubSub[int]]]


def _bounded(capacity: int) -> fx.Effect[PubSub[int]]:
    return PubSub[int].bounded(capacity)


def _dropping(capacity: int) -> fx.Effect[PubSub[int]]:
    return PubSub[int].dropping(capacity)


def _sliding(capacity: int) -> fx.Effect[PubSub[int]]:
    return PubSub[int].sliding(capacity)


def _unbounded(_: int) -> fx.Effect[PubSub[int]]:
    return PubSub[int].unbounded()


def _publish_all(pubsub: PubSub[int], values: list[int]) -> fx.Effect[object]:
    return pubsub.publish_all(values)


def _publish_each(pubsub: PubSub[int], values: list[int]) -> fx.Effect[object]:
    return fx.for_each(values, pubsub.publish)


type _Publish = Callable[[PubSub[int], list[int]], fx.Effect[object]]

_CONCURRENT = [
    pytest.param(_bounded, _publish_all, id="backpressured"),
    pytest.param(_dropping, _publish_each, id="dropping"),
    pytest.param(_sliding, _publish_each, id="sliding"),
    pytest.param(_unbounded, _publish_all, id="unbounded"),
]


@pytest.mark.parametrize(("make", "publish"), _CONCURRENT)
@testing.effect
def test_concurrent_publishers_and_subscribers_one_to_one(make: _Make, publish: _Publish):
    """backpressured concurrent publishers and subscribers - one to one; dropping
    concurrent publishers and subscribers - one to one; sliding concurrent publishers
    and subscribers - one to one; unbounded concurrent publishers and subscribers - one
    to one"""
    pubsub = yield from make(64)
    subscriber = yield from _taking(pubsub, len(VALUES_0_TO_64))
    yield from publish(pubsub, VALUES_0_TO_64).fork()
    assert (yield from subscriber.join()) == VALUES_0_TO_64


@pytest.mark.parametrize(
    ("make", "publish"),
    [
        pytest.param(_bounded, _publish_all, id="backpressured"),
        pytest.param(_dropping, _publish_each, id="dropping"),
        pytest.param(_sliding, _publish_all, id="sliding"),
        pytest.param(_unbounded, _publish_all, id="unbounded"),
    ],
)
@testing.effect
def test_concurrent_publishers_and_subscribers_one_to_many(make: _Make, publish: _Publish):
    """backpressured concurrent publishers and subscribers - one to many; dropping
    concurrent publishers and subscribers - one to many; sliding concurrent publishers
    and subscribers - one to many; unbounded concurrent publishers and subscribers - one
    to many"""
    pubsub = yield from make(64)
    subscriber1 = yield from _taking(pubsub, len(VALUES_0_TO_64))
    subscriber2 = yield from _taking(pubsub, len(VALUES_0_TO_64))
    yield from publish(pubsub, VALUES_0_TO_64).fork()
    assert (yield from subscriber1.join()) == VALUES_0_TO_64
    assert (yield from subscriber2.join()) == VALUES_0_TO_64


@pytest.mark.parametrize(
    ("make", "publish"),
    [
        pytest.param(_bounded, _publish_all, id="backpressured"),
        pytest.param(_dropping, _publish_each, id="dropping"),
        pytest.param(_sliding, _publish_all, id="sliding"),
        pytest.param(_unbounded, _publish_all, id="unbounded"),
    ],
)
@testing.effect
def test_concurrent_publishers_and_subscribers_many_to_many(make: _Make, publish: _Publish):
    """backpressured concurrent publishers and subscribers - many to many; dropping
    concurrent publishers and subscribers - many to many; sliding concurrent publishers
    and subscribers - many to many; unbounded concurrent publishers and subscribers -
    many to many"""
    values = VALUES_1_TO_64
    negated = [-n for n in values]
    pubsub = yield from make(64 * 2)
    subscriber1 = yield from _taking(pubsub, 2 * len(values))
    subscriber2 = yield from _taking(pubsub, 2 * len(values))
    fiber = yield from publish(pubsub, values).fork()
    yield from publish(pubsub, negated).fork()
    result1 = yield from subscriber1.join()
    result2 = yield from subscriber2.join()
    yield from fiber.join()
    for result in (result1, result2):
        assert [n for n in result if n > 0] == values
        assert [n for n in result if n < 0] == negated


@testing.effect
def test_infinite_capacity_behaves_as_unbounded():
    """infinite capacity behaves as unbounded"""
    values = VALUES_0_TO_64
    for make in (PubSub[int].bounded, PubSub[int].dropping, PubSub[int].sliding):
        pubsub = yield from make(None, replay=2)
        subscription = yield from pubsub.subscribe()
        yield from pubsub.publish_all(values)
        assert (yield from subscription.take_all()) == values
        late = yield from pubsub.subscribe()
        assert (yield from late.take_all()) == [63, 64]


@testing.effect
def test_null_values():
    """null values"""
    messages = [1, None]
    pubsub = yield from PubSub[int | None].unbounded()
    sub1 = yield from pubsub.subscribe()
    sub2 = yield from pubsub.subscribe()
    yield from pubsub.publish_all(messages)
    assert (yield from sub1.take_all()) == messages
    assert (yield from sub2.take_all()) == messages


@testing.effect
def test_publish_does_not_increase_size_while_no_subscribers():
    """publish does not increase size while no subscribers"""
    pubsub = yield from PubSub[int].dropping(2)
    yield from pubsub.publish(1)
    yield from pubsub.publish(2)
    assert pubsub.unsafe_size() == 0


@testing.effect
def test_publish_all_does_not_increase_size_while_no_subscribers():
    """publishAll does not increase size while no subscribers"""
    pubsub = yield from PubSub[int].dropping(2)
    yield from pubsub.publish_all([1, 2])
    assert pubsub.unsafe_size() == 0


@pytest.mark.parametrize("capacity", [0, -1])
def test_make_atomic_bounded_rejects_invalid_capacity(capacity: int):
    """makeAtomicBounded rejects invalid capacity %s (options: ${options})"""
    with pytest.raises(ValueError, match="capacity"):
        Atomic[int].bounded(capacity)


def test_normalizes_low_level_polling_and_replay_counts():
    """normalizes low-level polling and replay counts"""
    for atomic in (
        Atomic[int].bounded(1),
        Atomic[int].bounded(3),
        Atomic[int].bounded(4),
        Atomic[int].unbounded(),
    ):
        subscription = atomic.subscribe()
        atomic.publish_all([1, 2, 3])
        assert subscription.poll_up_to(1) == [1]
        assert subscription.poll_up_to(0) == []
        assert subscription.poll_up_to(-1) == []

    replay_atomic = Atomic[int].unbounded(replay=3)
    replay_atomic.publish_all([1, 2, 3])
    replay = replay_atomic.replay_window()
    assert replay.take_n(1) == [1]
    assert replay.take_n(0) == []
    assert replay.take_n(-1) == []
    assert replay.take_all() == [2, 3]


def test_polls_mutable_list_empty_as_a_value():
    """polls MutableList.Empty as a value"""
    atomic = Atomic[None].bounded(1)
    subscription = atomic.subscribe()
    atomic.publish(None)
    assert subscription.poll_up_to(1) == [None]


def test_publishes_after_a_capacity_one_subscriber_unsubscribes_from_a_slid_message():
    """publishes after a capacity-one subscriber unsubscribes from a slid message"""
    atomic = Atomic[int].bounded(1)
    subscription = atomic.subscribe()
    atomic.publish(1)
    atomic.slide()
    subscription.unsubscribe()

    following = atomic.subscribe()
    assert atomic.publish(2)
    assert atomic.size() == 1
    assert following.poll_up_to(1) == [2]


# --- replay -----------------------------------------------------------------------------


def _take(window: ReplayWindow[_Box]) -> _Box | None:
    taken = window.take()
    return None if taken is None else taken.value


def test_replay_does_not_retain_values_published_after_the_replay_window_is_drained():
    """does not retain values published after the replay window is drained"""
    atomic = Atomic[_Box].unbounded(replay=1)
    atomic.publish(_Box())
    replay_window = atomic.replay_window()
    replay_window.take()

    slid_out = _Box()
    atomic.publish(slid_out)
    atomic.publish(_Box())

    assert not _retains(replay_window, slid_out)


def test_replay_does_not_retain_values_published_outside_an_undrained_replay_window():
    """does not retain values published outside an undrained replay window"""
    atomic = Atomic[_Box].unbounded(replay=1)
    replayed = _Box()
    atomic.publish(replayed)
    replay_window = atomic.replay_window()

    slid_out = _Box()
    atomic.publish(slid_out)
    atomic.publish(_Box())

    assert not _retains(replay_window, slid_out)
    assert _take(replay_window) is replayed


def test_replay_does_not_retain_values_through_a_dropped_replay_node():
    """does not retain values through a dropped replay node"""
    atomic = Atomic[_Box].unbounded(replay=1)
    first = _Box()
    atomic.publish(first)
    second = _Box()
    atomic.publish(second)
    atomic.publish(_Box())

    assert not _retains(atomic, first)
    assert not _retains(atomic, second)


def test_replay_preserves_replay_order_across_multiple_slides():
    """preserves replay order across multiple slides"""
    atomic = Atomic[int].bounded(4, replay=3)
    atomic.publish_all([1, 2, 3, 4, 5])
    subscription = atomic.subscribe()
    replay_window = atomic.replay_window()
    atomic.publish_all([6, 7, 8, 9])
    for value in (10, 11, 12):
        atomic.slide()
        atomic.publish(value)

    assert replay_window.take_all() == [6, 7, 8]
    assert subscription.poll_all() == [9, 10, 11, 12]


@testing.effect
def test_replay_unbounded():
    """unbounded"""
    pubsub = yield from PubSub[int].unbounded(replay=3)
    yield from pubsub.publish_all([1, 2, 3, 4, 5])
    sub = yield from pubsub.subscribe()
    assert (yield from sub.take_all()) == [3, 4, 5]


@testing.effect
def test_replay_unbounded_disables_non_positive_replay():
    """unbounded disables non-positive replay"""
    pubsub = yield from PubSub[int].unbounded(replay=-1)
    yield from pubsub.publish_all([1, 2])
    sub = yield from pubsub.subscribe()
    assert (yield from sub.take_up_to(2)) == []


@testing.effect
def test_replay_unbounded_take_up_to():
    """unbounded takeUpTo"""
    pubsub = yield from PubSub[int].unbounded(replay=3)
    yield from pubsub.publish_all([1, 2, 3, 4, 5])

    sub1 = yield from pubsub.subscribe()
    yield from pubsub.publish(6)
    sub2 = yield from pubsub.subscribe()

    assert (yield from sub1.remaining()) == 4
    assert (yield from sub2.remaining()) == 3
    assert (yield from sub1.take_up_to(2)) == [3, 4]
    assert (yield from sub1.take_up_to(2)) == [5, 6]
    assert (yield from sub2.take_up_to(3)) == [4, 5, 6]


@testing.effect
def test_replay_take_up_to_keeps_its_limit_when_run_again_after_taking_replayed_messages():
    """takeUpTo keeps its limit when run again after taking replayed messages"""
    pubsub = yield from PubSub[int].unbounded(replay=2)
    yield from pubsub.publish_all([1, 2])
    sub = yield from pubsub.subscribe()
    take_three = sub.take_up_to(3)
    yield from pubsub.publish(3)
    assert (yield from take_three) == [1, 2, 3]
    yield from pubsub.publish_all([4, 5, 6])
    assert (yield from take_three) == [4, 5, 6]


@testing.effect
def test_replay_dropping():
    """dropping"""
    pubsub = yield from PubSub[int].dropping(2, replay=3)

    yield from pubsub.publish_all([1, 2, 3, 4, 5])
    sub = yield from pubsub.subscribe()
    assert (yield from sub.take_all()) == [3, 4, 5]
    yield from pubsub.publish_all([6, 7])
    assert (yield from sub.take_all()) == [6, 7]

    sub2 = yield from pubsub.subscribe()
    assert (yield from sub2.take_all()) == [5, 6, 7]

    yield from pubsub.publish_all([8, 9, 10, 11])
    assert (yield from sub.take_all()) == [8, 9]
    assert (yield from sub2.take_all()) == [8, 9]

    sub3 = yield from pubsub.subscribe()
    assert (yield from sub3.take_all()) == [7, 8, 9]


@testing.effect
def test_replay_sliding():
    """sliding"""
    pubsub = yield from PubSub[int].sliding(4, replay=3)

    yield from pubsub.publish_all([1, 2, 3, 4, 5])
    sub = yield from pubsub.subscribe()
    assert (yield from sub.take()) == 3
    yield from pubsub.publish_all([6, 7, 8, 9, 10])
    assert (yield from sub.take_all()) == [5, 6, 7, 8, 9, 10]

    sub2 = yield from pubsub.subscribe()
    assert (yield from sub2.take_all()) == [8, 9, 10]

    yield from pubsub.publish_all([11, 12, 13, 14, 15, 16])
    assert (yield from sub.take_all()) == [13, 14, 15, 16]
    assert (yield from sub2.take_all()) == [13, 14, 15, 16]

    sub3 = yield from pubsub.subscribe()
    assert (yield from sub3.take_all()) == [14, 15, 16]


@testing.effect
def test_replay_sliding_preserves_publish_order_with_a_lagging_subscriber():
    """sliding preserves publish order with a lagging subscriber"""
    pubsub = yield from PubSub[int].sliding(4, replay=3)
    yield from pubsub.subscribe()
    yield from pubsub.publish_all([1, 2])
    subscription = yield from pubsub.subscribe()
    yield from pubsub.publish_all([3, 4, 5])

    values = yield from subscription.take_all()
    assert values == sorted(values)


# --- shutdown and interruption ------------------------------------------------------


@testing.effect
def test_shutdown_interrupts_suspended_subscribers():
    """shutdown interrupts suspended subscribers"""
    pubsub = yield from PubSub[int].unbounded()
    subscription = yield from pubsub.subscribe()
    fiber = yield from subscription.take().fork(start_immediately=True)

    yield from pubsub.shutdown()

    assert _interrupted((yield from fiber.await_exit()))


@testing.effect
def test_publish_succeeds_after_interrupting_a_suspended_subscriber():
    """publish succeeds after interrupting a suspended subscriber"""
    pubsub = yield from PubSub[int].dropping(1)
    subscription = yield from pubsub.subscribe()
    fiber = yield from subscription.take().fork(start_immediately=True)

    yield from fiber.interrupt()

    assert (yield from pubsub.publish(42)) is True
    assert (yield from subscription.take()) == 42


_BUDGETS = range(1, 65)


@pytest.mark.parametrize("ops", _BUDGETS)
@testing.effect
def test_an_interrupted_take_never_swallows_the_next_message(ops: int):
    """an interrupted take never swallows the next message"""
    pubsub = yield from PubSub[int].bounded(4)
    subscription = yield from pubsub.subscribe()
    fiber = yield from _budget(subscription.take(), ops).fork(start_immediately=True)
    yield from fiber.interrupt()
    yield from pubsub.publish(1)
    assert len((yield from subscription.take_up_to(1))) == 1


@pytest.mark.parametrize("ops", _BUDGETS)
@testing.effect
def test_a_take_that_starts_waiting_after_unsubscribe_is_interrupted(ops: int):
    """a take that starts waiting after unsubscribe is interrupted"""
    pubsub = yield from PubSub[int].unbounded()
    scope = fx.CloseableScope()
    subscription = yield from pubsub.subscribe().pipe(fx.provide_service(fx.Scope, scope))
    fiber = yield from _budget(subscription.take(), ops).fork(start_immediately=True)
    yield from scope.close(fx.Success(None))
    for _ in range(100):
        if fiber.unsafe_poll() is not None:
            break
        yield from fx.yield_now()
    assert _interrupted(fiber.unsafe_poll())


@pytest.mark.parametrize("ops", _BUDGETS)
@testing.effect
def test_an_interrupted_backpressured_publisher_never_publishes_later(ops: int):
    """an interrupted backpressured publisher never publishes later"""
    pubsub = yield from PubSub[int].bounded(1)
    subscription = yield from pubsub.subscribe()
    yield from pubsub.publish(1)
    fiber = yield from _budget(pubsub.publish(2), ops).fork(start_immediately=True)
    yield from fiber.interrupt()
    yield from subscription.take_up_to(1)
    assert (yield from subscription.take_up_to(1)) == []


@testing.effect
def test_shutdown_interrupts_suspended_take_all_subscribers():
    """shutdown interrupts suspended takeAll subscribers"""
    pubsub = yield from PubSub[int].unbounded()
    subscription = yield from pubsub.subscribe()
    fiber = yield from subscription.take_all().fork(start_immediately=True)
    yield from pubsub.shutdown()
    assert _interrupted((yield from fiber.await_exit()))


@testing.effect
def test_publish_returns_false_after_shutdown():
    """publish returns false after shutdown"""
    pubsub = yield from PubSub[int].unbounded()
    yield from pubsub.shutdown()
    assert (yield from pubsub.publish(1)) is False


@testing.effect
def test_publish_all_returns_false_after_shutdown():
    """publishAll returns false after shutdown"""
    pubsub = yield from PubSub[int].unbounded()
    yield from pubsub.shutdown()
    assert (yield from pubsub.publish_all([1, 2, 3])) is False


# --- end ------------------------------------------------------------------------------


@pytest.mark.parametrize("ops", _BUDGETS)
@testing.effect
def test_end_take_delivers_data_published_during_waiter_registration_before_the_final_message(
    ops: int,
):
    """take delivers data published during waiter registration before the final message"""
    pubsub = yield from PubSub[int].unbounded()
    subscription = yield from pubsub.subscribe()
    fiber = yield from _budget(subscription.take(), ops).fork(start_immediately=True)
    pubsub.unsafe_publish(1)
    pubsub.unsafe_end(0)

    first = yield from fiber.join()
    last = yield from subscription.take()
    assert [first, last] == [1, 0]


@pytest.mark.parametrize("ops", _BUDGETS)
@testing.effect
def test_end_take_all_delivers_data_published_during_waiter_registration_before_the_final_message(
    ops: int,
):
    """takeAll delivers data published during waiter registration before the final message"""
    pubsub = yield from PubSub[int].unbounded()
    subscription = yield from pubsub.subscribe()
    fiber = yield from _budget(subscription.take_all(), ops).fork(start_immediately=True)
    pubsub.unsafe_publish(1)
    pubsub.unsafe_end(0)

    first = yield from fiber.join()
    last = yield from subscription.take_all()
    assert [first, last] == [[1], [0]]


@testing.effect
def test_end_delivers_buffered_messages_before_the_final_message_and_rejects_later_publishes():
    """delivers buffered messages before the final message and rejects later publishes"""
    pubsub = yield from PubSub[int].bounded(4)
    subscription = yield from pubsub.subscribe()
    yield from pubsub.publish_all([1, 2])

    assert (yield from pubsub.end(0)) is True
    assert (yield from pubsub.end(-1)) is False
    assert (yield from pubsub.publish(3)) is False
    assert (yield from pubsub.publish_all([3])) is False
    assert pubsub.unsafe_publish(3) is False

    assert (yield from subscription.take_all()) == [1, 2]
    assert (yield from subscription.take()) == 0
    assert (yield from subscription.take()) == 0
    assert (yield from subscription.take_all()) == [0]


@testing.effect
def test_end_wakes_a_suspended_take():
    """wakes a suspended take"""
    pubsub = yield from PubSub[int].unbounded()
    subscription = yield from pubsub.subscribe()
    fiber = yield from subscription.take().fork(start_immediately=True)

    yield from pubsub.end(0)

    assert (yield from fiber.join()) == 0


@testing.effect
def test_end_is_not_dropped_by_a_full_dropping_pubsub():
    """is not dropped by a full dropping PubSub"""
    pubsub = yield from PubSub[int].dropping(1)
    subscription = yield from pubsub.subscribe()
    yield from pubsub.publish(1)

    yield from pubsub.end(0)

    assert (yield from subscription.take()) == 1
    assert (yield from subscription.take()) == 0


@testing.effect
def test_end_late_subscribers_receive_the_replayed_messages_and_then_the_final_message():
    """late subscribers receive the replayed messages and then the final message"""
    pubsub = yield from PubSub[int].unbounded(replay=2)
    yield from pubsub.publish_all([1, 2, 3])
    yield from pubsub.end(0)

    subscription = yield from pubsub.subscribe()
    assert (yield from subscription.take_between(3, 3)) == [2, 3, 0]


@testing.effect
def test_end_rejects_a_suspended_backpressured_publish_instead_of_delivering_it_late():
    """rejects a suspended backpressured publish instead of delivering it after the final message"""
    pubsub = yield from PubSub[int].bounded(1)
    fast = yield from pubsub.subscribe()
    slow = yield from pubsub.subscribe()
    yield from pubsub.publish(1)
    # The store stays full until the slow subscriber takes 1, so this
    # publish waits.
    publisher = yield from pubsub.publish(2).fork(start_immediately=True)
    assert (yield from fast.take()) == 1

    yield from pubsub.end(0)

    assert (yield from fast.take()) == 0
    assert (yield from slow.take()) == 1
    assert (yield from publisher.join()) is False
    assert (yield from fast.take()) == 0
    assert (yield from slow.take()) == 0


@testing.effect
def test_end_delivers_a_backpressured_publish_when_the_resumed_publisher_ends_the_pubsub():
    """delivers a backpressured publish to a waiting subscriber when the resumed publisher ends the PubSub"""  # noqa: E501
    pubsub = yield from PubSub[int].bounded(1)
    fast = yield from pubsub.subscribe()
    slow = yield from pubsub.subscribe()
    yield from pubsub.publish(1)
    yield from pubsub.publish(2).and_then(pubsub.end(0)).fork(start_immediately=True)
    assert (yield from fast.take()) == 1
    waiting = yield from fast.take().fork(start_immediately=True)

    assert (yield from slow.take()) == 1

    assert (yield from waiting.join()) == 2
    assert (yield from fast.take()) == 0


@pytest.mark.parametrize("ops", _BUDGETS)
@testing.effect
def test_end_rejects_a_backpressured_publish_that_yields_before_registering_its_surplus(ops: int):
    """rejects a backpressured publish that yields before registering its surplus"""
    pubsub = yield from PubSub[int].bounded(1)
    subscription = yield from pubsub.subscribe()
    yield from pubsub.publish(1)
    publisher = yield from _budget(pubsub.publish(2), ops).fork(start_immediately=True)

    pubsub.unsafe_end(0)
    yield from fx.yield_now()

    assert (yield from subscription.take()) == 1
    assert (yield from subscription.take()) == 0
    assert (yield from publisher.join()) is False


@testing.effect
def test_end_shutdown_still_interrupts_subscribers():
    """shutdown still interrupts subscribers"""
    pubsub = yield from PubSub[int].unbounded()
    subscription: Subscription[int] = yield from pubsub.subscribe()
    yield from pubsub.end(0)
    yield from pubsub.shutdown()

    assert _interrupted((yield from subscription.take().exit()))
