"""Interleaving scenarios for Queues, PubSub, Semaphore, Latch, the refs,
Deferred and References (README.md).

Each is small: two or three fibers, an interrupt from a fiber and one from a
simulated thread, decided results recorded in the continuation that receives
them. Where a primitive has ``*_unsafe`` calls, a simulated thread makes them
from outside any fiber, so what they wake is resumed through the scheduler.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import itertools
from collections.abc import Callable, Sequence
from typing import Any

import pyfect as fx
from pyfect import scope
from pyfect.errors import Done
from pyfect.exit import Exit, Failure, Success
from pyfect.pubsub import Subscription
from pyfect.result import Ok

from ._harness import Problems, Scenario, ThreadBody, World
from ._kit import AnyFiber, Slot, from_thread, interrupt_from_thread


def _in_order(seen: Sequence[int]) -> bool:
    """Strictly increasing: in order, none twice."""
    return all(a < b for a, b in itertools.pairwise(seen))


def _ended_with_done(ex: Exit[Any, Any]) -> bool:
    return isinstance(ex, Failure) and isinstance(ex.cause.find_error(), Ok)


_THREAD = -1
"""The interruptor id ``_interrupt_as_thread`` uses, to tell its interrupt
from a primitive's own (a queue's shutdown interrupts with no id)."""


def _interrupt_as_thread(w: World, name: str, target: Slot[AnyFiber]) -> None:
    """``interrupt_from_thread``, interrupting as ``_THREAD``."""

    def body() -> ThreadBody:
        yield target.is_set
        target.get().interrupt_as_unsafe(_THREAD)

    w.thread(name, body)


def _by_thread(ex: Exit[Any, Any]) -> bool:
    return isinstance(ex, Failure) and _THREAD in ex.cause.interruptors


def _record_exit(
    exits: dict[str, Exit[Any, Any]], name: str
) -> Callable[[Exit[Any, Any]], fx.Effect[None]]:
    return lambda ex: fx.sync(lambda: exits.__setitem__(name, ex))


# --- Queue -----------------------------------------------------------------------------


def _queue_sliding(w: World) -> None:
    """Four offers into a sliding queue of two, against a taker of two
    (interrupted from a thread) and one taker interrupted by a fiber. Every
    offer succeeds; a sliding queue drops only its oldest items, so what was
    taken and what is left are in order, none twice, and always include the
    newest item."""
    taken: list[int] = []
    queue = Slot[fx.Queue[int]]()
    second = Slot[AnyFiber]()
    refused: list[int] = []

    def offer(q: fx.Queue[int], i: int) -> fx.Effect[None]:
        return q.offer(i).map(lambda ok: None if ok else refused.append(i))

    @fx.gen
    def main():
        q = queue.set((yield from fx.Queue[int].sliding(2)))
        first = yield from q.take().map(taken.append).fork()
        second.set((yield from fx.for_each(range(2), lambda _: q.take().map(taken.append)).fork()))
        offers = yield from fx.for_each([1, 2, 3, 4], lambda i: offer(q, i)).fork()
        yield from fx.yield_now()
        yield from first.interrupt()
        yield from offers.await_exit()
        yield from second.get().interrupt()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", second)

    def check() -> Problems:
        left = list(queue.get()._items)
        both = sorted(taken) + left
        if refused or not _in_order(both) or 4 not in both or len(left) > 2:
            return f"taken {taken}, left {left}, refused {refused}"
        return None

    w.check(check)


def _queue_dropping(w: World) -> None:
    """Three offers into a dropping queue of one, a taker interrupted by a
    fiber and one of two items interrupted from a thread. An offer that said
    ``True`` is taken once or still queued; one that said ``False`` never
    shows up."""
    taken: list[int] = []
    accepted: list[int] = []
    queue = Slot[fx.Queue[int]]()
    second = Slot[AnyFiber]()

    def offer(q: fx.Queue[int], i: int) -> fx.Effect[None]:
        return q.offer(i).map(lambda ok: accepted.append(i) if ok else None)

    @fx.gen
    def main():
        q = queue.set((yield from fx.Queue[int].dropping(1)))
        first = yield from q.take().map(taken.append).fork()
        second.set((yield from fx.for_each(range(2), lambda _: q.take().map(taken.append)).fork()))
        offers = yield from fx.for_each([1, 2, 3], lambda i: offer(q, i)).fork()
        yield from fx.yield_now()
        yield from first.interrupt()
        yield from offers.await_exit()
        yield from second.get().interrupt()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", second)

    def check() -> Problems:
        left = list(queue.get()._items)
        if sorted(taken) + left != accepted or len(set(taken)) != len(taken):
            return f"accepted {accepted}, taken {taken}, left {left}"
        return None

    w.check(check)


def _queue_batches(w: World) -> None:
    """Two ``offer_all`` batches into an unbounded queue, against a
    ``take_n(2)`` interrupted from a thread and a ``take_between(1, 3)``
    interrupted by a fiber; ``take_all`` then empties the rest. Every item is
    taken exactly once, and each batch's items come out in order."""
    batches: list[list[int]] = []
    unadded: list[int] = []
    interrupter = Slot[AnyFiber]()

    def into(found: Sequence[int]) -> None:
        batches.append(list(found))

    @fx.gen
    def main():
        q = yield from fx.Queue[int].unbounded()
        pairs = yield from q.take_n(2).map(into).fork()
        some = yield from q.take_between(1, 3).map(into).fork()
        a = yield from q.offer_all([1, 2, 3]).map(unadded.extend).fork()
        b = yield from q.offer_all([4, 5]).map(unadded.extend).fork()
        interrupter.set(pairs)
        yield from fx.yield_now()
        yield from some.interrupt()
        yield from a.await_exit()
        yield from b.await_exit()
        yield from pairs.await_exit()
        rest = yield from q.size()
        if rest:
            yield from q.take_all().map(into)

    w.fork(main)
    interrupt_from_thread(w, "interrupter", interrupter)

    def check() -> Problems:
        items = [i for batch in batches for i in batch]
        if unadded or sorted(items) != [1, 2, 3, 4, 5]:
            return f"taken {batches}, not added {unadded}"
        for batch in batches:
            if not (
                _in_order([i for i in batch if i <= 3]) and _in_order([i for i in batch if i > 3])
            ):
                return f"a batch out of order: {batches}"
        return None

    w.check(check)


