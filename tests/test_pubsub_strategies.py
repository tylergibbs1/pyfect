"""PubSub strategies: the built-ins through Effect's ``Strategy`` interface,
and strategies written by the user. Expected values were printed by
Effect's ``PubSub`` under Node (the user strategies are the same strategies
written in TypeScript), unless a test says otherwise."""

from collections.abc import Callable, Iterable
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import cause, testing
from pyfect.option import Option
from pyfect.pubsub import (
    Atomic,
    BackingSubscription,
    BackPressureStrategy,
    DroppingStrategy,
    Pollers,
    PubSub,
    SlidingStrategy,
    Strategy,
    Subscribers,
    Subscription,
)


def _logged[A](log: list[str], name: str, eff: fx.Effect[A]) -> fx.Effect[A]:
    return eff.tap(lambda v: fx.sync(lambda: log.append(f"{name}{v}")))


def _shown(ex: fx.Exit[Any, Any]) -> object:
    return ex.value if isinstance(ex, fx.Success) else "interrupted"


# --- the built-ins ---------------------------------------------------------


@testing.effect
def test_takes_parked_on_several_subscriptions_wake_in_the_order_they_parked():
    log: list[str] = []
    ps = yield from PubSub[int].bounded(4)
    a = yield from ps.subscribe()
    b = yield from ps.subscribe()
    fb = yield from _logged(log, "b", b.take()).fork(start_immediately=True)
    fa = yield from _logged(log, "a", a.take()).fork(start_immediately=True)
    yield from ps.publish(1)
    log.append("published")
    yield from fa.join()
    yield from fb.join()
    assert log == ["b1", "a1", "published"]


@testing.effect
def test_back_pressure_admits_parked_publishers_oldest_first():
    log: list[str] = []
    ps = yield from PubSub[int].bounded(1)
    sub = yield from ps.subscribe()
    yield from ps.publish(0)
    p1 = yield from _logged(log, "p1 ", ps.publish_all([1, 2])).fork(start_immediately=True)
    p2 = yield from _logged(log, "p2 ", ps.publish(3)).fork(start_immediately=True)
    for _ in range(4):
        taken = yield from sub.take()
        log.append(f"took {taken}")
    yield from p1.join()
    yield from p2.join()
    assert log == ["took 0", "p1 True", "took 1", "p2 True", "took 2", "took 3"]


@testing.effect
def test_back_pressure_with_takes_parked_on_two_subscriptions():
    log: list[str] = []
    ps = yield from PubSub[int].bounded(1)
    a = yield from ps.subscribe()
    b = yield from ps.subscribe()

    def takes(name: str, sub: Subscription[int]) -> fx.Effect[fx.Fiber[list[int], Never]]:
        return fx.for_each(range(3), lambda _: _logged(log, name, sub.take())).fork(
            start_immediately=True
        )

    fa = yield from takes("a", a)
    fb = yield from takes("b", b)
    publisher = yield from _logged(log, "pub ", ps.publish_all([1, 2, 3])).fork(
        start_immediately=True
    )
    yield from fa.join()
    yield from fb.join()
    yield from publisher.join()
    assert log == ["a1", "b1", "a2", "b2", "a3", "b3", "pub True"]


@testing.effect
def test_a_parked_take_reading_the_last_owed_message_admits_a_parked_publisher():
    ps = yield from PubSub[int].bounded(1)
    a = yield from ps.subscribe()
    b = yield from ps.subscribe()
    yield from ps.publish(1)
    publisher = yield from ps.publish(2).fork(start_immediately=True)
    assert (yield from b.take()) == 1
    assert publisher.poll_unsafe() is None
    taker = yield from a.take().fork(start_immediately=True)
    assert publisher.poll_unsafe() == fx.Success(True)
    assert ps.size_unsafe() == 1
    assert (yield from taker.join()) == 1


@testing.effect
def test_back_pressure_gives_parked_takes_an_admitted_message_before_resuming_its_publisher():
    log: list[str] = []
    ps = yield from PubSub[int].bounded(1)
    a = yield from ps.subscribe()
    b = yield from ps.subscribe()
    yield from ps.publish(0)
    publisher = yield from _logged(log, "p ", ps.publish(1)).fork(start_immediately=True)
    yield from a.take()
    taker = yield from _logged(log, "a", a.take()).fork(start_immediately=True)
    yield from b.take()
    log.append("b took")
    yield from taker.join()
    yield from publisher.join()
    assert log == ["a1", "p True", "b took"]


@pytest.mark.parametrize("subscribers", [1, 3])
def test_a_long_parked_publish_all_to_parked_takes_does_not_overflow_the_stack(subscribers: int):
    """Effect's ``BackPressureStrategy`` recurses once per message here and
    overflows Node's stack at 1,000 messages ("Maximum call stack size
    exceeded"), an Effect bug not copied (PARITY section 4)."""
    count = 5_000

    @fx.gen
    def program():
        ps = yield from PubSub[int].bounded(1)
        subs = yield from fx.for_each(range(subscribers), lambda _: ps.subscribe())
        takers = yield from fx.for_each(
            subs,
            lambda sub: fx.for_each(range(count), lambda _: sub.take()).fork(
                start_immediately=True
            ),
        )
        # One more than they take: the last take's room admits it.
        assert (yield from ps.publish_all(range(count + 1))) is True
        assert ps.size_unsafe() == 1
        return (yield from fx.for_each(takers, lambda taker: taker.join()))

    assert fx.run_blocking(fx.scoped(program)) == [list(range(count))] * subscribers


