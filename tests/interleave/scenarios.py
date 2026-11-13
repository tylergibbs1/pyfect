"""The runtime scenarios the interleaving harness explores (README.md).

Each one is small on purpose, so the bounded search covers most of its
schedules. Interrupts come both from a fiber (delivered at once) and from a
simulated thread (through the scheduler), at whatever point the schedule
puts them. What each checks comes from CLAUDE.md's runtime rules: a decided
result is seen by its continuation or released, finalizers run once, every
fiber ends once (the harness checks that for every fiber), and nothing
parks forever where Effect would go on.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import contextvars
from collections.abc import Callable
from typing import Any, Never

import pyfect as fx
from pyfect import layer, scope
from pyfect.exit import Exit, Success
from pyfect.exit import void as exit_void
from pyfect.testing import TestClock, adjust

from . import scenarios_fibers, scenarios_resources, scenarios_streams, scenarios_sync
from ._harness import Problems, Scenario, ThreadBody, World
from ._kit import AnyFiber, Slot, balanced, interrupt_from_thread, resource

# --- Queue -----------------------------------------------------------------------------


def _queue_take_interrupt(w: World) -> None:
    """Two takers and an offerer on a queue of one; one taker is interrupted
    by a fiber, the other from a thread. Every offer that said ``True`` is
    either seen by a taker's continuation or still in the queue."""
    taken: list[int] = []
    offered: list[int] = []
    queue = Slot[fx.Queue[int]]()
    second = Slot[AnyFiber]()

    def offer(q: fx.Queue[int], i: int) -> fx.Effect[None]:
        return q.offer(i).map(lambda ok: offered.append(i) if ok else None)

    @fx.gen
    def main():
        q = queue.set((yield from fx.Queue[int].bounded(1)))
        first = yield from q.take().map(taken.append).fork()
        second.set((yield from q.take().map(taken.append).fork()))
        offers = yield from fx.for_each([1, 2, 3], lambda i: offer(q, i)).fork()
        yield from fx.yield_now()
        yield from first.interrupt()
        yield from second.get().await_exit()
        yield from offers.interrupt()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", second)

    def check() -> Problems:
        left = queue.get().size_unsafe()
        if len(set(taken)) != len(taken) or len(taken) + left != len(offered):
            return f"offered {offered}, taken {taken}, {left} left in the queue"
        return None

    w.check(check)


def _queue_shutdown(w: World) -> None:
    """A shutdown races a taker (also interrupted from a thread) and an
    offerer: both end, and the taker saw offered items in order, once."""
    taken: list[int] = []
    offered: list[int] = []
    taker = Slot[AnyFiber]()

    @fx.gen
    def main():
        q = yield from fx.Queue[int].bounded(1)
        taker.set((yield from fx.for_each(range(2), lambda _: q.take().map(taken.append)).fork()))

        def offer(i: int) -> fx.Effect[None]:
            return q.offer(i).map(lambda ok: offered.append(i) if ok else None)

        offers = yield from fx.for_each([1, 2, 3], offer).fork()
        yield from fx.yield_now()
        yield from q.shutdown()
        yield from taker.get().await_exit()
        yield from offers.await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", taker)

    def check() -> Problems:
        if taken != sorted(set(taken)) or not set(taken) <= set(offered):
            return f"offered {offered}, taken {taken}"
        return None

    w.check(check)


# --- Semaphore ---------------------------------------------------------------------------


def _semaphore(w: World) -> None:
    """Three holders of a one-permit semaphore (``with_permits``,
    ``take_scoped``, and ``take`` + ``release``), two interrupted: never two
    inside at once, and the permit always comes back."""
    inside = [0, 0]  # now, most at once
    sem = Slot[fx.Semaphore]()
    second = Slot[AnyFiber]()

    def enter() -> None:
        inside[0] += 1
        inside[1] = max(inside)

    def leave() -> None:
        inside[0] -= 1

    held = fx.scoped(
        scope.acquire_release(fx.sync(enter), lambda _, __: fx.sync(leave)).and_then(fx.yield_now())
    )

    @fx.gen
    def main():
        s = sem.set((yield from fx.Semaphore.make(1)))
        first = yield from s.with_permits(held).fork()
        second.set((yield from fx.scoped(s.take_scoped().and_then(held)).fork()))
        third = yield from fx.uninterruptible_mask(
            lambda restore: s.take().and_then(restore(held)).ensuring(s.release())
        ).fork()
        yield from fx.yield_now()
        yield from first.interrupt()
        yield from second.get().await_exit()
        yield from third.await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", second)

    def check() -> Problems:
        free = sem.get()._free
        if inside[1] > 1 or inside[0] != 0 or free != 1:
            return f"at most {inside[1]} inside, {inside[0]} left inside, {free} permits free"
        return None

    w.check(check)