def _queue_offer_all_parked(w: World) -> None:
    """An ``offer_all`` of four into a bounded queue of two parks with two
    admitted and is interrupted from a thread; a ``take_n(2)`` and a
    ``take`` (interrupted by a fiber) drain it. The items admitted are a
    prefix of the batch (an interrupted batch keeps what it delivered), each
    taken once or still queued; a finished ``offer_all`` returns exactly the
    items not added."""
    taken: list[int] = []
    rest: list[list[int]] = []
    queue = Slot[fx.Queue[int]]()
    offerer = Slot[AnyFiber]()

    @fx.gen
    def main():
        q = queue.set((yield from fx.Queue[int].bounded(2)))
        offerer.set((yield from q.offer_all([1, 2, 3, 4]).map(rest.append).fork()))
        yield from fx.yield_now()
        one = yield from q.take().map(taken.append).fork()
        pair = yield from q.take_n(2).map(taken.extend).fork()
        yield from fx.yield_now()
        yield from one.interrupt()
        yield from fx.yield_now()
        # Interrupted early, the batch may leave too few items for the pair.
        yield from offerer.get().interrupt()
        yield from pair.interrupt()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", offerer)

    def check() -> Problems:
        left = list(queue.get()._items)
        moved = sorted(taken) + left
        if moved != list(range(1, len(moved) + 1)) or len(left) > 2:
            return f"taken {taken}, left {left}"
        if rest and rest[0] != [i for i in [1, 2, 3, 4] if i not in moved]:
            return f"offer_all returned {rest[0]}, but taken {taken} and left {left}"
        return None

    w.check(check)


def _queue_end_await(w: World) -> None:
    """A producer offers two items into a queue of one and ends it; a
    consumer (interrupted from a thread) takes until ``Done``, an
    ``await_done`` waiter is interrupted by a fiber or sees the end. The
    items are taken exactly once between the consumer and a final
    ``collect``; ``await_done`` succeeds only on a drained, ended queue."""
    seen: list[int] = []
    collected: list[int] = []
    exits: dict[str, Exit[Any, Any]] = {}
    drained_when_awaited: list[bool] = []
    consumer = Slot[AnyFiber]()

    @fx.gen
    def main():
        q = yield from fx.Queue[int, Done].bounded(1)

        @fx.gen
        def consume():
            while True:
                yield from q.take().map(seen.append)

        consumer.set((yield from consume.on_exit(_record_exit(exits, "consumer")).fork()))
        awaiter = yield from (
            q.await_done()
            .map(lambda _: drained_when_awaited.append(q.is_done_unsafe()))
            .on_exit(_record_exit(exits, "awaiter"))
            .fork()
        )
        producer = yield from (q.offer(1).and_then(q.offer(2)).and_then(q.end()).fork())
        yield from fx.yield_now()
        yield from awaiter.interrupt()
        yield from consumer.get().await_exit()
        yield from q.collect().map(collected.extend)
        yield from producer.await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", consumer)

    def check() -> Problems:
        if seen + collected != [1, 2]:
            return f"the consumer took {seen}, collect got {collected}"
        if drained_when_awaited != [True] * len(drained_when_awaited):
            return f"await_done returned before the queue was done: {drained_when_awaited}"
        ex = exits.get("consumer")
        if ex is not None and _ended_with_done(ex) and seen != [1, 2]:
            return f"the consumer ended with Done after taking only {seen}"
        return None

    w.check(check)


