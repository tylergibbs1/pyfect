"""Interleaving scenarios for FiberSet, FiberMap, FiberHandle, timeout,
concurrent zip and all, for_each, races, Schedule retry / repeat and the
fiber primitives (README.md)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never

import pyfect as fx
from pyfect import schedule, scope
from pyfect.cause import Cause, Fail, Interrupt
from pyfect.errors import TimeoutException
from pyfect.exit import Exit, Failure, Success
from pyfect.exit import void as exit_void
from pyfect.option import Some
from pyfect.testing import TestClock, adjust, test_clock

from ._harness import Problems, Scenario, ThreadBody, World
from ._kit import AnyFiber, Slot, balanced, interrupt_from_thread, resource

# --- shared --------------------------------------------------------------------------------


def _holder(w: World, name: str) -> fx.Effect[Never]:
    """Holds a counted resource until interrupted."""
    return fx.scoped(resource(w, name).and_then(fx.never))


def _exit_of(fiber: Slot[AnyFiber]) -> Exit[Any, Any] | None:
    return fiber.get()._exit if fiber.is_set() else None


def _interrupted_only(ex: Exit[Any, Any] | None) -> bool:
    return isinstance(ex, Failure) and ex.cause.has_interrupts_only


def _timed_out(ex: Exit[Any, Any] | None) -> bool:
    if not isinstance(ex, Failure):
        return False
    found = ex.cause.find_fail()
    return isinstance(found, Fail) and isinstance(found.error, TimeoutException)


def _reasons(cause: Cause[Any]) -> list[object]:
    """The reasons, with interrupts reduced to who sent them."""
    return [("interrupt", r.fiber_id) if isinstance(r, Interrupt) else r for r in cause.reasons]


# --- FiberSet --------------------------------------------------------------------------------


def _fiber_set_scope_close(w: World) -> None:
    """Two members holding resources (one started at once, one on the next
    turn), one interrupted from a thread, then the set's scope closes while
    they run. Every member ends, each resource is released once, the set is
    empty and closed afterwards, its ``join`` succeeds, and a run into the
    closed set gives an interrupted fiber that never runs its effect."""
    fibers = Slot[fx.FiberSet[None, Never]]()
    second = Slot[AnyFiber]()
    late = Slot[AnyFiber]()
    joined: list[Exit[None, Never]] = []

    @fx.gen
    def in_scope():
        s = fibers.set((yield from fx.FiberSet[None, Never].make()))
        yield from s.run(_holder(w, "a"))
        second.set((yield from s.run(_holder(w, "b"), start_immediately=False)))
        yield from s.join().exit().map(joined.append).fork_daemon()
        yield from fx.yield_now()

    @fx.gen
    def main():
        yield from fx.scoped(in_scope)
        late.set((yield from fibers.get().run(_holder(w, "late"))))
        yield from late.get().await_exit()
        yield from fx.yield_now()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", second)
    w.check(balanced(w, "a", "b"))

    def check() -> Problems:
        problems: list[str] = []
        s = fibers.get()
        if list(s) or s._fibers is not None:
            problems.append(f"the set is {s!r} after its scope closed")
        if w.counts["acquire late"] or not _interrupted_only(_exit_of(late)):
            problems.append(f"a run into the closed set ran, or ended {_exit_of(late)}")
        if joined and not isinstance(joined[0], Success):
            problems.append(f"join after closing gave {joined}")
        return problems

    w.check(check)


def _fiber_set_close_while_starting(start_immediately: bool) -> Callable[[World], None]:
    def build(w: World) -> None:
        """One fiber runs a resource holder into a set while another closes
        the set's scope, and a thread interrupts the runner. The holder
        either never ran or is interrupted, its resource released once, and
        the fiber ``run`` gave back always ends."""
        started = Slot[AnyFiber]()
        runner = Slot[AnyFiber]()

        @fx.gen
        def main():
            sc = yield from scope.make()
            s = yield from fx.FiberSet[None, Never].make().pipe(scope.provide(sc))
            run = s.run(_holder(w, "r"), start_immediately=start_immediately).map(started.set)
            runner.set((yield from fx.yield_now().and_then(run).fork()))
            closer = yield from sc.close(exit_void).fork()
            yield from runner.get().await_exit()
            yield from closer.await_exit()
            if started.is_set():
                yield from started.get().await_exit()
            if list(s):
                yield from fx.die(f"the set still holds {list(s)} after closing")

        w.fork(main)
        interrupt_from_thread(w, "interrupter", runner)
        w.check(balanced(w, "r"))

    return build


def _fiber_set_join(w: World) -> None:
    """A member fails after a yield, another (interrupted from a thread,
    which ``join`` ignores without ``propagate_interruption``) holds a
    resource. ``join`` fails with exactly the member's failure; the
    holder is released once when the scope closes."""
    holder = Slot[AnyFiber]()
    joined: list[Exit[None, str]] = []

    @fx.gen
    def in_scope():
        s = yield from fx.FiberSet[None, str].make()
        holder.set((yield from s.run(_holder(w, "h"))))
        yield from s.run(fx.yield_now().and_then(fx.fail("boom")))
        joined.append((yield from s.join().exit()))

    w.fork(fx.scoped(in_scope))
    interrupt_from_thread(w, "interrupter", holder)
    w.check(balanced(w, "h"))

    def check() -> Problems:
        if len(joined) != 1 or not isinstance(joined[0], Failure):
            return f"join gave {joined}"
        if _reasons(joined[0].cause) != [Fail("boom")]:
            return f"join failed with {joined[0].cause.pretty()}"
        return None

    w.check(check)


def _fiber_set_propagate_interruption(w: World) -> None:
    """With ``propagate_interruption``, a member interrupted from a thread
    or by a fiber fails ``join`` with that interrupt; ``clear`` (the set's
    own interrupt) never does. ``join`` reports one of the outside
    interrupts or, if ``clear`` came first, nothing until the scope closes."""
    holder = Slot[AnyFiber]()
    other = Slot[AnyFiber]()
    joined: list[Exit[None, Never]] = []
    by_fiber = Slot[int]()

    @fx.gen
    def in_scope():
        s = yield from fx.FiberSet[None, Never].make()
        holder.set((yield from s.run(_holder(w, "a"), propagate_interruption=True)))
        other.set((yield from s.run(_holder(w, "b"), propagate_interruption=True)))
        joiner = yield from s.join().exit().map(joined.append).fork()

        @fx.gen
        def interrupter():
            by_fiber.set((yield from fx.fiber_id()))
            yield from other.get().interrupt()

        killer = yield from interrupter.fork()
        yield from fx.yield_now()
        yield from s.clear()
        yield from killer.await_exit()
        if list(s):
            yield from fx.die(f"the set holds {list(s)} after clear")
        yield from fx.yield_now()
        yield from joiner.interrupt()

    w.fork(fx.scoped(in_scope))
    interrupt_from_thread(w, "interrupter", holder)
    w.check(balanced(w, "a", "b"))

    def check() -> Problems:
        if not joined:
            return None  # cleared before any outside interrupt landed
        ex = joined[0]
        if not isinstance(ex, Failure):
            return f"join gave {ex}"
        senders = {r.fiber_id for r in ex.cause.reasons if isinstance(r, Interrupt)}
        if not ex.cause.has_interrupts_only or not senders <= {None, by_fiber.get()}:
            return f"join reported {ex.cause.pretty()}"
        return None

    w.check(check)


def _fiber_set_await_empty(w: World) -> None:
    """Members that finish on their own after a yield, one interrupted from
    a thread; ``await_empty`` returns only once the set is empty."""
    victim = Slot[AnyFiber]()
    left: list[int] = []

    def member(name: str) -> fx.Effect[None]:
        return fx.scoped(resource(w, name).and_then(fx.yield_now()))

    @fx.gen
    def in_scope():
        s = yield from fx.FiberSet[None, Never].make()
        yield from s.run(member("a"))
        victim.set((yield from s.run(member("b"), start_immediately=False)))
        yield from s.run(fx.sleep("1 second").and_then(member("c")))
        yield from s.await_empty()
        left.append(len(list(s)))

    w.fork(fx.scoped(in_scope))
    interrupt_from_thread(w, "interrupter", victim)
    w.check(balanced(w, "a", "b", "c"))
    w.check(lambda: None if left == [0] else f"await_empty returned with {left} members left")


# --- FiberMap ----------------------------------------------------------------------------------


def _fiber_map_replace(w: World) -> None:
    """Running under a key that holds a fiber interrupts the old one, which
    ``join`` does not report; ``only_if_missing`` gives back an interrupted
    fiber that never runs. A thread interrupts the replaced fiber too. Every
    resource is released once, the old fiber ends interrupted, and the map
    is empty and closed after its scope."""
    first = Slot[AnyFiber]()
    second = Slot[AnyFiber]()
    third = Slot[AnyFiber]()
    the_map = Slot[fx.FiberMap[str, None, Never]]()
    joined: list[Exit[None, Never]] = []

    @fx.gen
    def in_scope():
        m = the_map.set((yield from fx.FiberMap[str, None, Never].make()))
        joiner = yield from m.join().exit().map(joined.append).fork()
        first.set((yield from m.run("k", _holder(w, "one"))))
        yield from fx.yield_now()
        second.set((yield from m.run("k", _holder(w, "two"))))
        third.set((yield from m.run("k", _holder(w, "three"), only_if_missing=True)))
        yield from first.get().await_exit()
        current = m.get_unsafe("k")
        if current is not second.get():
            yield from fx.die(f"key k holds {current}, not the replacement")
        yield from fx.yield_now()
        yield from joiner.interrupt()

    w.fork(fx.scoped(in_scope))
    interrupt_from_thread(w, "interrupter", first)
    w.check(balanced(w, "one", "two"))

    def check() -> Problems:
        problems: list[str] = []
        if not _interrupted_only(_exit_of(first)):
            problems.append(f"the replaced fiber ended {_exit_of(first)}")
        if w.counts["acquire three"] or not _interrupted_only(_exit_of(third)):
            problems.append(f"only_if_missing ran, or ended {_exit_of(third)}")
        if joined:
            problems.append(f"join reported {joined} (no failure, no propagated interrupt)")
        m = the_map.get()
        if list(m) or m._state is not None:
            problems.append(f"the map is {m!r} after its scope closed")
        return problems

    w.check(check)


def _fiber_map_only_if_missing(w: World) -> None:
    """Two fibers race to run a holder under one key with
    ``only_if_missing``; whichever is there is interrupted from a thread,
    and a fiber removes the key. Never two holders of the key at once,
    each released once."""
    inside = [0, 0]  # now, most at once
    keyed = Slot[AnyFiber]()

    def enter() -> None:
        inside[0] += 1
        inside[1] = max(inside)

    def leave() -> None:
        inside[0] -= 1

    def holder(name: str) -> fx.Effect[Never]:
        held = scope.acquire_release(fx.sync(enter), lambda _, __: fx.sync(leave))
        return fx.scoped(resource(w, name).and_then(held).and_then(fx.never))

    @fx.gen
    def in_scope():
        m = yield from fx.FiberMap[str, None, Never].make()

        def racer(name: str) -> fx.Effect[None]:
            def keep(f: fx.Fiber[None, Never]) -> None:
                if m.get_unsafe("k") is f:
                    keyed.set(f)

            return fx.yield_now().and_then(m.run("k", holder(name), only_if_missing=True)).map(keep)

        a = yield from racer("a").fork()
        b = yield from racer("b").fork()
        yield from a.await_exit()
        yield from b.await_exit()
        yield from m.remove("k")
        if m.has_unsafe("k"):
            yield from fx.die("key k is still there after remove")

    w.fork(fx.scoped(in_scope))
    interrupt_from_thread(w, "interrupter", keyed)
    w.check(balanced(w, "a", "b"))

    def check() -> Problems:
        if inside[1] > 1 or inside[0] != 0:
            return f"at most {inside[1]} holders at once, {inside[0]} left"
        return None

    w.check(check)


# --- FiberHandle -------------------------------------------------------------------------------


def _fiber_handle(w: World) -> None:
    """A handle runs one holder, then a second that replaces it, then
    ``only_if_missing`` (never runs); a thread interrupts the first, a fiber
    clears. Every fiber ends, each resource released once, the replaced and
    cleared fibers are not reported by ``join``, and the handle is closed
    afterwards."""
    first = Slot[AnyFiber]()
    handle = Slot[fx.FiberHandle[None, Never]]()
    joined: list[Exit[None, Never]] = []
    after_clear: list[object] = []

    @fx.gen
    def in_scope():
        h = handle.set((yield from fx.FiberHandle[None, Never].make()))
        joiner = yield from h.join().exit().map(joined.append).fork()
        first.set((yield from h.run(_holder(w, "one"), start_immediately=False)))
        yield from fx.yield_now()
        second = yield from h.run(_holder(w, "two"))
        third = yield from h.run(_holder(w, "three"), only_if_missing=True)
        clearer = yield from h.clear().fork()
        yield from clearer.await_exit()
        after_clear.append(h.get_unsafe())
        yield from second.await_exit()
        yield from third.await_exit()
        yield from joiner.interrupt()

    w.fork(fx.scoped(in_scope))
    interrupt_from_thread(w, "interrupter", first)
    w.check(balanced(w, "one", "two"))

    def check() -> Problems:
        problems: list[str] = []
        if w.counts["acquire three"]:
            problems.append("only_if_missing ran its effect")
        if after_clear != [None]:
            problems.append(f"after clear the handle held {after_clear}")
        if joined:
            problems.append(f"join reported {joined}")
        if handle.get()._state is not None:
            problems.append(f"the handle is {handle.get()!r} after its scope closed")
        return problems

    w.check(check)


def _fiber_handle_close_while_starting(w: World) -> None:
    """The handle's scope closes while a fiber runs a holder into it (not
    started at once) and another replaces it; a thread interrupts the
    first runner. Every holder ends, released once."""
    runner = Slot[AnyFiber]()

    @fx.gen
    def main():
        sc = yield from scope.make()
        h = yield from fx.FiberHandle[None, Never].make().pipe(scope.provide(sc))
        runs: list[AnyFiber] = []
        a = h.run(_holder(w, "a"), start_immediately=False).map(runs.append)
        b = fx.yield_now().and_then(h.run(_holder(w, "b"))).map(runs.append)
        runner.set((yield from a.fork()))
        replacer = yield from b.fork()
        yield from sc.close(exit_void)
        yield from runner.get().await_exit()
        yield from replacer.await_exit()
        for f in runs:
            yield from f.await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", runner)
    w.check(balanced(w, "a", "b"))


# --- timeout ---------------------------------------------------------------------------------


def _timeout_same_instant(w: World) -> None:
    """``timeout_option`` and ``timeout`` of effects that end at the same
    virtual instant as their timers (the schedule picks which fires first):
    one succeeds holding a resource, one fails; a thread interrupts the
    first. Exactly one outcome each (value or timeout, failure or timeout),
    the resource released once."""
    seen: list[object] = []
    optional = Slot[AnyFiber]()
    failing = Slot[AnyFiber]()

    @fx.gen
    def main():
        held = fx.scoped(resource(w, "r").and_then(fx.sleep("1 second"))).as_(7)
        optional.set((yield from held.timeout_option("1 second").map(seen.append).fork()))
        fails = fx.sleep("1 second").and_then(fx.fail("late"))
        failing.set((yield from fails.timeout("1 second").fork()))
        yield from optional.get().await_exit()
        yield from failing.get().await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", optional)
    w.check(balanced(w, "r"))

    def check() -> Problems:
        problems: list[str] = []
        ex = _exit_of(optional)
        if isinstance(ex, Success) != (len(seen) == 1) or seen not in ([], [Some(7)], [None]):
            problems.append(f"timeout_option ended {ex}, recorded {seen}")
        if isinstance(ex, Failure) and not ex.cause.has_interrupts_only:
            problems.append(f"timeout_option failed: {ex.cause.pretty()}")
        fx_ = _exit_of(failing)
        errors: list[object] = [] if not isinstance(fx_, Failure) else _reasons(fx_.cause)
        if len(errors) != 1 or not (errors[0] == Fail("late") or _timed_out(fx_)):
            problems.append(f"timeout of a failing effect ended {fx_}")
        return problems

    w.check(check)


def _timeout_interrupted(w: World) -> None:
    """A ``timeout`` around a resource holder that never ends is
    interrupted by a fiber and from a thread before (or as) the timer
    fires: it ends with the timeout or interrupted, never anything else,
    and the inner effect's resource is released before ``timeout``
    returns."""
    timed = Slot[AnyFiber]()
    released_at_end: list[int] = []

    @fx.gen
    def main():
        inner = fx.scoped(resource(w, "r").and_then(fx.never))
        record = fx.sync(lambda: released_at_end.append(w.counts["release r"]))
        timed.set((yield from inner.timeout("1 second").ensuring(record).fork()))
        yield from fx.yield_now()
        yield from timed.get().interrupt()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", timed)
    w.check(balanced(w, "r"))

    def check() -> Problems:
        ex = _exit_of(timed)
        if not isinstance(ex, Failure):
            return f"timeout ended {ex}"
        if not (ex.cause.has_interrupts_only or _timed_out(ex)):
            return f"timeout ended {ex.cause.pretty()}"
        if released_at_end and released_at_end != [w.counts["acquire r"]]:
            return f"timeout ended before the inner release: {released_at_end}"
        return None

    w.check(check)


# --- zip / all / for_each / race_first -------------------------------------------------------


def _zip_concurrent(w: World) -> None:
    """``zip(concurrent=True)`` of a side that fails after a sleep and a
    resource holder; a thread interrupts the zip. It fails with the side's
    error (the holder's interrupt is dropped) or is interrupted from
    outside, and the holder is released once before it returns."""
    zipped = Slot[AnyFiber]()
    by_parent = Slot[int]()
    released_at_end: list[int] = []

    @fx.gen
    def main():
        failing = fx.scoped(resource(w, "a").and_then(fx.sleep("1 second"))).and_then(fx.fail("a"))
        record = fx.sync(lambda: released_at_end.append(w.counts["release b"]))
        both = failing.zip(_holder(w, "b"), concurrent=True)
        zipped.set(
            (yield from fx.fiber_id().map(by_parent.set).and_then(both).ensuring(record).fork())
        )
        yield from zipped.get().await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", zipped)
    w.check(balanced(w, "a", "b"))

    def check() -> Problems:
        ex = _exit_of(zipped)
        if not isinstance(ex, Failure):
            return f"zip ended {ex}"
        reasons = _reasons(ex.cause)
        if not set(map(str, reasons)) <= {str(Fail("a")), str(("interrupt", None))} or not reasons:
            return f"zip failed with {reasons}"
        if released_at_end and released_at_end != [w.counts["acquire b"]]:
            return f"zip ended before the holder's release: {released_at_end}"
        return None

    w.check(check)


def _all_concurrency(w: World) -> None:
    """``fx.all`` of four, two at a time: one fails after a yield, one is
    slow (sleeps), one holds a resource and is interrupted by a fiber, one
    never starts if a failure comes first. The whole fails with the first
    failure (the side's error, or the interrupt a fiber sent an item);
    every started item is released once; nothing starts after the
    failure."""
    victim = Slot[AnyFiber]()
    whole = Slot[AnyFiber]()
    killer_id = Slot[int]()
    started: list[str] = []

    def item(name: str, body: fx.Effect[None, str]) -> fx.Effect[None, str]:
        mark = fx.sync(lambda: started.append(name))
        return mark.and_then(fx.scoped(resource(w, name).and_then(body)))

    @fx.gen
    def main():
        grab = fx.current_fiber().map(victim.set).and_then(fx.never)
        whole.set(
            (
                yield from fx.all(
                    item("held", grab),
                    item("fails", fx.yield_now().and_then(fx.fail("x"))),
                    item("slow", fx.sleep("1 second")),
                    item("last", fx.void),
                    concurrency=2,
                ).fork()
            )
        )

        @fx.gen
        def killer():
            killer_id.set((yield from fx.fiber_id()))
            yield from fx.yield_now()
            if victim.is_set():
                yield from victim.get().interrupt()

        k = yield from killer.fork()
        yield from whole.get().await_exit()
        yield from k.await_exit()

    w.fork(main)
    w.check(balanced(w, "held", "fails", "slow", "last"))

    def check() -> Problems:
        ex = _exit_of(whole)
        if not isinstance(ex, Failure):
            return f"all ended {ex}"
        reasons = _reasons(ex.cause)
        # A failure after the first adds its own reasons, not its interrupts.
        killed = ("interrupt", killer_id.get())
        if reasons not in ([Fail("x")], [killed], [killed, Fail("x")]):
            return f"all failed with {reasons}"
        if "last" in started:
            return f"an item started after the failure: {started}"
        return None

    w.check(check)


def _for_each_failure(w: World) -> None:
    """``for_each`` (two at a time) over items holding resources where one
    fails after a yield; a thread interrupts the whole. Siblings are
    interrupted and released once before it returns; the cause is the
    item's failure, then any interrupt from outside, never the siblings'
    interrupts."""
    each = Slot[AnyFiber]()
    released_at_end: list[int] = []

    def item(i: int) -> fx.Effect[int, str]:
        body = fx.yield_now().and_then(fx.fail(f"bad {i}") if i == 1 else fx.never)
        return fx.scoped(resource(w, str(i)).and_then(body)).as_(i)

    @fx.gen
    def main():
        record = fx.sync(lambda: released_at_end.append(w.counts["release 0"]))
        each.set((yield from fx.for_each(range(3), item, concurrency=2).ensuring(record).fork()))
        yield from each.get().await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", each)
    w.check(balanced(w, "0", "1", "2"))

    def check() -> Problems:
        ex = _exit_of(each)
        if not isinstance(ex, Failure):
            return f"for_each ended {ex}"
        reasons = _reasons(ex.cause)
        # A failure after the outside interrupt adds its own reasons too.
        fail, outside = Fail("bad 1"), ("interrupt", None)
        allowed = ([fail], [outside], [fail, outside], [outside, fail])
        if reasons not in allowed:
            return f"for_each failed with {reasons}"
        if released_at_end and released_at_end != [w.counts["acquire 0"]]:
            return f"for_each ended before a sibling's release: {released_at_end}"
        return None

    w.check(check)


def _race_first(w: World) -> None:
    """``race_first`` of a side that fails and one that succeeds at the same
    instant, and ``race_all_first`` of three (two at the same instant); a
    thread interrupts the first race. The first to end wins, success or
    failure; losers are released once, before the race returns."""
    pair = Slot[AnyFiber]()
    three = Slot[AnyFiber]()
    released_at_end: list[tuple[int, int]] = []

    def record() -> None:
        released_at_end.append((w.counts["release a"], w.counts["release b"]))

    def side(name: str, delay: str, fails: bool) -> fx.Effect[str, str]:
        body = fx.scoped(resource(w, name).and_then(fx.sleep(delay)))
        return body.and_then(fx.fail(name)) if fails else body.as_(name)

    @fx.gen
    def main():
        race = side("a", "1 second", True).race_first(side("b", "1 second", False))
        pair.set((yield from race.ensuring(fx.sync(record)).fork()))
        racers = fx.race_all_first(
            side("c", "2 seconds", False), side("d", "1 second", True), side("e", "1 second", False)
        )
        three.set((yield from racers.fork()))
        yield from pair.get().await_exit()
        yield from three.get().await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", pair)
    w.check(balanced(w, *"abcde"))

    def check() -> Problems:
        problems: list[str] = []
        ex = _exit_of(pair)
        if not (
            (isinstance(ex, Success) and ex.value == "b")
            or (
                isinstance(ex, Failure)
                and _reasons(ex.cause)
                in ([Fail("a")], [("interrupt", None)], [Fail("a"), ("interrupt", None)])
            )
        ):
            problems.append(f"race_first ended {ex}")
        acquired = (w.counts["acquire a"], w.counts["acquire b"])
        if released_at_end and released_at_end != [acquired]:
            problems.append(f"race_first returned before a loser's release: {released_at_end}")
        ex3 = _exit_of(three)
        # ``c`` sleeps longer, but its sleep may start late.
        if not (
            (isinstance(ex3, Success) and ex3.value in ("c", "e"))
            or (isinstance(ex3, Failure) and _reasons(ex3.cause) == [Fail("d")])
        ):
            problems.append(f"race_all_first ended {ex3}")
        return problems

    w.check(check)


# --- retry / repeat --------------------------------------------------------------------------


def _retry_spaced(w: World) -> None:
    """``retry(spaced 1s, times=3)`` of an always-failing effect runs at 0,
    1, 2 and 3 seconds (virtual time), then fails with its error; an
    ``exponential`` one (1s, 2s, 4s) runs at 0, 1, 3, 7. A thread interrupts
    the first, a fiber the second: they stop where they are, with no
    attempt after the interrupt is delivered."""
    spaced: list[float] = []
    expo: list[float] = []
    first = Slot[AnyFiber]()
    second = Slot[AnyFiber]()
    at_interrupt: list[int] = []

    def attempt(times: list[float]) -> fx.Effect[Never, str]:
        return fx.sync(lambda: times.append(w.scheduler.now)).and_then(fx.fail("e"))

    @fx.gen
    def main():
        first.set(
            (yield from attempt(spaced).retry(schedule=schedule.spaced("1 second"), times=3).fork())
        )
        second.set(
            (
                yield from attempt(expo)
                .retry(schedule=schedule.exponential("1 second"), times=3)
                .fork()
            )
        )
        yield from fx.sleep("2 seconds")
        me = yield from fx.fiber_id()

        def interrupt() -> None:
            # In one step with the delivery, which is at once from a fiber.
            if second.get()._exit is None:
                at_interrupt.append(len(expo))
                second.get().interrupt_as_unsafe(me)

        yield from fx.sync(interrupt)
        yield from second.get().await_exit()
        yield from first.get().await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", first)

    def check() -> Problems:
        problems: list[str] = []
        for name, times, expected, fiber in (
            ("spaced", spaced, [0, 1, 2, 3], first),
            ("exponential", expo, [0, 1, 3, 7], second),
        ):
            ex = _exit_of(fiber)
            if times != expected[: len(times)]:
                problems.append(f"{name} ran at {times}")
            if isinstance(ex, Failure) and _reasons(ex.cause) == [Fail("e")]:
                if times != expected:
                    problems.append(f"{name} gave up after {times}")
            elif not _interrupted_only(ex):
                problems.append(f"{name} ended {ex}")
        if at_interrupt and at_interrupt != [len(expo)]:
            problems.append(f"exponential ran again after its interrupt: {at_interrupt}, {expo}")
        return problems

    w.check(check)


def _repeat_recurs(w: World) -> None:
    """``repeat(recurs(2))`` with a 1 second sleep in each run runs three
    times and succeeds with the schedule's last output (2); a thread
    interrupts it mid-sleep, after which it never runs again."""
    runs: list[float] = []
    repeating = Slot[AnyFiber]()

    @fx.gen
    def main():
        once = fx.sync(lambda: runs.append(w.scheduler.now)).and_then(fx.sleep("1 second"))
        repeating.set((yield from once.repeat(schedule.recurs(2)).fork()))
        yield from repeating.get().await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", repeating)

    def check() -> Problems:
        ex = _exit_of(repeating)
        if runs != [0, 1, 2][: len(runs)]:
            return f"repeat ran at {runs}"
        if isinstance(ex, Success) and (ex.value != 2 or len(runs) != 3):
            return f"repeat succeeded with {ex.value} after {runs}"
        if not isinstance(ex, Success) and not _interrupted_only(ex):
            return f"repeat ended {ex}"
        return None

    w.check(check)


def _retry_test_clock(w: World) -> None:
    """``retry(spaced 1s, times=2)`` under the TestClock: each ``adjust`` of
    a second runs exactly one more attempt, stamped with the clock's time; a
    thread interrupts the retrying fiber mid-delay, which ends it there."""
    stamps: list[float] = []
    retrying = Slot[AnyFiber]()

    @fx.gen
    def main():
        stamp = fx.clock.current_time_millis().map(stamps.append)
        policy = schedule.spaced("1 second")
        retrying.set(
            (
                yield from stamp.and_then(fx.fail("e"))
                .retry(schedule=policy, times=2)
                .fork(start_immediately=True)
            )
        )
        clock = yield from test_clock()
        for _ in range(3):
            # Once the attempt has failed and its delay started (or it ended).
            while not clock.pending_sleeps and retrying.get()._exit is None:
                yield from fx.yield_now()
            yield from adjust("1 second")
        yield from retrying.get().await_exit()

    w.fork(main.pipe(fx.provide(TestClock.layer())))
    interrupt_from_thread(w, "interrupter", retrying)

    def check() -> Problems:
        ex = _exit_of(retrying)
        if stamps != [0, 1000, 2000][: len(stamps)]:
            return f"attempts at {stamps}"
        if isinstance(ex, Failure) and _reasons(ex.cause) == [Fail("e")]:
            return None if len(stamps) == 3 else f"gave up after {stamps}"
        return None if _interrupted_only(ex) else f"retry ended {ex}"

    w.check(check)


# --- fiber primitives ------------------------------------------------------------------------


def _fork_start_immediately(w: World) -> None:
    """A child forked with ``start_immediately`` acquires a resource before
    the parent goes on, then is interrupted by the parent and from a thread
    at once. It ran up to its first wait before ``fork`` returned, and its
    resource is released once."""
    child = Slot[AnyFiber]()
    acquired_at_fork: list[int] = []

    @fx.gen
    def main():
        child.set((yield from _holder(w, "r").fork(start_immediately=True)))
        acquired_at_fork.append(w.counts["acquire r"])
        yield from child.get().interrupt()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", child)
    w.check(balanced(w, "r"))

    def check() -> Problems:
        # Up to its first wait, or (with a step budget) its first pause.
        if w.ops is None and acquired_at_fork != [1]:
            return f"the child had acquired {acquired_at_fork} when fork returned"
        return None if _interrupted_only(_exit_of(child)) else f"child ended {_exit_of(child)}"

    w.check(check)


def _fork_daemon(w: World) -> None:
    """A parent forks a daemon holding a resource across a sleep and a plain
    child holding one until interrupted, and ends. The plain child is
    interrupted with the parent; the daemon outlives it and finishes
    (unless a thread interrupts it). Each resource released once."""
    daemon = Slot[AnyFiber]()
    child = Slot[AnyFiber]()
    finished: list[str] = []

    def work(name: str) -> fx.Effect[None]:
        body = resource(w, name).and_then(fx.sleep("1 second"))
        return fx.scoped(body).and_then(fx.sync(lambda: finished.append(name)))

    @fx.gen
    def parent():
        daemon.set((yield from work("daemon").fork_daemon()))
        child.set((yield from _holder(w, "child").fork()))
        yield from fx.yield_now()

    @fx.gen
    def main():
        yield from (yield from parent.fork()).await_exit()
        yield from daemon.get().await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", daemon)
    w.check(balanced(w, "daemon", "child"))

    def check() -> Problems:
        problems: list[str] = []
        if not _interrupted_only(_exit_of(child)):
            problems.append(f"the plain child outlived its parent: {_exit_of(child)}")
        ex = _exit_of(daemon)
        if isinstance(ex, Success) != ("daemon" in finished):
            problems.append(f"the daemon ended {ex}, finished {finished}")
        if not isinstance(ex, Success) and not _interrupted_only(ex):
            problems.append(f"the daemon ended {ex}")
        return problems

    w.check(check)


def _fork_uninterruptible(w: World) -> None:
    """A child forked ``uninterruptible=True`` takes a resource and two
    yields, interrupted by its parent and from a thread meanwhile. It runs
    every step (no interrupt lands inside it) and releases once; its
    ``restore``d part is where an interrupt may land."""
    child = Slot[AnyFiber]()
    steps: list[str] = []

    def step(name: str) -> fx.Effect[None]:
        return fx.yield_now().and_then(fx.sync(lambda: steps.append(name)))

    @fx.gen
    def main():
        body = fx.scoped(resource(w, "r").and_then(step("one")).and_then(step("two")))
        child.set((yield from body.fork(uninterruptible=True)))
        yield from fx.yield_now()
        yield from child.get().interrupt()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", child)
    w.check(balanced(w, "r"))
    w.check(lambda: None if steps == ["one", "two"] else f"the uninterruptible child ran {steps}")


def _await_exit_thread_resumed(w: World) -> None:
    """A waiter parks on a callback a thread resumes, then joins (and awaits
    the exit of) a target that a fiber interrupts. It gets exactly the
    target's exit, and ``join`` fails with the target's cause."""
    target = Slot[AnyFiber]()
    parked = Slot[Callable[[fx.Effect[None]], None]]()
    joined: list[Exit[Any, Any]] = []
    awaited: list[Exit[Any, Any]] = []

    def park(resume: Callable[[fx.Effect[None]], None]) -> None:
        parked.set(resume)

    @fx.gen
    def main():
        target.set((yield from _holder(w, "r").fork()))
        waiter = yield from (
            fx.callback(park)
            .and_then(target.get().await_exit().map(awaited.append))
            .and_then(target.get().join().exit().map(joined.append))
            .fork()
        )
        yield from fx.yield_now()
        yield from target.get().interrupt()
        yield from waiter.await_exit()

    w.fork(main)

    def resumer() -> ThreadBody:
        yield parked.is_set
        parked.get()(fx.void)

    w.thread("resumer", resumer)
    w.check(balanced(w, "r"))

    def check() -> Problems:
        ex = _exit_of(target)
        if len(awaited) != 1 or awaited[0] is not ex:
            return f"await_exit saw {awaited}, the target ended {ex}"
        if len(joined) != 1 or not isinstance(joined[0], Failure) or not isinstance(ex, Failure):
            return f"join saw {joined}, the target ended {ex}"
        if _reasons(joined[0].cause) != _reasons(ex.cause):
            return (
                f"join failed with {joined[0].cause.pretty()}, the target with {ex.cause.pretty()}"
            )
        return None

    w.check(check)


def _interrupt_chain(w: World) -> None:
    """A fiber interrupts its child, whose release takes a second, while
    itself being interrupted by a fiber and from a thread. Everything ends,
    the child's resource is released once, and the middle fiber ends only
    after its child has (a fiber's children are interrupted and awaited
    before it ends)."""
    middle = Slot[AnyFiber]()
    child = Slot[AnyFiber]()
    child_done_when_middle_ended: list[bool] = []

    slow_release = scope.acquire_release(
        w.bump("acquire r"), lambda _, __: fx.sleep("1 second").and_then(w.bump("release r"))
    )

    @fx.gen
    def middle_body():
        child.set(
            (yield from fx.scoped(slow_release.and_then(fx.never)).fork(start_immediately=True))
        )
        yield from child.get().interrupt()

    def record(_: object) -> None:
        child_done_when_middle_ended.append(child.is_set() and child.get()._exit is not None)

    @fx.gen
    def main():
        middle.set((yield from middle_body.fork()))
        yield from fx.sync(lambda: middle.get().add_observer_unsafe(record))
        yield from fx.yield_now()
        yield from middle.get().interrupt()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", middle)
    w.check(balanced(w, "r"))

    def check() -> Problems:
        # Interrupted before it forked the child, it has none to wait for.
        expected = [True] if child.is_set() else [False]
        if child_done_when_middle_ended != expected:
            return f"the middle fiber ended before its child: {child_done_when_middle_ended}"
        return None

    w.check(check)


SCENARIOS: list[Scenario] = [
    Scenario("fiber_set_scope_close", _fiber_set_scope_close, runs=600),
    Scenario(
        "fiber_set_close_while_starting[start]", _fiber_set_close_while_starting(True), runs=600
    ),
    Scenario(
        "fiber_set_close_while_starting[later]", _fiber_set_close_while_starting(False), runs=600
    ),
    Scenario("fiber_set_join", _fiber_set_join, runs=600),
    Scenario("fiber_set_propagate_interruption", _fiber_set_propagate_interruption, runs=600),
    Scenario("fiber_set_await_empty", _fiber_set_await_empty, runs=600),
    Scenario("fiber_map_replace", _fiber_map_replace, runs=600),
    Scenario("fiber_map_only_if_missing", _fiber_map_only_if_missing, runs=600),
    Scenario("fiber_handle", _fiber_handle, runs=600),
    Scenario("fiber_handle_close_while_starting", _fiber_handle_close_while_starting, runs=600),
    Scenario("timeout_same_instant", _timeout_same_instant, runs=600),
    Scenario("timeout_interrupted", _timeout_interrupted, runs=600),
    Scenario("zip_concurrent", _zip_concurrent, runs=600),
    Scenario("all_concurrency", _all_concurrency, runs=600),
    Scenario("for_each_failure", _for_each_failure, runs=600),
    Scenario("race_first", _race_first, runs=400),
    # Virtual time passes only while every fiber waits, so an attempt and
    # the delay it starts happen at the same instant.
    Scenario("retry_spaced", _retry_spaced, timers="when_idle", runs=600),
    Scenario("repeat_recurs", _repeat_recurs, timers="when_idle", runs=600),
    Scenario("retry_test_clock", _retry_test_clock, order="fifo", timers="when_idle", runs=400),
    Scenario("fork_start_immediately", _fork_start_immediately, runs=600),
    Scenario("fork_daemon", _fork_daemon, runs=600),
    Scenario("fork_uninterruptible", _fork_uninterruptible, runs=600),
    Scenario("await_exit_thread_resumed", _await_exit_thread_resumed, runs=600),
    Scenario("interrupt_chain", _interrupt_chain, runs=600),
]