# --- Deferred ------------------------------------------------------------------------------


def _deferred(w: World) -> None:
    """Two waiters on a Deferred a fiber completes, one interrupted by a
    fiber and one from a thread; and a ``complete(eff)`` whose fiber is
    interrupted while ``eff`` sleeps. A waiter ends with the value or
    interrupted, and sees the value only if it succeeded."""
    seen: list[tuple[str, int]] = []
    exits: dict[str, Exit[Any, Any]] = {}
    second = Slot[AnyFiber]()
    lazy = Slot[fx.Deferred[int]]()

    def waiter(d: fx.Deferred[int], name: str) -> fx.Effect[None]:
        return (
            d.wait()
            .map(lambda v: seen.append((name, v)))
            .on_exit(lambda ex: fx.sync(lambda: exits.__setitem__(name, ex)))
        )

    @fx.gen
    def main():
        d = yield from fx.Deferred[int].make()
        first = yield from waiter(d, "first").fork()
        second.set((yield from waiter(d, "second").fork()))
        completer = yield from fx.yield_now().and_then(d.succeed(7)).fork()
        later = lazy.set((yield from fx.Deferred[int].make()))
        third = yield from waiter(later, "third").fork()
        running = yield from later.complete(fx.sleep("1 second").as_(5)).fork()
        yield from fx.yield_now()
        yield from first.interrupt()
        yield from running.interrupt()
        yield from completer.await_exit()
        yield from second.get().await_exit()
        if not later.is_done_unsafe():  # interrupted before ``complete`` ran
            yield from third.interrupt()
        yield from third.await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", second)

    def check() -> Problems:
        succeeded = sorted(name for name, ex in exits.items() if isinstance(ex, Success))
        if sorted(name for name, _ in seen) != succeeded:
            return f"seen {seen}, exits {exits}"
        wrong = [(n, v) for n, v in seen if v != {"first": 7, "second": 7, "third": 5}[n]]
        return f"wrong values {wrong}" if wrong else None

    w.check(check)


# --- Fiber join / interrupt ----------------------------------------------------------------


def _join_interrupt(w: World) -> None:
    """A fiber holding a resource is joined by one fiber and interrupted by
    another and by a thread: its finalizer runs once, and the joiner gets
    exactly its exit."""
    holder = Slot[AnyFiber]()
    joined: list[Exit[Any, Any]] = []

    @fx.gen
    def main():
        h = holder.set((yield from fx.scoped(resource(w, "r").and_then(fx.never)).fork()))
        joiner = yield from h.await_exit().map(joined.append).fork()
        yield from fx.yield_now()
        yield from h.interrupt()
        yield from joiner.await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", holder)
    w.check(balanced(w, "r"))

    def check() -> Problems:
        if len(joined) != 1 or joined[0] is not holder.get()._exit:
            return f"the joiner saw {joined}, the fiber ended with {holder.get()._exit}"
        return None

    w.check(check)


# --- race / race_all ---------------------------------------------------------------------


def _side(w: World, name: str, delay: str) -> fx.Effect[str]:
    return fx.scoped(resource(w, name).and_then(fx.sleep(delay))).as_(name)


def _race(w: World) -> None:
    """Two racers that finish at the same instant (the schedule picks which
    timer fires first), and a race_all of three where one fails; one race is
    also interrupted from a thread. One winner each, losers released."""
    won: list[str] = []
    racing = Slot[AnyFiber]()

    @fx.gen
    def main():
        pair = _side(w, "a", "1 second").race(_side(w, "b", "1 second")).map(won.append)
        racing.set((yield from pair.fork()))
        failing = fx.sleep("1 second").and_then(fx.fail("no"))
        three = fx.race_all(failing, _side(w, "c", "2 seconds"), _side(w, "d", "1 second"))
        all_of = yield from three.map(won.append).fork()
        yield from racing.get().await_exit()
        yield from all_of.await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", racing)
    w.check(balanced(w, "a", "b", "c", "d"))

    def check() -> Problems:
        # ``d`` sleeps less than ``c``, but its sleep may start late (a
        # fiber can be slow to get there), so either may win.
        pair = [x for x in won if x in "ab"]
        rest = [x for x in won if x in "cd"]
        if len(pair) > 1 or len(rest) != 1:
            return f"winners {won}"
        if isinstance(racing.get()._exit, Success) != (len(pair) == 1):
            return f"the pair race ended with {racing.get()._exit} but recorded {pair}"
        return None

    w.check(check)