def _queue_end_vs_shutdown(w: World) -> None:
    """One fiber ends a queue holding an item while another shuts it down;
    a parked ``offer`` and an ``await_done`` waiter (interrupted from a
    thread) race them. Exactly one of end and shutdown takes effect first;
    the parked offer is admitted or refused, and ``await_done`` succeeds
    exactly when the end came first."""
    results: dict[str, bool] = {}
    exits: dict[str, Exit[Any, Any]] = {}
    awaiter = Slot[AnyFiber]()

    def note(name: str) -> Callable[[bool], None]:
        return lambda ok: results.__setitem__(name, ok)

    @fx.gen
    def main():
        q = yield from fx.Queue[int, Done].bounded(1)
        yield from q.offer(1)
        offer = yield from q.offer(2).map(note("offer")).fork()
        awaiter.set((yield from q.await_done().on_exit(_record_exit(exits, "awaiter")).fork()))
        ender = yield from q.end().map(note("end")).fork()
        shutter = yield from q.shutdown().map(note("shutdown")).fork()
        yield from ender.await_exit()
        yield from shutter.await_exit()
        yield from offer.await_exit()
        yield from awaiter.get().await_exit()

    w.fork(main)
    _interrupt_as_thread(w, "interrupter", awaiter)

    def check() -> Problems:
        if not results.get("shutdown") and not results.get("end"):
            return f"neither end nor shutdown took effect: {results}"
        if results.get("offer"):
            return f"an offer to a full queue was admitted with no taker: {results}"
        ex = exits.get("awaiter")
        if ex is None or _by_thread(ex):
            return None
        if isinstance(ex, Success) != results.get("end", False):
            return f"await_done ended with {ex}, but end returned {results.get('end')}"
        return None

    w.check(check)


def _queue_external_producer(w: World) -> None:
    """A simulated thread offers two items with ``offer_unsafe`` and ends the
    queue with ``end_unsafe``, waking a parked taker through the scheduler;
    a second taker is interrupted by a fiber. Each item is taken exactly
    once, in order per taker, and both takers end once the queue is done."""
    seen: dict[str, list[int]] = {"a": [], "b": []}
    exits: dict[str, Exit[Any, Any]] = {}
    queue = Slot[fx.Queue[int, Done]]()
    sent: list[int] = []

    def consume(q: fx.Queue[int, Done], name: str) -> fx.Effect[None, Done]:
        @fx.gen
        def body():
            while True:
                yield from q.take().map(seen[name].append)

        return body

    @fx.gen
    def main():
        q = queue.set((yield from fx.Queue[int, Done].unbounded()))
        a = yield from consume(q, "a").on_exit(_record_exit(exits, "a")).fork()
        b = yield from consume(q, "b").on_exit(_record_exit(exits, "b")).fork()
        yield from fx.yield_now()
        yield from b.interrupt()
        yield from a.await_exit()

    def producer() -> ThreadBody:
        yield queue.is_set
        q = queue.get()
        for i in (1, 2):
            if q.offer_unsafe(i):
                sent.append(i)
            yield
        q.end_unsafe()

    w.fork(main)
    w.thread("producer", producer)

    def check() -> Problems:
        a, b = seen["a"], seen["b"]
        if sorted(a + b) != sent or sent != [1, 2] or not _in_order(a) or not _in_order(b):
            return f"sent {sent}, a took {a}, b took {b}"
        ex = exits.get("a")
        if ex is None or not _ended_with_done(ex):
            return f"the taker ended with {ex}, not Done"
        return None

    w.check(check)


# --- PubSub ----------------------------------------------------------------------------


def _reader(
    sub: Subscription[int], seen: list[int], *, until: int | None = None
) -> fx.Effect[None]:
    """Take into ``seen`` until ``until`` is taken (forever if ``None``)."""

    @fx.gen
    def body():
        while True:
            value = yield from sub.take().tap(lambda v: fx.sync(lambda: seen.append(v)))
            if value == until:
                return

    return body


def _pubsub_sliding(w: World) -> None:
    """Two subscribers of a sliding PubSub of one read while three messages
    are published, then the hub shuts down; one reader is interrupted by a
    fiber, the other from a thread. Every publish succeeds (sliding drops
    the oldest instead), and each reader sees messages in order, once."""
    seen: dict[str, list[int]] = {"a": [], "b": []}
    refused: list[int] = []
    first = Slot[AnyFiber]()

    @fx.gen
    def body():
        ps = yield from fx.PubSub[int].sliding(1)
        a = yield from ps.subscribe()
        b = yield from ps.subscribe()
        first.set((yield from _reader(a, seen["a"]).fork()))
        second = yield from _reader(b, seen["b"]).fork()
        publisher = yield from fx.for_each(
            [1, 2, 3], lambda i: ps.publish(i).map(lambda ok: None if ok else refused.append(i))
        ).fork()
        yield from fx.yield_now()
        yield from second.interrupt()
        yield from publisher.await_exit()
        yield from ps.shutdown()
        yield from first.get().await_exit()

    w.fork(fx.scoped(body))
    interrupt_from_thread(w, "interrupter", first)

    def check() -> Problems:
        bad = {k: v for k, v in seen.items() if not _in_order(v) or not set(v) <= {1, 2, 3}}
        if refused or bad:
            return f"refused {refused}, readers saw {seen}"
        return None

    w.check(check)