@testing.effect
def test_sliding_with_several_subscribers():
    ps = yield from PubSub[int].sliding(2)
    a = yield from ps.subscribe()
    b = yield from ps.subscribe()
    yield from ps.publish_all([1, 2])
    first = yield from a.take()
    yield from ps.publish(3)
    yield from ps.publish(4)
    assert first == 1
    assert (yield from a.take_all()) == [3, 4]
    assert (yield from b.take_all()) == [3, 4]
    yield from ps.publish_all([5, 6, 7])
    assert (yield from a.take_all()) == [6, 7]
    assert (yield from b.take_all()) == [6, 7]
    assert ps.size_unsafe() == 0


@testing.effect
def test_sliding_with_a_parked_take_on_one_of_two_subscribers():
    log: list[str] = []
    ps = yield from PubSub[int].sliding(1)
    a = yield from ps.subscribe()
    b = yield from ps.subscribe()
    fa = yield from _logged(log, "a", a.take()).fork(start_immediately=True)
    yield from ps.publish_all([1, 2, 3])
    assert (yield from b.take_all()) == [3]
    yield from fa.join()
    assert log == ["a1"]
    assert (yield from a.take_up_to(10)) == [3]


@testing.effect
def test_shutdown_admits_parked_publishers_as_the_store_empties():
    ps = yield from PubSub[int].bounded(1)
    yield from ps.subscribe()
    yield from ps.publish(0)
    p1 = yield from ps.publish(1).fork(start_immediately=True)
    p2 = yield from ps.publish_all([2, 3]).fork(start_immediately=True)
    yield from ps.shutdown()
    assert [_shown((yield from p1.await_exit())), _shown((yield from p2.await_exit()))] == [
        True,
        True,
    ]


@testing.effect
def test_shutdown_interrupts_a_publisher_the_store_never_admits():
    """A subscriber outside the hub keeps the store full, so the publisher
    is still waiting when the strategy's ``shutdown`` runs."""
    atomic = Atomic[int].bounded(1)
    ps = yield from PubSub.make(lambda: atomic, BackPressureStrategy)
    atomic.subscribe()
    yield from ps.publish(0)
    publisher = yield from ps.publish(1).fork(start_immediately=True)
    yield from ps.shutdown()
    assert _shown((yield from publisher.await_exit())) == "interrupted"


@pytest.mark.parametrize(
    ("name", "built_in"),
    [
        ("suspend", BackPressureStrategy),
        ("dropping", DroppingStrategy),
        ("sliding", SlidingStrategy),
    ],
)
def test_a_strategy_name_is_shorthand_for_a_new_built_in(name: Any, built_in: type[Any]):
    """pyfect's own spelling, not Effect's."""

    @fx.gen
    def program():
        first = yield from PubSub.make(lambda: Atomic[int].bounded(2), name)
        second = yield from PubSub.make(lambda: Atomic[int].bounded(2), name)
        return first.strategy, second.strategy

    first, second = fx.run_blocking(program)
    assert type(first) is built_in
    assert first is not second


# --- user strategies ---------------------------------------------------------


class _Counting[A](DroppingStrategy[A]):
    """Drops as Effect's ``DroppingStrategy`` does, counting what it drops."""

    def __init__(self) -> None:
        self.dropped = 0

    def handle_surplus(
        self,
        pubsub: Atomic[A],
        subscribers: Subscribers[A],
        elements: Iterable[A],
        is_shutdown: Callable[[], bool],
        ended: Callable[[], Option[A]],
    ) -> fx.Effect[bool]:
        self.dropped += len(list(elements))
        return fx.succeed(False)


@testing.effect
def test_a_user_strategy_extending_a_built_in():
    strategy = _Counting[int]()
    ps = yield from PubSub.make(lambda: Atomic[int].bounded(2), lambda: strategy)
    sub = yield from ps.subscribe()
    assert (yield from ps.publish_all([1, 2, 3, 4])) is False
    assert (yield from ps.publish(5)) is False
    assert strategy.dropped == 3
    assert (yield from sub.take_all()) == [1, 2]