# --- for_each with concurrency -----------------------------------------------------------


def _for_each(w: World) -> None:
    """Four items, two at a time, each holding a resource across a yield;
    the whole is interrupted from a thread. Every resource is released once,
    and a success means every item ran."""
    each = Slot[AnyFiber]()
    names = [str(i) for i in range(4)]

    def item(name: str) -> fx.Effect[str]:
        return fx.scoped(resource(w, name).and_then(fx.yield_now())).as_(name)

    @fx.gen
    def main():
        each.set((yield from fx.for_each(names, item, concurrency=2).fork()))
        yield from each.get().await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", each)
    w.check(balanced(w, *names))

    def check() -> Problems:
        ex = each.get()._exit
        if isinstance(ex, Success) and ex.value != names:
            return f"for_each succeeded with {ex.value}"
        if isinstance(ex, Success) and any(w.counts[f"acquire {n}"] != 1 for n in names):
            return f"for_each succeeded, but acquired {dict(w.counts)}"
        return None

    w.check(check)


# --- Pool ----------------------------------------------------------------------------------


def _pool(w: World) -> None:
    """A pool of one: a borrower invalidates its item, another (interrupted
    from a thread) waits for one. Every item acquired is released once, by
    the time the pool's scope has closed."""
    made: list[int] = []
    borrower = Slot[AnyFiber]()

    def acquire() -> fx.Effect[int, Never, scope.Scope]:
        def make() -> int:
            made.append(len(made))
            return made[-1]

        return scope.acquire_release(
            fx.sync(make).tap(lambda i: w.bump(f"acquire {i}")),
            lambda i, _: w.bump(f"release {i}"),
        )

    @fx.gen
    def in_scope():
        pool = yield from fx.Pool.make(acquire(), size=1)
        invalidator = yield from fx.scoped(
            pool.get().flat_map(lambda item: pool.invalidate(item).and_then(fx.yield_now()))
        ).fork()
        borrower.set((yield from fx.scoped(pool.get()).fork()))
        yield from invalidator.await_exit()
        yield from borrower.get().await_exit()

    w.fork(fx.scoped(in_scope))
    interrupt_from_thread(w, "interrupter", borrower)

    def check() -> Problems:
        return balanced(w, *(str(i) for i in made))()

    w.check(check)


# --- PubSub ----------------------------------------------------------------------------------


def _pubsub(w: World) -> None:
    """A subscriber takes two messages and unsubscribes while a publisher
    publishes three into a PubSub of one; the subscriber is also interrupted
    from a thread. It sees messages in order, once each, and the publisher
    is never left waiting for a subscriber that has gone."""
    seen: list[int] = []
    subscriber = Slot[AnyFiber]()

    @fx.gen
    def main():
        ps = yield from fx.PubSub[int].bounded(1)

        def take_two(sub: Any) -> fx.Effect[Any]:
            return fx.for_each(range(2), lambda _: sub.take().map(seen.append))

        subscriber.set((yield from fx.scoped(ps.subscribe().flat_map(take_two)).fork()))
        publisher = yield from fx.for_each([1, 2, 3], ps.publish).fork()
        yield from subscriber.get().await_exit()
        yield from publisher.await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", subscriber)

    def check() -> Problems:
        if seen != sorted(set(seen)) or not set(seen) <= {1, 2, 3}:
            return f"the subscriber saw {seen}"
        return None

    w.check(check)


# --- Scope close racing a fork -----------------------------------------------------------


def _scope_close_fork(w: World) -> None:
    """One fiber forks a resource holder into a scope while another closes
    it: the holder is interrupted (or never starts), and its resource, if
    acquired, is released once."""
    child = Slot[AnyFiber]()

    @fx.gen
    def main():
        sc = yield from scope.make()
        forker = (
            yield from scope.fork_in(fx.scoped(resource(w, "r").and_then(fx.never)), sc)
            .map(child.set)
            .fork()
        )
        closer = yield from fx.yield_now().and_then(sc.close(exit_void)).fork()
        yield from forker.await_exit()
        yield from closer.await_exit()
        yield from child.get().await_exit()

    w.fork(main)
    w.check(balanced(w, "r"))


# --- TestClock ---------------------------------------------------------------------------------