def _pubsub_dropping_unsafe(w: World) -> None:
    """A dropping PubSub of one with two subscribers: a simulated thread
    publishes with ``publish_unsafe`` and ends the hub with ``end_unsafe``
    while a fiber publishes too; one reader takes once and is interrupted by
    a fiber. The other reader sees exactly the messages whose publish said
    ``True``, each publisher's in order, then the end."""
    seen: list[int] = []
    accepted: list[int] = []
    hub = Slot[fx.PubSub[int]]()

    @fx.gen
    def body():
        ps = yield from fx.PubSub[int].dropping(1)
        a = yield from ps.subscribe()
        b = yield from ps.subscribe()
        hub.set(ps)
        reader = yield from _reader(a, seen, until=0).fork()
        once = yield from b.take().fork()
        publisher = yield from fx.for_each(
            [3, 4], lambda i: ps.publish(i).map(lambda ok: accepted.append(i) if ok else None)
        ).fork()
        yield from fx.yield_now()
        yield from once.interrupt()
        yield from publisher.await_exit()
        yield from reader.await_exit()

    def producer() -> ThreadBody:
        yield hub.is_set
        for i in (1, 2):
            if hub.get().publish_unsafe(i):
                accepted.append(i)
            yield
        hub.get().end_unsafe(0)

    w.fork(fx.scoped(body))
    w.thread("producer", producer)

    def check() -> Problems:
        got = seen[:-1]
        if seen[-1:] != [0] or sorted(got) != sorted(accepted):
            return f"accepted {accepted}, the reader saw {seen}"
        if not _in_order([i for i in got if i < 3]) or not _in_order([i for i in got if i >= 3]):
            return f"the reader saw a publisher's messages out of order: {seen}"
        return None

    w.check(check)


def _pubsub_replay(w: World) -> None:
    """An unbounded PubSub replaying two: after two publishes, a publisher
    adds two more and ends the hub while two late subscribers join, one
    interrupted from a thread and one by a fiber. A subscriber sees the
    replayed messages, then every later one, in order with no gap, then the
    end."""
    seen: dict[str, list[int]] = {"a": [], "b": []}
    late = Slot[AnyFiber]()

    def subscriber(ps: fx.PubSub[int], name: str) -> fx.Effect[None]:
        return fx.scoped(ps.subscribe().flat_map(lambda sub: _reader(sub, seen[name], until=0)))

    @fx.gen
    def main():
        ps = yield from fx.PubSub[int].unbounded(replay=2)
        yield from ps.publish(1)
        yield from ps.publish(2)
        publisher = yield from ps.publish(3).and_then(ps.publish(4)).and_then(ps.end(0)).fork()
        late.set((yield from subscriber(ps, "a").fork()))
        other = yield from subscriber(ps, "b").fork()
        yield from fx.yield_now()
        yield from other.interrupt()
        yield from publisher.await_exit()
        yield from late.get().await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", late)

    def check() -> Problems:
        for name, got in seen.items():
            values = [v for v in got if v != 0]
            start = values[0] if values else 1
            if values != list(range(start, start + len(values))) or start > 3:
                return f"{name} saw {got}"
            if got[-1:] == [0] and values[-1:] != [4]:
                return f"{name} saw the end before every message: {got}"
        return None

    w.check(check)


def _pubsub_shutdown_race(w: World) -> None:
    """A bounded PubSub of one: a publisher waits on a slow reader, a second
    subscriber joins while another fiber shuts the hub down, and an
    ``await_shutdown`` waiter is interrupted from a thread. The publisher
    never waits forever on subscribers that are gone, readers see messages
    in order, once, and ``await_shutdown`` returns only once shut down."""
    seen: dict[str, list[int]] = {"a": [], "b": []}
    published: list[int] = []
    shut_when_awaited: list[bool] = []
    waiter = Slot[AnyFiber]()

    @fx.gen
    def body():
        ps = yield from fx.PubSub[int].bounded(1)
        a = yield from ps.subscribe()
        reader = yield from _reader(a, seen["a"]).fork()
        joiner = yield from fx.scoped(
            ps.subscribe().flat_map(lambda sub: _reader(sub, seen["b"]))
        ).fork()
        publisher = yield from fx.for_each(
            [1, 2, 3], lambda i: ps.publish(i).map(lambda ok: published.append(i) if ok else None)
        ).fork()
        waiter.set(
            (
                yield from ps.await_shutdown()
                .map(lambda _: shut_when_awaited.append(ps.is_shutdown_unsafe()))
                .fork()
            )
        )
        yield from fx.yield_now()
        yield from ps.shutdown()
        yield from publisher.await_exit()
        yield from reader.await_exit()
        yield from joiner.await_exit()
        yield from waiter.get().await_exit()

    w.fork(fx.scoped(body))
    interrupt_from_thread(w, "interrupter", waiter)

    def check() -> Problems:
        # A publish that registers after the shutdown flag is set, but before
        # the subscriptions close, may deliver and still be interrupted, as
        # Effect's ``BackPressureStrategy.handleSurplus`` does; so a reader
        # can see a message whose publish did not say ``True``.
        bad = {k: v for k, v in seen.items() if not _in_order(v) or not set(v) <= {1, 2, 3}}
        if bad or not _in_order(published):
            return f"published {published}, readers saw {seen}"
        if not all(shut_when_awaited):
            return "await_shutdown returned before the hub shut down"
        return None

    w.check(check)


