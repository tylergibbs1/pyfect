"""PubSub behavior beyond Effect's tests. Expected values were printed by
Effect's ``PubSub`` under Node unless a test says otherwise."""

from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.cause import Die
from pyfect.pubsub import Atomic, PubSub


def _interrupted(ex: fx.Exit[Any, Any] | None) -> bool:
    return isinstance(ex, fx.Failure) and ex.cause.has_interrupts


@testing.effect
def test_a_message_published_to_a_waiting_subscriber_frees_its_room():
    pubsub = yield from PubSub[int].dropping(1)
    sub = yield from pubsub.subscribe()
    fiber = yield from sub.take().fork(start_immediately=True)
    results = yield from fx.for_each((1, 2, 3), pubsub.publish)
    assert results == [True, True, False]
    assert pubsub.size_unsafe() == 1
    assert (yield from fiber.join()) == 1
    assert (yield from sub.take_all()) == [2]


@testing.effect
def test_a_bounded_publish_does_not_wait_for_room_a_waiting_subscriber_freed():
    pubsub = yield from PubSub[int].bounded(1)
    sub = yield from pubsub.subscribe()
    taker = yield from sub.take().fork(start_immediately=True)
    assert (yield from pubsub.publish(1)) is True
    publisher = yield from pubsub.publish(2).fork(start_immediately=True)
    assert publisher.poll_unsafe() == fx.Success(True)
    assert (yield from taker.join()) == 1
    assert (yield from sub.take_all()) == [2]


@testing.effect
def test_a_parked_publish_all_fills_room_a_waiting_subscriber_freed():
    pubsub = yield from PubSub[int].bounded(2)
    sub = yield from pubsub.subscribe()
    taker = yield from sub.take().fork(start_immediately=True)
    publisher = yield from pubsub.publish_all([1, 2, 3, 4]).fork(start_immediately=True)
    assert publisher.poll_unsafe() is None
    assert (yield from taker.join()) == 1
    assert pubsub.size_unsafe() == 2
    assert (yield from sub.take_all()) == [2, 3]


@testing.effect
def test_a_bounded_publish_all_waits_for_room_then_completes():
    pubsub = yield from PubSub[int].bounded(2)
    sub = yield from pubsub.subscribe()
    publisher = yield from pubsub.publish_all([1, 2, 3, 4, 5]).fork(start_immediately=True)
    assert (yield from sub.take_all()) == [1, 2]
    assert publisher.poll_unsafe() is None
    assert (yield from sub.take_all()) == [3, 4]
    assert (yield from sub.take_all()) == [5]
    assert (yield from publisher.join()) is True


@pytest.mark.parametrize("ops", range(1, 40))
@testing.effect
def test_a_message_read_for_an_interrupted_taker_goes_to_the_next_take(ops: int):
    """pyfect's own: the woken taker can be interrupted before it retries;
    the message read for it stays with the subscription."""
    pubsub = yield from PubSub[int].unbounded()
    sub = yield from pubsub.subscribe()
    taker = (
        yield from sub.take()
        .pipe(fx.provide_service(fx.MaxOpsBeforeYield, ops))
        .fork(start_immediately=True)
    )
    yield from pubsub.publish(1)
    yield from taker.interrupt()
    rest = yield from sub.take_up_to(1)
    taken = taker.poll_unsafe()
    delivered = [*([taken.value] if isinstance(taken, fx.Success) else []), *rest]
    assert delivered == [1]


@testing.effect
def test_dropping_publish_all_publishes_what_fits_and_returns_false():
    pubsub = yield from PubSub[int].dropping(2)
    sub = yield from pubsub.subscribe()
    assert (yield from pubsub.publish_all([1, 2, 3])) is False
    assert (yield from sub.take_all()) == [1, 2]


@testing.effect
def test_sliding_publish_drops_the_oldest_and_unsafe_publish_does_not_slide():
    pubsub = yield from PubSub[int].sliding(2)
    sub = yield from pubsub.subscribe()
    results = yield from fx.for_each((1, 2, 3), pubsub.publish)
    assert results == [True, True, True]
    assert pubsub.publish_unsafe(4) is False
    assert (yield from sub.take_all()) == [2, 3]