def _test_clock(w: World) -> None:
    """Sleepers at 1 and 2 seconds and an ``adjust`` of 2 seconds; one
    sleeper is interrupted from a thread. ``adjust`` returns only after every
    due sleeper has woken and run, in time order."""
    woke: list[tuple[str, float]] = []
    third = Slot[AnyFiber]()

    def sleeper(name: str, delay: str) -> fx.Effect[None]:
        stamp = fx.clock.current_time_millis().map(lambda t: woke.append((name, t)))
        return fx.sleep(delay).and_then(stamp)

    @fx.gen
    def main():
        first = yield from sleeper("1s", "1 second").fork()
        second = yield from sleeper("2s", "2 seconds").fork()
        third.set((yield from sleeper("1s again", "1 second").fork()))
        yield from adjust("2 seconds")
        woke.append(("adjusted", -1))
        yield from first.await_exit()
        yield from second.await_exit()
        yield from third.get().await_exit()

    w.fork(main.pipe(fx.provide(TestClock.layer())))
    interrupt_from_thread(w, "interrupter", third)

    def check() -> Problems:
        names = [n for n, _ in woke]
        expected = ["1s", "1s again", "2s", "adjusted"]
        if [n for n in names if n != "1s again"] != ["1s", "2s", "adjusted"]:
            return f"woke {woke}"
        if names not in (
            expected,
            ["1s again", "1s", "2s", "adjusted"],
            [*expected[:1], *expected[2:]],
        ):
            return f"woke {woke}"
        times = {n: t for n, t in woke}
        if times["1s"] != 1000 or times["2s"] != 2000:
            return f"woke {woke}"
        return None

    w.check(check)


# --- ManagedRuntime from threads ---------------------------------------------------------------

request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class Greeting(fx.Tag[str]): ...


def _managed_runtime(w: World) -> None:
    """Simulated threads start runs on one ManagedRuntime (``run_fork``,
    ``run_callback``, ``run_blocking``, which drives its scheduler), another
    runs ``run_sync`` and then disposes it while they may still run. The layer is built
    once and released once, and each run reads its own caller's
    ``contextvars``."""
    built = layer.effect(Greeting, resource(w, "layer").as_("hi"))
    runtime = fx.ManagedRuntime.make(built)
    runtime._run_scheduler = lambda: w.scheduler
    runtime._fork_outside_runs = w.scheduler
    reads: list[tuple[str, str]] = []
    started = Slot[AnyFiber]()

    def read(caller: str) -> fx.Effect[None, Never, Greeting]:
        record = fx.sync(lambda: reads.append((caller, request_id.get())))
        return record.and_then(fx.yield_now()).and_then(Greeting()).and_then(record)

    def forking() -> ThreadBody:
        request_id.set("fork")
        started.set(runtime.run_fork(w.budgeted(read("fork"))))
        yield

    def calling_back() -> ThreadBody:
        request_id.set("callback")
        runtime.run_callback(w.budgeted(read("callback")))
        yield

    def blocking() -> ThreadBody:
        request_id.set("blocking")
        yield
        # Dies once the runtime is disposed; either way it drives the scheduler.
        runtime.run_blocking_exit(w.budgeted(read("blocking")))

    def disposing() -> ThreadBody:
        request_id.set("sync")
        yield lambda: started.value is not None
        runtime.run_sync(fx.sync(lambda: reads.append(("sync", request_id.get()))))
        yield
        runtime.dispose()

    w.thread("fork", forking)
    w.thread("callback", calling_back)
    w.thread("blocking", blocking)
    w.thread("dispose", disposing)
    w.check(balanced(w, "layer"))

    def check() -> Problems:
        wrong = [(caller, seen) for caller, seen in reads if caller != seen]
        if wrong:
            return f"runs read another caller's context: {wrong}"
        if w.counts["acquire layer"] != 1:
            return f"the layer was built {w.counts['acquire layer']} times"
        return None

    w.check(check)


# --- resumes and interrupts from other threads -----------------------------------------------