# --- Semaphore ---------------------------------------------------------------------------


class _Permits:
    """Counts the permits held inside guarded sections: never more than
    ``limit``, nor more than the semaphore counts as taken."""

    def __init__(self, sem: Slot[fx.Semaphore], limit: int) -> None:
        self.sem = sem
        self.limit = limit
        self.inside = 0
        self.problems: list[str] = []

    def held(self, n: int) -> fx.Effect[None]:
        """Hold ``n`` permits' worth across a yield, counted in and out."""

        def enter() -> None:
            self.inside += n
            taken = self.sem.get()._taken
            if self.inside > min(self.limit, taken):
                self.problems.append(f"{self.inside} permits held, {taken} taken of {self.limit}")

        def leave() -> None:
            self.inside -= n

        return fx.scoped(
            scope.acquire_release(fx.sync(enter), lambda _, __: fx.sync(leave)).and_then(
                fx.yield_now()
            )
        )

    def check(self) -> Problems:
        sem = self.sem.get()
        problems = list(self.problems)
        if self.inside != 0 or sem._taken != 0:
            problems.append(f"{self.inside} still held inside, {sem._taken} permits still taken")
        return problems


def _semaphore_n(w: World) -> None:
    """Three permits: holders of two (``with_permits``), of two (``take`` and
    ``release``, interrupted from a thread) and of three (interrupted by a
    fiber, and overtaken by the smaller requests behind it). Never more than
    three held at once, and all come back."""
    sem = Slot[fx.Semaphore]()
    permits = _Permits(sem, 3)
    second = Slot[AnyFiber]()

    @fx.gen
    def main():
        s = sem.set((yield from fx.Semaphore.make(3)))
        first = yield from s.with_permits(permits.held(2), 2).fork()
        second.set(
            (
                yield from fx.uninterruptible_mask(
                    lambda restore: (
                        s.take(2).and_then(restore(permits.held(2))).ensuring(s.release(2))
                    )
                ).fork()
            )
        )
        third = yield from s.with_permits(permits.held(3), 3).fork()
        yield from fx.yield_now()
        yield from third.interrupt()
        yield from first.await_exit()
        yield from second.get().await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", second)
    w.check(permits.check)


def _semaphore_resize(w: World) -> None:
    """One permit, held across yields, with requests for one (interrupted by
    a fiber) and for two (interrupted from a thread) parked behind it; the
    semaphore grows to three, then shrinks to two. Nobody is inside without
    the permits taken, never more than three, the parked requests are woken
    by the growth, and all permits come back."""
    sem = Slot[fx.Semaphore]()
    permits = _Permits(sem, 3)  # the most it ever has
    big = Slot[AnyFiber]()

    @fx.gen
    def main():
        s = sem.set((yield from fx.Semaphore.make(1)))
        holder = yield from s.with_permits(permits.held(1).and_then(fx.yield_now())).fork()
        one = yield from s.with_permits(permits.held(1)).fork()
        big.set((yield from s.with_permits(permits.held(2), 2).fork()))
        yield from fx.yield_now()
        yield from s.resize(3)
        yield from fx.yield_now()
        yield from one.interrupt()
        yield from s.resize(2)
        yield from holder.await_exit()
        yield from big.get().await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", big)
    w.check(permits.check)


def _semaphore_release_all(w: World) -> None:
    """Two permits: one fiber takes both and gives them back with
    ``release_all``; ``with_permits`` holders (one interrupted by a fiber,
    one from a thread), a ``with_permits_if_available`` and a
    ``take_if_available`` compete. Never more than two held, an
    ``*_if_available`` succeeds only when the permit was free, and all
    permits come back."""
    sem = Slot[fx.Semaphore]()
    permits = _Permits(sem, 2)
    second = Slot[AnyFiber]()
    tried: list[str] = []

    @fx.gen
    def main():
        s = sem.set((yield from fx.Semaphore.make(2)))
        both = yield from fx.uninterruptible_mask(
            lambda restore: s.take(2).and_then(restore(permits.held(2))).and_then(s.release_all())
        ).fork()
        first = yield from s.with_permits(permits.held(1)).fork()
        second.set((yield from s.with_permits(permits.held(1)).fork()))
        maybe = (
            yield from s.with_permits_if_available(permits.held(1))
            .map(lambda got: tried.append("with" if got is not None else "-"))
            .fork()
        )
        took = (
            yield from fx.uninterruptible_mask(
                lambda restore: s.take_if_available().flat_map(
                    lambda ok: (
                        restore(permits.held(1)).ensuring(s.release()).as_("take")
                        if ok
                        else fx.succeed("-")
                    )
                )
            )
            .map(tried.append)
            .fork()
        )
        yield from fx.yield_now()
        yield from first.interrupt()
        yield from both.await_exit()
        yield from second.get().await_exit()
        yield from maybe.await_exit()
        yield from took.await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", second)
    w.check(permits.check)