@testing.effect
def test_sliding_publish_all_slides_before_each_surplus_message():
    """Effect 4.0.6 under Node gives ``[1, [4]]``: its ``SlidingStrategy``
    slides before each surplus message, even when a waiting subscriber
    has just read one and made room."""
    pubsub = yield from PubSub[int].sliding(2)
    sub = yield from pubsub.subscribe()
    taker = yield from sub.take().fork(start_immediately=True)
    yield from pubsub.publish_all([1, 2, 3, 4])
    assert (yield from taker.join()) == 1
    assert (yield from sub.take_all()) == [4]


@testing.effect
def test_counts_of_zero_or_less_take_nothing():
    pubsub = yield from PubSub[int].unbounded(replay=2)
    yield from pubsub.publish_all([1, 2])
    sub = yield from pubsub.subscribe()
    yield from pubsub.publish(3)
    assert (yield from sub.take_up_to(-1)) == []
    assert (yield from sub.take_between(-3, -1)) == []
    assert (yield from sub.take_between(2, 1)) == []
    assert (yield from sub.take_between(0, 1)) == [1]
    assert (yield from sub.remaining()) == 2


@testing.effect
def test_take_between_on_an_ended_hub_repeats_the_final_message():
    pubsub = yield from PubSub[int].unbounded()
    sub = yield from pubsub.subscribe()
    yield from pubsub.end(0)
    assert (yield from sub.take_between(3, 3)) == [0, 0, 0]
    assert (yield from sub.take_up_to(3)) == []
    assert (yield from sub.take_between(0, 2)) == []


@testing.effect
def test_subscribing_after_shutdown_gives_an_unsubscribed_subscription():
    pubsub = yield from PubSub[int].unbounded()
    yield from pubsub.shutdown()
    sub = yield from pubsub.subscribe()
    assert _interrupted((yield from sub.take().exit()))
    assert (yield from pubsub.is_shutdown()) is True
    assert (yield from pubsub.size()) == 0
    assert (yield from pubsub.end(1)) is False


@testing.effect
def test_shutdown_lets_a_waiting_publish_complete():
    pubsub = yield from PubSub[int].bounded(1)
    yield from pubsub.subscribe()
    yield from pubsub.publish(1)
    publisher = yield from pubsub.publish(2).fork(start_immediately=True)
    yield from pubsub.shutdown()
    assert (yield from publisher.await_exit()) == fx.Success(True)
    assert (yield from pubsub.size()) == 0


@testing.effect
def test_await_shutdown_waits_for_shutdown():
    pubsub = yield from PubSub[int].unbounded()
    waiter = yield from pubsub.await_shutdown().fork(start_immediately=True)
    assert waiter.poll_unsafe() is None
    yield from pubsub.shutdown()
    yield from pubsub.shutdown()
    assert (yield from waiter.join()) is None


@testing.effect
def test_an_unsubscribed_subscription_interrupts_every_take():
    pubsub = yield from PubSub[int].unbounded()
    scope = fx.CloseableScope()
    sub = yield from pubsub.subscribe().pipe(fx.provide_service(fx.Scope, scope))
    yield from scope.close(fx.Success(None))
    assert sub.remaining_unsafe() is None
    assert _interrupted((yield from sub.remaining().exit()))
    assert _interrupted((yield from sub.take_up_to(1).exit()))


@testing.effect
def test_is_full_is_empty_and_capacity():
    pubsub = yield from PubSub[int].bounded(2)
    yield from pubsub.subscribe()
    yield from pubsub.publish_all([1, 2])
    unbounded = yield from PubSub[int].unbounded()
    assert (yield from pubsub.is_full()) is True
    assert (yield from pubsub.is_empty()) is False
    assert pubsub.capacity == 2
    assert unbounded.capacity is None
    assert (yield from unbounded.is_empty()) is True


@testing.effect
def test_a_capacity_below_one_is_a_defect():
    ex = yield from PubSub[int].bounded(0).exit()
    assert isinstance(ex, fx.Failure)
    defects = [r.defect for r in ex.cause.reasons if isinstance(r, Die)]
    assert [str(d) for d in defects] == ["Cannot construct PubSub with capacity of 0"]