class _Pairs[A]:
    """Written from scratch, as an object with the five members (not a
    subclass): gives messages to parked takes two at a time."""

    @property
    def shutdown(self) -> fx.Effect[None]:
        return fx.void

    def handle_surplus(
        self,
        pubsub: Atomic[A],
        subscribers: Subscribers[A],
        elements: Iterable[A],
        is_shutdown: Callable[[], bool],
        ended: Callable[[], Option[A]],
    ) -> fx.Effect[bool]:
        return fx.succeed(False)

    def on_pubsub_empty_space_unsafe(self, pubsub: Atomic[A], subscribers: Subscribers[A]) -> None:
        pass

    def complete_pollers_unsafe(
        self,
        pubsub: Atomic[A],
        subscribers: Subscribers[A],
        subscription: BackingSubscription[A],
        pollers: Pollers[A],
    ) -> None:
        while subscription.size() >= 2 and len(pollers) >= 2:
            for _ in range(2):
                poller, polled = pollers.take(), subscription.poll()
                assert poller is not None
                assert polled is not None
                poller.succeed(polled.value)

    def complete_subscribers_unsafe(self, pubsub: Atomic[A], subscribers: Subscribers[A]) -> None:
        for subscription, pollers in subscribers.items():
            self.complete_pollers_unsafe(pubsub, subscribers, subscription, pollers)


@testing.effect
def test_a_user_strategy_decides_when_parked_takes_get_their_messages():
    log: list[str] = []
    ps = yield from PubSub.make(Atomic[int].unbounded, _Pairs[int])
    sub = yield from ps.subscribe()
    f1 = yield from _logged(log, "t1 ", sub.take()).fork(start_immediately=True)
    f2 = yield from _logged(log, "t2 ", sub.take()).fork(start_immediately=True)
    yield from ps.publish(1)
    log.append("after 1")
    yield from ps.publish(2)
    log.append("after 2")
    yield from f1.join()
    yield from f2.join()
    assert log == ["after 1", "t1 1", "t2 2", "after 2"]


class _Dying[A](DroppingStrategy[A]):
    """Fails each parked take with a defect, consuming its message."""

    def complete_pollers_unsafe(
        self,
        pubsub: Atomic[A],
        subscribers: Subscribers[A],
        subscription: BackingSubscription[A],
        pollers: Pollers[A],
    ) -> None:
        if not subscription.is_empty() and (poller := pollers.take()) is not None:
            subscription.poll()
            poller.done(fx.Failure(cause.die("boom")))


@testing.effect
def test_a_user_strategy_can_fail_a_parked_take():
    ps = yield from PubSub.make(Atomic[int].unbounded, _Dying[int])
    sub = yield from ps.subscribe()
    fiber = yield from sub.take().fork(start_immediately=True)
    yield from ps.publish(1)
    ex = yield from fiber.await_exit()
    assert isinstance(ex, fx.Failure)
    assert ex.cause == cause.die("boom")


def _woken_then_interrupted(links: int) -> tuple[object, tuple[int, ...]]:
    """A take on an unbounded hub, given its message by a publish made
    ``links`` nested runs deep, and interrupted right after by the
    publishing fiber. Past ``_MAX_NESTED_RUNS`` the woken take is queued, so
    the interrupt reaches it before it collects."""

    @fx.gen
    def program():
        ps = yield from PubSub[int].unbounded()
        sub = yield from ps.subscribe()
        taker = yield from sub.take().fork(start_immediately=True)
        gates = yield from fx.for_each(range(links + 1), lambda _: fx.Deferred[None].make())

        @fx.gen
        def last():
            yield from gates[links].wait()
            yield from ps.publish(1)
            taker.interrupt_as_unsafe(None)

        yield from last.fork(start_immediately=True)
        for i in reversed(range(links)):
            link = gates[i].wait().and_then(gates[i + 1].succeed(None))
            yield from link.fork(start_immediately=True)
        yield from gates[0].succeed(None)
        ex = yield from taker.await_exit()
        return _shown(ex), tuple((yield from sub.take_up_to(10)))

    return fx.run_blocking(fx.scoped(program))


def test_a_message_given_to_a_take_interrupted_before_collecting_goes_back():
    """pyfect's rule that a woken waiter claims in its own step (not
    checked under Node). Either the take collects its message, or it is
    interrupted first and the message is the subscription's next."""
    outcomes = {_woken_then_interrupted(links) for links in range(24)}
    assert outcomes == {(1, ()), ("interrupted", (1,))}


def test_a_user_strategy_has_the_strategy_type():
    """Static: ``_Pairs`` matches the protocol without subclassing it."""
    strategy: Strategy[int] = _Pairs[int]()
    assert strategy.shutdown is not None


# --- Subscribers -------------------------------------------------------------


def test_subscribers_iterate_as_a_javascript_map():
    """Entries added while iterating are visited, removed ones skipped, and
    setting an existing key keeps its place (``Map`` semantics)."""
    atomic = Atomic[int].unbounded()
    a, b, c, d = (atomic.subscribe() for _ in range(4))
    subs = Subscribers[int]()
    for key in (a, b, c):
        subs[key] = Pollers(key)
    seen: list[BackingSubscription[int]] = []
    for key in subs:
        seen.append(key)
        if key is a:
            del subs[b]
            subs[d] = Pollers(d)
            subs[a] = Pollers(a)
        if key is c and seen.count(c) == 1:
            del subs[c]
            subs[c] = Pollers(c)
    assert seen == [a, c, d, c]
    assert list(subs) == [a, d, c]