def _semaphore_thread_release(w: World) -> None:
    """A fiber takes the only permit with ``take`` and never gives it back; a
    simulated thread releases it (``run_sync(release())``, its own run)
    while a ``with_permits`` waiter is parked and another is interrupted by
    a fiber. The parked waiter is woken through the scheduler, never two
    hold the permit at once, and it comes back."""
    sem = Slot[fx.Semaphore]()
    permits = _Permits(sem, 1)
    taken = Slot[bool]()

    @fx.gen
    def main():
        s = sem.set((yield from fx.Semaphore.make(1)))
        yield from s.take()
        taken.set(True)
        waiter = yield from s.with_permits(permits.held(1)).fork()
        other = yield from s.with_permits(permits.held(1)).fork()
        yield from fx.yield_now()
        yield from other.interrupt()
        yield from waiter.await_exit()

    w.fork(main)
    from_thread(w, "releaser", lambda: fx.run_sync(sem.get().release()), when=taken.is_set)
    w.check(permits.check)


# --- Latch -------------------------------------------------------------------------------


def _latch(w: World) -> None:
    """Waiters at a closed latch (one interrupted by a fiber, one in
    ``when_open`` interrupted from a thread) while a fiber releases it, opens
    it and closes it again; a waiter that arrives after the close is let
    through only by a simulated thread's ``open_unsafe``. Nobody passes a
    latch before it was released or opened, and every waiter ends."""
    events: list[str] = []
    latch = Slot[fx.Latch]()
    closed_again = Slot[bool]()
    second = Slot[AnyFiber]()

    def mark(event: str) -> fx.Effect[None]:
        return fx.sync(lambda: events.append(event))

    @fx.gen
    def main():
        lt = latch.set((yield from fx.Latch.make()))
        first = yield from lt.wait().and_then(mark("pass first")).fork()
        second.set((yield from lt.when_open(mark("pass second")).fork()))
        third = yield from lt.wait().and_then(mark("pass third")).fork()
        yield from fx.yield_now()
        yield from first.interrupt()
        yield from mark("release").and_then(lt.release())
        yield from fx.yield_now()
        yield from mark("open").and_then(lt.open())
        yield from third.await_exit()
        yield from second.get().await_exit()
        yield from lt.close()
        late = yield from lt.wait().and_then(mark("pass late")).fork()
        closed_again.set(True)
        yield from late.await_exit()

    def opener() -> ThreadBody:
        yield closed_again.is_set
        events.append("open again")
        latch.get().open_unsafe()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", second)
    w.thread("opener", opener)

    def check() -> Problems:
        for i, event in enumerate(events):
            if not event.startswith("pass"):
                continue
            before = events[:i]
            needed = "open again" if event == "pass late" else "release"
            if needed not in before:
                return f"{event} before the latch let it through: {events}"
        if "pass late" not in events or "pass third" not in events:
            return f"a waiter never passed the open latch: {events}"
        return None

    w.check(check)


# --- Ref, SynchronizedRef, SubscriptionRef ----------------------------------------------


def _ref_modify(w: World) -> None:
    """Three fibers each ``get_and_update`` a Ref twice (one interrupted by
    a fiber, one from a thread). Each update is atomic and its decided
    result reaches the continuation: the old values seen are exactly
    ``0 .. final - 1``, none twice."""
    olds: list[int] = []
    ref = Slot[fx.Ref[int]]()
    second = Slot[AnyFiber]()

    def bump(r: fx.Ref[int]) -> fx.Effect[None]:
        once = r.get_and_update(lambda v: v + 1).map(olds.append)
        return once.and_then(once)

    @fx.gen
    def main():
        r = ref.set((yield from fx.Ref.make(0)))
        first = yield from bump(r).fork()
        second.set((yield from bump(r).fork()))
        third = yield from r.modify(lambda v: (v, v + 1)).map(olds.append).fork()
        yield from first.interrupt()
        yield from second.get().await_exit()
        yield from third.await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", second)

    def check() -> Problems:
        final = ref.get().get_unsafe()
        if sorted(olds) != list(range(final)):
            return f"saw old values {olds}, final value {final}"
        return None

    w.check(check)