@testing.effect
def test_make_builds_a_hub_over_a_given_store():
    pubsub = yield from PubSub.make(lambda: Atomic[str].bounded(100), "suspend")
    assert (yield from pubsub.publish("Hello")) is True
    yield from pubsub.shutdown()


@testing.effect
def test_a_message_read_for_a_waiting_taker_is_not_taken_by_another_take():
    pubsub = yield from PubSub[int].unbounded()
    sub = yield from pubsub.subscribe()
    waiting = yield from sub.take().fork(start_immediately=True)
    yield from pubsub.publish(1)
    assert (yield from sub.take_up_to(1)) == []
    yield from pubsub.publish(2)
    assert (yield from waiting.join()) == 1
    assert (yield from sub.take_up_to(5)) == [2]


@testing.effect
def test_waiting_takers_of_one_subscription_are_served_in_order():
    pubsub = yield from PubSub[int].unbounded()
    sub = yield from pubsub.subscribe()
    first = yield from sub.take().fork(start_immediately=True)
    yield from pubsub.publish(1)
    second = yield from sub.take().fork(start_immediately=True)
    yield from pubsub.publish(2)
    assert [(yield from first.join()), (yield from second.join())] == [1, 2]


@testing.effect
def test_take_all_behind_a_waiting_take_waits_its_turn():
    pubsub = yield from PubSub[int].unbounded()
    sub = yield from pubsub.subscribe()
    single = yield from sub.take().fork(start_immediately=True)
    batch = yield from sub.take_all().fork(start_immediately=True)
    yield from pubsub.publish_all([1, 2, 3])
    assert [(yield from single.join()), (yield from batch.join())] == [1, [2, 3]]


@testing.effect
def test_an_interrupted_waiting_take_leaves_the_queue():
    pubsub = yield from PubSub[int].unbounded()
    sub = yield from pubsub.subscribe()
    first = yield from sub.take().fork(start_immediately=True)
    second = yield from sub.take().fork(start_immediately=True)
    yield from first.interrupt()
    yield from pubsub.publish(1)
    assert (yield from second.join()) == 1
    assert (yield from sub.remaining()) == 0


@pytest.mark.parametrize("ops", range(1, 40))
@testing.effect
def test_a_take_that_starts_waiting_after_end_gets_the_final_message(ops: int):
    pubsub = yield from PubSub[int].unbounded()
    sub = yield from pubsub.subscribe()
    single = (
        yield from sub.take()
        .pipe(fx.provide_service(fx.MaxOpsBeforeYield, ops))
        .fork(start_immediately=True)
    )
    batch = (
        yield from sub.take_all()
        .pipe(fx.provide_service(fx.MaxOpsBeforeYield, ops))
        .fork(start_immediately=True)
    )
    pubsub.end_unsafe(0)
    assert (yield from single.join()) == 0
    assert (yield from batch.join()) == [0]


@testing.effect
def test_a_waiting_take_is_interrupted_by_the_fiber_that_unsubscribes():
    pubsub = yield from PubSub[int].unbounded()
    sub = yield from pubsub.subscribe()
    taker = yield from sub.take().fork(start_immediately=True)
    closer = yield from pubsub.shutdown().fork()
    yield from closer.join()
    ex = yield from taker.await_exit()
    assert isinstance(ex, fx.Failure)
    assert ex.cause.interruptors == {closer.id}


@testing.effect
def test_a_take_woken_with_a_message_gets_it_when_the_pubsub_then_shuts_down():
    # Effect resumes the woken take at once, so the shutdown comes after it
    # has its message.
    pubsub = yield from PubSub[int].unbounded()
    sub = yield from pubsub.subscribe()
    single = yield from sub.take().fork(start_immediately=True)
    batch = yield from sub.take_all().fork(start_immediately=True)
    yield from pubsub.publish_all([1, 2, 3])
    yield from pubsub.shutdown()
    assert (yield from single.join()) == 1
    assert (yield from batch.join()) == [2, 3]