def _cross_thread_resume(w: World) -> None:
    """A fiber parks on a callback; two simulated threads resume it (with 1
    and with 2) and a third interrupts it. Only the first resume counts, and
    a resume sent before the interrupt is seen by the fiber's continuation,
    as Effect runs a resume at once (the interrupt then lands after it)."""
    events: list[str] = []
    seen: list[int] = []
    parked = Slot[Callable[[fx.Effect[int]], None]]()
    waiter = Slot[AnyFiber]()

    def park(resume: Callable[[fx.Effect[int]], None]) -> None:
        parked.set(resume)

    waiter.set(
        w.fork(fx.callback(park).map(seen.append).and_then(fx.yield_now()), must_succeed=False)
    )

    def resumer(value: int) -> Callable[[], ThreadBody]:
        def body() -> ThreadBody:
            yield lambda: parked.value is not None or waiter.get().poll_unsafe() is not None
            if parked.value is not None:  # else interrupted before it parked
                events.append(f"resume {value}")
                parked.get()(fx.succeed(value))

        return body

    def interrupter() -> ThreadBody:
        yield
        events.append("interrupt")
        waiter.get().interrupt_as_unsafe(None)

    w.thread("resume 1", resumer(1))
    w.thread("resume 2", resumer(2))
    w.thread("interrupter", interrupter)

    def check() -> Problems:
        # An interrupt sent from another thread is delivered later, on the
        # fiber's thread, so a resume sent after it may still win; one sent
        # before it always does.
        resumes = [e for e in events if e.startswith("resume")]
        if events and events[0].startswith("resume") and seen != [int(events[0].split()[1])]:
            return f"events {events}, the fiber saw {seen}"
        if len(seen) > 1 or (seen and f"resume {seen[0]}" != resumes[0]):
            return f"events {events}, the fiber saw {seen}"
        return None

    w.check(check)


# --- contextvars ---------------------------------------------------------------------------------


def _contextvars(w: World) -> None:
    """Two simulated threads, each with its own request id, start a run on
    a shared scheduler (``fx.run_fork(..., scheduler=...)``). Each run reads
    the id at its first step, after a yield, in a forked child (scheduled,
    not started at once), and after a resume sent from a third thread with
    an id of its own. Every read is its own caller's id (the 0.5.4 fix: a
    first run that is scheduled used to take the context of whatever drained
    the scheduler)."""
    request_id.set("driver")
    reads: list[tuple[str, str]] = []
    parked: list[Callable[[fx.Effect[None]], None]] = []

    def read(caller: str) -> fx.Effect[None]:
        return fx.sync(lambda: reads.append((caller, request_id.get())))

    def park(resume: Callable[[fx.Effect[None]], None]) -> None:
        parked.append(resume)

    def program(caller: str) -> fx.Effect[None]:
        @fx.gen
        def body():
            yield from read(caller)
            yield from fx.yield_now()
            yield from read(caller)
            child = yield from read(caller).fork()
            yield from child.join()
            yield from fx.callback(park)
            yield from read(caller)

        return body

    def starter(caller: str) -> Callable[[], ThreadBody]:
        def body() -> ThreadBody:
            request_id.set(caller)
            fx.run_fork(w.budgeted(program(caller)), scheduler=w.scheduler)
            yield

        return body

    def resumer() -> ThreadBody:
        request_id.set("resumer")
        for _ in range(2):
            yield lambda: bool(parked)
            parked.pop(0)(fx.void)

    w.thread("a", starter("a"))
    w.thread("b", starter("b"))
    w.thread("resumer", resumer)

    def check() -> Problems:
        wrong = [(caller, seen) for caller, seen in reads if caller != seen]
        if wrong:
            return f"runs read another context: {wrong}"
        if len(reads) != 8:
            return f"expected 8 reads, got {reads}"
        return None

    w.check(check)


BASE = [
    Scenario("queue_take_interrupt", _queue_take_interrupt),
    Scenario("queue_shutdown", _queue_shutdown),
    Scenario("semaphore", _semaphore),
    Scenario("deferred", _deferred),
    Scenario("join_interrupt", _join_interrupt),
    Scenario("race", _race),
    Scenario("for_each", _for_each),
    Scenario("pool", _pool, runs=1000),
    Scenario("pubsub", _pubsub),
    Scenario("scope_close_fork", _scope_close_fork),
    # A sleeper's fork must run before ``adjust`` moves time, as the real
    # (FIFO) schedulers guarantee; time is virtual, so its timers wait for idle.
    Scenario("test_clock", _test_clock, order="fifo", timers="when_idle"),
    Scenario("managed_runtime", _managed_runtime),
    Scenario("contextvars", _contextvars),
    Scenario("cross_thread_resume", _cross_thread_resume),
]
# The primitives' own scenarios, one module per family.
ALL_BASE = [
    *BASE,
    *scenarios_sync.SCENARIOS,
    *scenarios_resources.SCENARIOS,
    *scenarios_fibers.SCENARIOS,
    *scenarios_streams.SCENARIOS,
]
# Each also runs with every step a possible pause (as tests/test_decided_results.py
# sweeps), where most interleavings live.
SCENARIOS = [variant for base in ALL_BASE for variant in (base, base.with_ops(1), base.with_ops(3))]
BY_NAME = {s.name: s for s in SCENARIOS}