def _synchronized_ref(w: World) -> None:
    """Two ``update_effect`` calls and a ``modify_effect`` on a
    SynchronizedRef, each yielding before it stores, plus a plain
    ``update``; one effectful update is interrupted by a fiber, one from a
    thread, at any point of its update.
    Updates take turns: each name lands at most once, and every update that
    succeeded is in the final value (none lost to a concurrent one)."""
    succeeded: list[str] = []
    ref = Slot[fx.SynchronizedRef[tuple[str, ...]]]()
    second = Slot[AnyFiber]()

    def add(r: fx.SynchronizedRef[tuple[str, ...]], name: str) -> fx.Effect[None]:
        update = r.update_effect(lambda v: fx.yield_now().as_((*v, name)))
        return update.map(lambda _: succeeded.append(name))

    @fx.gen
    def main():
        r = ref.set((yield from fx.SynchronizedRef[tuple[str, ...]].make(())))
        first = yield from add(r, "first").fork()
        second.set((yield from add(r, "second").fork()))
        third = (
            yield from r.modify_effect(lambda v: fx.yield_now().as_(("third", (*v, "third"))))
            .map(succeeded.append)
            .fork()
        )
        plain = (
            yield from r.update(lambda v: (*v, "plain"))
            .map(lambda _: succeeded.append("plain"))
            .fork()
        )
        yield from fx.yield_now()
        yield from first.interrupt()
        yield from second.get().await_exit()
        yield from third.await_exit()
        yield from plain.await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", second)

    def check() -> Problems:
        final = ref.get().get_unsafe()
        if len(set(final)) != len(final) or not set(succeeded) <= set(final):
            return f"succeeded {succeeded}, final value {final}"
        if ref.get()._lock._taken != 0:
            return f"the ref's lock is still taken after {succeeded}"
        return None

    w.check(check)


def _subscription_ref(w: World) -> None:
    """A SubscriptionRef: a subscriber joins while two fibers increment it
    (one ``update_effect`` interrupted from a thread mid-update), and a
    ``changes()`` stream is interrupted by a fiber; then the value is set to
    -1. Each sees the current value, then every later one, in order, no
    gaps or repeats, ending with -1."""
    seen: list[int] = []
    streamed: list[list[int]] = []
    last = Slot[int]()
    slow = Slot[AnyFiber]()

    @fx.gen
    def main():
        r = yield from fx.SubscriptionRef.make(0)
        subscriber = yield from fx.scoped(
            r.subscribe().flat_map(lambda sub: _reader(sub, seen, until=-1))
        ).fork()
        stream = (
            yield from r.changes()
            .take_until(lambda v: v < 0)
            .run_collect()
            .map(streamed.append)
            .fork()
        )
        quick = yield from r.update(lambda v: v + 1).fork()
        slow.set((yield from r.update_effect(lambda v: fx.yield_now().as_(v + 1)).fork()))
        yield from fx.yield_now()
        yield from stream.interrupt()
        yield from quick.await_exit()
        yield from slow.get().await_exit()
        last.set((yield from r.get()))
        yield from r.set(-1)
        yield from subscriber.await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", slow)

    def check() -> Problems:
        for got in [seen, *streamed]:
            values = got[:-1]
            # Subscribed after the -1, it sees only that.
            start = values[0] if values else last.get() + 1
            if got[-1:] != [-1] or values != list(range(start, last.get() + 1)):
                return f"saw {got}, the last value before -1 was {last.get()}"
        return None

    w.check(check)


# --- Deferred ------------------------------------------------------------------------------


def _deferred_race(w: World) -> None:
    """A fiber's ``succeed``, a fiber's ``complete`` of an effect that
    yields, a fiber's ``complete_with`` and a simulated thread's
    ``done_unsafe`` race to complete a Deferred, with three waiters (one
    interrupted by a fiber, one from a thread). Exactly one completion says
    ``True``, and every waiter that succeeds sees its value."""
    won: list[int] = []
    seen: list[int] = []
    deferred = Slot[fx.Deferred[int]]()
    second = Slot[AnyFiber]()

    def note(value: int) -> Callable[[bool], None]:
        return lambda ok: won.append(value) if ok else None

    @fx.gen
    def main():
        d = deferred.set((yield from fx.Deferred[int].make()))
        first = yield from d.wait().map(seen.append).fork()
        second.set((yield from d.wait().map(seen.append).fork()))
        third = yield from d.wait().map(seen.append).fork()
        ones = yield from d.succeed(1).map(note(1)).fork()
        twos = yield from d.complete(fx.yield_now().as_(2)).map(note(2)).fork()
        fours = yield from d.complete_with(fx.succeed(4)).map(note(4)).fork()
        yield from first.interrupt()
        yield from ones.await_exit()
        yield from twos.await_exit()
        yield from fours.await_exit()
        yield from second.get().await_exit()
        yield from third.await_exit()

    def completer() -> ThreadBody:
        yield deferred.is_set
        if deferred.get().done_unsafe(Success(3)):
            won.append(3)

    w.fork(main)
    interrupt_from_thread(w, "interrupter", second)
    w.thread("completer", completer)

    def check() -> Problems:
        if len(won) != 1 or any(v != won[0] for v in seen) or not seen:
            return f"completions that won {won}, waiters saw {seen}"
        return None

    w.check(check)


# --- References ----------------------------------------------------------------------------


class _Level(fx.Reference[int]):
    @classmethod
    def default(cls) -> int:
        return 0


def _reference(w: World) -> None:
    """A Reference provided as 1 around a parent: a child reads it after a
    yield and after a resume from a simulated thread, then provides 2 for a
    region of its own; a child forked inside an ``update_service_scoped``
    region (5) reads after the region closed; a child inside a region of 3
    is interrupted from a thread, another by a fiber. A child sees its
    parent's value at fork time, its own regions never leak to the parent
    or out of the region, and finalizers see the value of where they were
    added."""
    reads: list[tuple[str, int]] = []
    parked = Slot[Callable[[fx.Effect[None]], None]]()
    victim = Slot[AnyFiber]()

    def read(name: str) -> fx.Effect[None]:
        return _Level().map(lambda v: reads.append((name, v)))

    def park(resume: Callable[[fx.Effect[None]], None]) -> None:
        parked.set(resume)

    @fx.gen
    def child():
        yield from fx.yield_now()
        yield from read("child after yield")
        yield from fx.callback(park)
        yield from read("child after resume")
        yield from fx.yield_now().and_then(read("child region")).pipe(fx.provide_service(_Level, 2))
        yield from read("child after region")

    def interrupted(name: str) -> fx.Effect[None]:
        inner = fx.never.ensuring(read(f"{name} inner")).pipe(fx.provide_service(_Level, 3))
        return inner.ensuring(read(f"{name} outer"))

    @fx.gen
    def body():
        yield from read("parent")
        kid = yield from child.fork()
        grandchild = yield from fx.scoped(
            fx.update_service_scoped(_Level, lambda v: v + 4).and_then(
                fx.yield_now().and_then(read("scoped child")).fork()
            )
        )
        yield from read("parent after scope")
        victim.set((yield from interrupted("thread victim").fork()))
        other = yield from interrupted("fiber victim").fork()
        yield from fx.yield_now()
        yield from other.interrupt()
        yield from kid.join()
        yield from grandchild.join()
        yield from victim.get().await_exit()
        yield from read("parent at end")

    w.fork(body.pipe(fx.provide_service(_Level, 1)))
    interrupt_from_thread(w, "interrupter", victim)
    from_thread(w, "resumer", lambda: parked.get()(fx.void), when=parked.is_set)

    expected = {
        "parent": 1,
        "child after yield": 1,
        "child after resume": 1,
        "child region": 2,
        "child after region": 1,
        "scoped child": 5,
        "parent after scope": 1,
        "thread victim inner": 3,
        "thread victim outer": 1,
        "fiber victim inner": 3,
        "fiber victim outer": 1,
        "parent at end": 1,
    }

    def check() -> Problems:
        wrong = [(name, v, expected[name]) for name, v in reads if v != expected[name]]
        if wrong:
            return f"read (name, value, expected): {wrong}"
        missing = {"parent at end", "child after region", "scoped child"} - {n for n, _ in reads}
        return f"never read {missing}: {reads}" if missing else None

    w.check(check)


SCENARIOS: list[Scenario] = [
    Scenario("queue_sliding", _queue_sliding, runs=1000),
    Scenario("queue_dropping", _queue_dropping, runs=1000),
    Scenario("queue_batches", _queue_batches, runs=1000),
    Scenario("queue_offer_all_parked", _queue_offer_all_parked, runs=1000),
    Scenario("queue_end_await", _queue_end_await, runs=1000),
    Scenario("queue_end_vs_shutdown", _queue_end_vs_shutdown, runs=1000),
    Scenario("queue_external_producer", _queue_external_producer, runs=1000),
    Scenario("pubsub_sliding", _pubsub_sliding, runs=600),
    Scenario("pubsub_dropping_unsafe", _pubsub_dropping_unsafe, runs=600),
    Scenario("pubsub_replay", _pubsub_replay, runs=600),
    Scenario("pubsub_shutdown_race", _pubsub_shutdown_race, runs=600),
    Scenario("semaphore_n", _semaphore_n, runs=600),
    Scenario("semaphore_resize", _semaphore_resize, runs=600),
    Scenario("semaphore_release_all", _semaphore_release_all, runs=600),
    Scenario("semaphore_thread_release", _semaphore_thread_release, runs=1000),
    Scenario("latch", _latch, runs=1000),
    Scenario("ref_modify", _ref_modify, runs=1000),
    Scenario("synchronized_ref", _synchronized_ref, runs=600),
    Scenario("subscription_ref", _subscription_ref, runs=600),
    Scenario("deferred_race", _deferred_race, runs=1000),
    Scenario("reference", _reference, runs=600),
]
