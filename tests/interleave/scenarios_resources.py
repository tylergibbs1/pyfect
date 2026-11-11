"""Interleaving scenarios for Pool, RcRef, RcMap, ScopedRef, Cache, ScopedCache,
Layer memoization, acquire_release / the interruptibility masks and Scope
finalizers (README.md).

Each counts its resources with ``_Live``: every acquire gets its own number,
and the checks are that each is released exactly once, that no more are
alive at once than the primitive allows, and that a value a fiber was handed
was still alive when it looked. Time is virtual: ``_VirtualClock`` reads the
harness scheduler's clock, so TTLs measured on the ``Clock`` move only as the
harness fires timers.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never

import pyfect as fx
from pyfect import layer, scope
from pyfect.clock import Clock, LiveClock
from pyfect.errors import ExceededCapacityError
from pyfect.exit import Exit, Failure, Success
from pyfect.exit import void as exit_void
from pyfect.layer import MemoMap
from pyfect.pool import TimeToLiveStrategy

from ._harness import Problems, Scenario, World
from ._kit import AnyFiber, Slot, interrupt_from_thread, released_once

# --- shared helpers ------------------------------------------------------------------------


class _VirtualClock(LiveClock):
    """The live clock's sleeps (harness timers), reading the harness's
    virtual time, so what a primitive measures on the ``Clock`` agrees with
    when its timers fire."""

    def __init__(self, w: World) -> None:
        self._w = w

    def _nanos(self) -> int:
        return round(self._w.scheduler.now * 1_000_000_000)

    def current_time_millis_unsafe(self) -> float:
        return float(self._nanos() // 1_000_000)

    def monotonic_unsafe(self) -> float:
        return self._w.scheduler.now

    def now_nanos_unsafe(self) -> int:
        return self._nanos()

    def monotonic_nanos_unsafe(self) -> int:
        return self._nanos()


def _virtual_time[A, E](w: World, eff: fx.Effect[A, E]) -> fx.Effect[A, E]:
    return eff.pipe(fx.provide_service(Clock, _VirtualClock(w)))


class _Live:
    """Resources numbered as acquired, counted as ``acquire <prefix><n>`` /
    ``release <prefix><n>`` (see ``released_once``), with how many are
    alive now and at most."""

    def __init__(self, w: World, prefix: str, *, pause: bool = False) -> None:
        self.w = w
        self.prefix = prefix
        self.pause = pause
        self.alive: set[int] = set()
        self.most = 0
        self.made = 0
        self.stale: list[str] = []
        self.on_release: Callable[[int], None] | None = None

    def acquire(self) -> fx.Effect[int, Never, scope.Scope]:
        """Acquire the next resource; with ``pause``, yield inside the
        (uninterruptible) acquire, so others run in the middle of it."""

        def make() -> int:
            self.made += 1
            n = self.made
            self.alive.add(n)
            self.most = max(self.most, len(self.alive))
            self.w.counts[f"acquire {self.prefix}{n}"] += 1
            self.w.notes.append(f"acquire {self.prefix}{n}")
            return n

        def release(n: int) -> None:
            self.alive.discard(n)
            self.w.counts[f"release {self.prefix}{n}"] += 1
            self.w.notes.append(f"release {self.prefix}{n}")
            if self.on_release is not None:
                self.on_release(n)

        made = fx.sync(make)
        if self.pause:
            made = made.tap(lambda _: fx.yield_now())
        return scope.acquire_release(made, lambda n, _: fx.sync(lambda: release(n)))

    def use(self, who: str) -> Callable[[int], None]:
        """Record a use of a value handed to ``who``: it must be alive."""

        def check(n: int) -> None:
            self.w.notes.append(f"{who} uses {self.prefix}{n}")
            if n not in self.alive:
                self.stale.append(f"{who} used {self.prefix}{n} after its release")

        return check

    def checks(self, *, most: int | None = None) -> Callable[[], Problems]:
        def check() -> Problems:
            unbalanced = released_once(self.w, self.prefix)()
            problems = [*self.stale, *(unbalanced or ())]
            if self.alive:
                problems.append(f"{self.prefix}: still alive at the end: {sorted(self.alive)}")
            if most is not None and self.most > most:
                problems.append(f"{self.prefix}: {self.most} alive at once, at most {most} allowed")
            return problems

        return check


def _interrupted_only(ex: Exit[Any, Any] | None) -> bool:
    return isinstance(ex, Failure) and ex.cause.has_interrupts_only


def _success_or_interrupted(name: str, fiber: Slot[AnyFiber]) -> Callable[[], Problems]:
    def check() -> Problems:
        ex = fiber.get()._exit
        if isinstance(ex, Success) or _interrupted_only(ex):
            return None
        return f"{name} ended with {ex}"

    return check


# --- Pool ----------------------------------------------------------------------------------


def _pool_ttl(strategy: TimeToLiveStrategy) -> Callable[[World], None]:
    def build(w: World) -> None:
        """A pool of 1 to 2 items with a TTL of 1 second; three borrowers
        hold an item across a 2-second sleep (so the pool grows, and with
        ``"creation"`` items expire while borrowed), one interrupted from a
        thread; then a late borrower after the TTL. At most 2 items in
        service, plus those expired while borrowed (they live until given
        back); every borrowed item alive while held; all released once by
        the time the pool's scope closes."""
        live = _Live(w, "item")
        second = Slot[AnyFiber]()

        def borrow(pool: fx.Pool[int], who: str) -> fx.Effect[None]:
            def hold(n: int) -> fx.Effect[None]:
                live.use(who)(n)
                after = fx.sync(lambda: live.use(f"{who} after sleeping")(n))
                return fx.sleep("2 seconds").and_then(after)

            return fx.scoped(pool.get().flat_map(hold))

        @fx.gen
        def in_scope():
            pool = yield from fx.Pool.make_with_ttl(
                live.acquire(),
                min=1,
                max=2,
                time_to_live="1 second",
                time_to_live_strategy=strategy,
            )
            first = yield from borrow(pool, "first").fork()
            second.set((yield from borrow(pool, "second").fork()))
            third = yield from borrow(pool, "third").fork()
            yield from first.await_exit()
            yield from second.get().await_exit()
            yield from third.await_exit()
            yield from fx.sleep("3 seconds")
            yield from borrow(pool, "late")

        w.fork(_virtual_time(w, fx.scoped(in_scope)))
        interrupt_from_thread(w, "interrupter", second)
        # Only ``"creation"`` expires a borrowed item; three borrowers hold at most 3.
        w.check(live.checks(most=2 if strategy == "usage" else 2 + 3))

    return build


def _pool_invalidate_idle(w: World) -> None:
    """A fixed pool of 2: one borrower returns its item and invalidates it
    while idle, another invalidates its item while still holding it, and a
    third (interrupted from a thread) borrows meanwhile. Never more than 2
    in service plus those invalidated while borrowed; every item a borrower
    holds is alive; all released once."""
    live = _Live(w, "item", pause=True)
    third = Slot[AnyFiber]()

    @fx.gen
    def in_scope():
        pool = yield from fx.Pool.make(live.acquire(), size=2)

        @fx.gen
        def idle_invalidator():
            n = yield from fx.scoped(pool.get().tap(lambda n: fx.sync(lambda: live.use("idle")(n))))
            yield from pool.invalidate(n)

        @fx.gen
        def held_invalidator():
            n = yield from pool.get()
            live.use("held")(n)
            yield from pool.invalidate(n)
            yield from fx.yield_now()
            live.use("held after invalidating")(n)

        a = yield from idle_invalidator.fork()
        b = yield from fx.scoped(held_invalidator).fork()
        third.set(
            (
                yield from fx.scoped(
                    pool.get().map(live.use("third")).and_then(fx.yield_now())
                ).fork()
            )
        )
        yield from a.await_exit()
        yield from b.await_exit()
        yield from third.get().await_exit()

    w.fork(fx.scoped(in_scope))
    interrupt_from_thread(w, "interrupter", third)
    # An item invalidated while borrowed lives until given back, beside the
    # 2 in service; each of the two invalidations may hit a borrowed item.
    w.check(live.checks(most=4))


def _pool_shutdown_waiters(w: World) -> None:
    """A pool of 1 whose scope closes while one fiber holds the item and two
    wait for it (one interrupted from a thread). The close waits for the
    item to come back; the waiters end (with the item, or interrupted as the
    pool shuts down); the item is released once."""
    live = _Live(w, "item")
    waiter = Slot[AnyFiber]()
    other = Slot[AnyFiber]()

    @fx.gen
    def main():
        sc = yield from scope.make()
        pool = yield from fx.Pool.make(live.acquire(), size=1).pipe(scope.provide(sc))
        holder = yield from fx.scoped(
            pool.get().map(live.use("holder")).and_then(fx.yield_now()).and_then(fx.yield_now())
        ).fork()
        waiter.set((yield from fx.scoped(pool.get().map(live.use("waiter"))).fork()))
        other.set((yield from fx.scoped(pool.get().map(live.use("other"))).fork()))
        yield from fx.yield_now()
        yield from sc.close(exit_void)
        yield from holder.await_exit()
        yield from waiter.get().await_exit()
        yield from other.get().await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", waiter)
    w.check(live.checks(most=1))
    w.check(_success_or_interrupted("a waiter", waiter))
    w.check(_success_or_interrupted("the other waiter", other))


def _pool_concurrency(w: World) -> None:
    """One item shared by up to 2 borrowers (``concurrency=2``): three
    borrowers ``use`` it across a sleep while the pool's scope closes, one
    interrupted from a thread and one invalidating the item. Never more than
    2 on an item at once, every item alive while used, all released once."""
    live = _Live(w, "item")
    on_item: dict[int, int] = {}
    crowded: list[str] = []
    second = Slot[AnyFiber]()

    def enter(n: int) -> None:
        on_item[n] = on_item.get(n, 0) + 1
        if on_item[n] > 2:
            crowded.append(f"{on_item[n]} borrowers on item{n}")

    def leave(n: int) -> None:
        on_item[n] -= 1

    def borrower(pool: fx.Pool[int], who: str, *, invalidate: bool = False) -> fx.Effect[None]:
        def body(n: int) -> fx.Effect[None]:
            live.use(who)(n)
            hold = fx.sync(lambda: enter(n)).and_then(fx.sleep("1 second"))
            if invalidate:
                hold = hold.and_then(pool.invalidate(n))
            return hold.ensuring(fx.sync(lambda: leave(n))).map(lambda _: live.use(who)(n))

        return pool.use(body)

    @fx.gen
    def main():
        sc = yield from scope.make()
        pool = yield from fx.Pool.make(live.acquire(), size=1, concurrency=2).pipe(
            scope.provide(sc)
        )
        first = yield from borrower(pool, "first", invalidate=True).fork()
        second.set((yield from borrower(pool, "second").fork()))
        third = yield from borrower(pool, "third").fork()
        yield from fx.yield_now()
        yield from sc.close(exit_void)
        yield from first.await_exit()
        yield from second.get().await_exit()
        yield from third.await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", second)
    w.check(live.checks(most=2))
    w.check(lambda: crowded)


# --- RcRef / RcMap ---------------------------------------------------------------------------
#
# Neither keeps "one value alive at a time": as in Effect, a release (or an
# abandoned acquisition) detaches the value before closing it, so a new get
# may acquire the next while the last is still being released. What holds
# is that callers holding the ref at the same time share one value.


class _Holders:
    """Who holds which value now; holders at the same time must share it."""

    def __init__(self, live: _Live) -> None:
        self.live = live
        self.held: dict[str, int] = {}
        self.problems: list[str] = []

    def hold[E](self, who: str, get: fx.Effect[int, E, scope.Scope]) -> fx.Effect[None, E]:
        """Get, hold across a yield, let go before the scope releases it."""

        def take(n: int) -> None:
            self.live.use(who)(n)
            others = {k: v for k, v in self.held.items() if v != n}
            if others:
                self.problems.append(f"{who} got {n} while {others} were held")
            self.held[who] = n

        def let_go() -> None:
            self.held.pop(who, None)

        held = get.map(take).and_then(fx.yield_now()).ensuring(fx.sync(let_go))
        return fx.scoped(held)

    def check(self) -> Problems:
        return self.problems


def _rc_ref_shared(w: World) -> None:
    """Three fibers get an RcRef at once (one interrupted by a fiber, one
    from a thread); its acquire yields inside. Holders at the same time
    share one value, each alive while held and released once; a get after
    they have all gone acquires afresh if the last was released."""
    live = _Live(w, "value", pause=True)
    holders = _Holders(live)
    second = Slot[AnyFiber]()

    @fx.gen
    def in_scope():
        ref = yield from fx.RcRef.make(live.acquire())
        first = yield from holders.hold("first", ref.get()).fork()
        second.set((yield from holders.hold("second", ref.get()).fork()))
        third = yield from holders.hold("third", ref.get()).fork()
        yield from fx.yield_now()
        yield from first.interrupt()
        yield from second.get().await_exit()
        yield from third.await_exit()
        yield from holders.hold("after", ref.get())

    w.fork(fx.scoped(in_scope))
    interrupt_from_thread(w, "interrupter", second)
    w.check(live.checks())
    w.check(holders.check)


def _rc_ref_idle_ttl(w: World) -> None:
    """An RcRef kept for 1 second after its last user: a getter lets go, and
    two more gets come exactly as the idle timer fires (the schedule picks
    which goes first), one interrupted from a thread. Holders share one
    value, each alive while held, all released once."""
    live = _Live(w, "value")
    holders = _Holders(live)
    late = Slot[AnyFiber]()

    @fx.gen
    def in_scope():
        ref = yield from fx.RcRef.make(live.acquire(), idle_time_to_live="1 second")
        yield from holders.hold("first", ref.get())
        late.set((yield from fx.sleep("1 second").and_then(holders.hold("late", ref.get())).fork()))
        yield from fx.sleep("1 second")
        yield from holders.hold("on time", ref.get())
        yield from late.get().await_exit()

    w.fork(fx.scoped(in_scope))
    interrupt_from_thread(w, "interrupter", late)
    w.check(live.checks())
    w.check(holders.check)


def _rc_ref_invalidate(w: World) -> None:
    """A holder keeps an RcRef's value and invalidates it, then gets again;
    another fiber invalidates too and a third (interrupted from a thread)
    gets. An invalidated value stays alive until its holder lets go, a get
    after an invalidation acquires afresh, each value is released once."""
    live = _Live(w, "value", pause=True)
    getter = Slot[AnyFiber]()
    fresh: list[str] = []

    def holder(ref: fx.RcRef[int]) -> fx.Effect[None]:
        def again(old: int, new: int) -> None:
            live.use("holder again")(new)
            if new == old:
                fresh.append(f"the get after invalidating {old} gave it again")

        def hold(old: int) -> fx.Effect[None, Never, scope.Scope]:
            live.use("holder")(old)
            then = ref.invalidate().and_then(fx.yield_now()).and_then(ref.get())
            return then.map(lambda new: again(old, new)).map(lambda _: live.use("holder")(old))

        return fx.scoped(ref.get().flat_map(hold))

    @fx.gen
    def in_scope():
        ref = yield from fx.RcRef.make(live.acquire())
        held = yield from holder(ref).fork()
        invalidator = yield from ref.invalidate().fork()
        getter.set(
            (
                yield from fx.scoped(
                    ref.get().map(live.use("getter")).and_then(fx.yield_now())
                ).fork()
            )
        )
        yield from held.await_exit()
        yield from invalidator.await_exit()
        yield from getter.get().await_exit()

    w.fork(fx.scoped(in_scope))
    interrupt_from_thread(w, "interrupter", getter)
    w.check(live.checks())
    w.check(lambda: fresh)


def _rc_ref_acquire_interrupt(w: World) -> None:
    """Two getters wait while the RcRef's acquire sleeps; one is interrupted
    by a fiber, the other from a thread. Once both leave, the acquisition is
    interrupted (its resource, if acquired, released once); a later get
    acquires afresh and succeeds."""
    live = _Live(w, "value")
    second = Slot[AnyFiber]()
    seen: list[int] = []

    @fx.gen
    def in_scope():
        ref = yield from fx.RcRef.make(live.acquire().tap(lambda _: fx.sleep("1 second")))
        first = yield from fx.scoped(ref.get().map(live.use("first"))).fork()
        second.set((yield from fx.scoped(ref.get().map(live.use("second"))).fork()))
        yield from fx.yield_now()
        yield from first.interrupt()
        yield from second.get().await_exit()
        n = yield from fx.scoped(ref.get().tap(lambda n: fx.sync(lambda: live.use("after")(n))))
        seen.append(n)

    w.fork(fx.scoped(in_scope))
    interrupt_from_thread(w, "interrupter", second)
    w.check(live.checks())
    w.check(lambda: None if len(seen) == 1 else f"the late get saw {seen}")


def _str_lookup(live: _Live) -> Callable[[str], fx.Effect[int, Never, scope.Scope]]:
    def lookup(_key: str) -> fx.Effect[int, Never, scope.Scope]:
        return live.acquire()

    return lookup


def _rc_map_shared(w: World) -> None:
    """An RcMap of capacity 1: two getters of ``a`` and one of ``b`` at once
    (one ``a`` getter interrupted from a thread); lookups yield inside.
    Holders of ``a`` at the same time share one value, ``b`` gets its value
    or ``ExceededCapacityError``, each value alive while held and released
    once."""
    live = _Live(w, "value", pause=True)
    holders = _Holders(live)
    others = _Holders(live)
    getter = Slot[AnyFiber]()
    b_exit: list[Exit[Any, Any]] = []

    @fx.gen
    def in_scope():
        m = yield from fx.RcMap.make(_str_lookup(live), capacity=1)
        first = yield from holders.hold("first a", m.get("a")).fork()
        getter.set((yield from holders.hold("second a", m.get("a")).fork()))
        b = yield from others.hold("b", m.get("b")).exit().map(b_exit.append).fork()
        yield from first.await_exit()
        yield from getter.get().await_exit()
        yield from b.await_exit()
        yield from others.hold("late b", m.get("b"))

    w.fork(fx.scoped(in_scope))
    interrupt_from_thread(w, "interrupter", getter)
    w.check(live.checks())
    w.check(holders.check)
    w.check(others.check)

    def check() -> Problems:
        for ex in b_exit:
            if isinstance(ex, Failure) and not isinstance(ex.cause.squash(), ExceededCapacityError):
                return f"b failed with {ex.cause.pretty()}"
        return None

    w.check(check)


def _rc_map_idle_ttl(w: World) -> None:
    """An RcMap key kept 1 second after its last user: after it is let go, a
    ``touch`` and two gets race its expiry (all due at the same instant);
    one getter is interrupted from a thread. Holders share one value, each
    alive while held, released once."""
    live = _Live(w, "value")
    holders = _Holders(live)
    late = Slot[AnyFiber]()

    @fx.gen
    def in_scope():
        m = yield from fx.RcMap.make(_str_lookup(live), idle_time_to_live="1 second")
        yield from holders.hold("first", m.get("a"))
        toucher = yield from fx.sleep("1 second").and_then(m.touch("a")).fork()
        late.set(
            (yield from fx.sleep("1 second").and_then(holders.hold("late", m.get("a"))).fork())
        )
        yield from fx.sleep("1 second")
        yield from holders.hold("on time", m.get("a"))
        yield from toucher.await_exit()
        yield from late.get().await_exit()

    w.fork(_virtual_time(w, fx.scoped(in_scope)))
    interrupt_from_thread(w, "interrupter", late)
    w.check(live.checks())
    w.check(holders.check)


def _rc_map_invalidate(w: World) -> None:
    """A holder keeps key ``a`` while another fiber invalidates it and a third
    (interrupted from a thread) gets it: the invalidated value lives until
    its holder lets go, the next get looks ``a`` up afresh, each value is
    released once."""
    live = _Live(w, "value", pause=True)
    getter = Slot[AnyFiber]()

    @fx.gen
    def in_scope():
        m = yield from fx.RcMap.make(_str_lookup(live))
        holder = yield from fx.scoped(
            m.get("a")
            .map(live.use("holder"))
            .and_then(fx.yield_now())
            .and_then(m.get("a"))
            .map(live.use("holder again"))
        ).fork()
        invalidator = yield from m.invalidate("a").fork()
        getter.set(
            (
                yield from fx.scoped(
                    m.get("a").map(live.use("getter")).and_then(fx.yield_now())
                ).fork()
            )
        )
        yield from holder.await_exit()
        yield from invalidator.await_exit()
        yield from getter.get().await_exit()

    w.fork(fx.scoped(in_scope))
    interrupt_from_thread(w, "interrupter", getter)
    w.check(live.checks())


# --- ScopedRef -----------------------------------------------------------------------------


def _scoped_ref(w: World) -> None:
    """Two fibers ``set`` a ScopedRef at once (one interrupted from a thread,
    so maybe while waiting for its turn), a third ``set`` fails after
    acquiring, and a reader reads meanwhile. A set
    acquires the new value before releasing the old (Effect's
    ``ScopedRef.set``), so one is alive at every moment until the ref's
    scope closes; a failed set keeps the old value; each value is released
    once."""
    live = _Live(w, "value", pause=True)
    setter = Slot[AnyFiber]()
    gaps: list[str] = []
    closing = [False]

    def released(n: int) -> None:
        if not closing[0] and not live.alive:
            gaps.append(f"value{n} was released before its successor was acquired")

    live.on_release = released

    def failing() -> fx.Effect[int, str, scope.Scope]:
        return live.acquire().and_then(fx.fail("no"))

    @fx.gen
    def in_scope():
        ref = yield from fx.ScopedRef.from_acquire(live.acquire())
        # Runs before the ref's own finalizer (last added, first run).
        yield from scope.add_finalizer(lambda _: fx.sync(lambda: closing.__setitem__(0, True)))
        first = yield from ref.set(live.acquire()).fork()
        setter.set((yield from ref.set(live.acquire()).fork()))
        bad = yield from ref.set(failing()).exit().fork()
        # As Effect's, ``set`` makes the new value current only once the old
        # one is released, so a read meanwhile may see the one going away.
        reads = fx.for_each(range(3), lambda _: ref.get().and_then(fx.yield_now()))
        reader = yield from reads.fork()
        yield from first.await_exit()
        yield from setter.get().await_exit()
        yield from bad.await_exit()
        yield from reader.await_exit()
        live.use("main, after the sets")(ref.get_unsafe())

    w.fork(fx.scoped(in_scope))
    interrupt_from_thread(w, "interrupter", setter)
    w.check(live.checks(most=2))
    w.check(lambda: gaps)


# --- Cache ---------------------------------------------------------------------------------


def _cache_dedupe(w: World) -> None:
    """Three fibers get one key of a Cache at once; the lookup sleeps. One
    getter is interrupted by a fiber, one from a thread. A lookup still
    awaited by anyone runs once and every successful getter sees one value;
    a lookup every getter left is interrupted and forgotten, so a later get
    looks the key up again and succeeds."""
    lookups: list[str] = []
    seen: list[tuple[str, int]] = []
    second = Slot[AnyFiber]()

    def lookup(_key: str) -> fx.Effect[int]:
        def start() -> int:
            lookups.append("started")
            return len(lookups)

        def finish(n: int) -> None:
            lookups[n - 1] = "done"

        return (
            fx.sync(start)
            .tap(lambda _: fx.sleep("1 second"))
            .tap(lambda n: fx.sync(lambda: finish(n)))
        )

    @fx.gen
    def main():
        cache = yield from fx.Cache.make(lookup, capacity=None)

        def get(who: str) -> fx.Effect[None]:
            return cache.get("k").map(lambda n: seen.append((who, n)))

        first = yield from get("first").fork()
        second.set((yield from get("second").fork()))
        third = yield from get("third").fork()
        yield from fx.yield_now()
        yield from first.interrupt()
        yield from second.get().await_exit()
        yield from third.await_exit()
        yield from get("after")

    w.fork(main)
    interrupt_from_thread(w, "interrupter", second)

    def check() -> Problems:
        # A lookup abandoned by every getter may still finish its work as
        # the interrupt arrives; it is forgotten either way, never served.
        values = {n for _, n in seen}
        if len(values) != 1 or lookups[min(values) - 1] != "done":
            return f"lookups {lookups}, getters saw {seen}"
        return None

    w.check(check)


def _cache_invalidate_refresh(w: World) -> None:
    """A getter, a ``refresh`` and an ``invalidate`` race on one key whose
    lookup yields; the getter is interrupted from a thread. Every value
    handed out is one a lookup produced, the getter and the refresh never
    hang, and a get afterwards gives the latest value cached."""
    results: list[tuple[str, int]] = []
    done: list[int] = []
    getter = Slot[AnyFiber]()

    def lookup(_key: str) -> fx.Effect[int]:
        def finish() -> int:
            done.append(len(done) + 1)
            return done[-1]

        return fx.yield_now().and_then(fx.sync(finish))

    @fx.gen
    def main():
        cache = yield from fx.Cache.make(lookup, capacity=None)
        getter.set((yield from cache.get("k").map(lambda n: results.append(("get", n))).fork()))
        refresher = (
            yield from cache.refresh("k").map(lambda n: results.append(("refresh", n))).fork()
        )
        invalidator = yield from fx.yield_now().and_then(cache.invalidate("k")).fork()
        yield from getter.get().await_exit()
        yield from refresher.await_exit()
        yield from invalidator.await_exit()
        n = yield from cache.get("k")
        results.append(("after", n))
        again = yield from cache.get("k")
        results.append(("again", again))

    w.fork(main)
    interrupt_from_thread(w, "interrupter", getter)

    def check() -> Problems:
        if any(n not in done for _, n in results):
            return f"handed out {results}, lookups finished {done}"
        after = dict(results)
        if after["after"] != after["again"]:
            return f"a cached key changed without a lookup: {results}"
        return None

    w.check(check)


def _cache_ttl_capacity(w: World) -> None:
    """A Cache of capacity 1 with a 1-second TTL: getters of ``a`` and ``b``
    (one interrupted from a thread), then ``a`` again as its entry expires.
    Each get returns its own key's value, from a lookup that finished; a key
    is looked up again only after it expired or was evicted."""
    results: list[tuple[str, str]] = []
    lookups: list[str] = []
    getter = Slot[AnyFiber]()

    def lookup(key: str) -> fx.Effect[str]:
        def finish() -> str:
            lookups.append(key)
            return f"{key}{len(lookups)}"

        return fx.yield_now().and_then(fx.sync(finish))

    @fx.gen
    def main():
        cache = yield from fx.Cache.make(lookup, capacity=1, time_to_live="1 second")

        def get(key: str) -> fx.Effect[None]:
            return cache.get(key).map(lambda v: results.append((key, v)))

        a = yield from get("a").fork()
        getter.set((yield from get("b").fork()))
        late = yield from fx.sleep("1 second").and_then(get("a")).fork()
        yield from a.await_exit()
        yield from getter.get().await_exit()
        yield from late.await_exit()
        yield from get("a")
        size = yield from cache.size()
        if size > 1:
            results.append(("size", str(size)))

    w.fork(_virtual_time(w, main))
    interrupt_from_thread(w, "interrupter", getter)

    def check() -> Problems:
        wrong = [(k, v) for k, v in results if k == "size" or not v.startswith(k)]
        if wrong:
            return f"results {results}"
        if len(lookups) > 4:
            return f"looked up {lookups} for 4 gets"
        return None

    w.check(check)


def _scoped_cache(w: World) -> None:
    """A ScopedCache of capacity 1 whose lookups acquire a resource: getters
    of ``a`` and ``b`` at once (one interrupted from a thread), an
    ``invalidate`` of ``a``, then the cache's scope closes. Each entry's
    scope closes exactly once, on eviction, invalidation or the close."""
    live = _Live(w, "value", pause=True)
    getter = Slot[AnyFiber]()

    @fx.gen
    def in_scope():
        cache = yield from fx.ScopedCache.make(_str_lookup(live), capacity=1)
        a = yield from cache.get("a").fork()
        getter.set((yield from cache.get("b").fork()))
        invalidator = yield from fx.yield_now().and_then(cache.invalidate("a")).fork()
        yield from a.await_exit()
        yield from getter.get().await_exit()
        yield from invalidator.await_exit()
        yield from cache.get("a")

    w.fork(fx.scoped(in_scope))
    interrupt_from_thread(w, "interrupter", getter)
    w.check(live.checks())


# --- Layer memoization -----------------------------------------------------------------------


class _Shared(fx.Tag[int]): ...


def _shared_layer(live: _Live) -> layer.Layer[_Shared]:
    return layer.effect(_Shared, live.acquire().tap(lambda _: fx.yield_now()))


def _memo_map_shared(w: World) -> None:
    """Two fibers build one layer with a shared MemoMap, each into its own
    scope; one is interrupted from a thread, maybe mid-build. Users at the
    same time share one build, released once when the last user's scope
    closes; the other user gets the build or, if its builder was
    interrupted, that interruption; nobody hangs. (As in Effect, the last
    user detaches the build before releasing it, so a user coming after may
    build anew while the old one is still being released.)"""
    live = _Live(w, "layer")
    holders = _Holders(live)
    first = Slot[AnyFiber]()
    second = Slot[AnyFiber]()
    shared = _shared_layer(live)
    memo = MemoMap()

    def get() -> fx.Effect[int, Never, scope.Scope]:
        built = scope.Scope().flat_map(lambda sc: shared.build_with_memo_map(memo, sc))
        return built.map(lambda ctx: ctx.get_unsafe(_Shared))

    @fx.gen
    def main():
        first.set((yield from holders.hold("first", get()).fork()))
        second.set((yield from holders.hold("second", get()).fork()))
        yield from first.get().await_exit()
        yield from second.get().await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", first)
    w.check(live.checks())
    w.check(holders.check)
    w.check(_success_or_interrupted("the second user", second))


def _memo_map_merge(w: World) -> None:
    """Two layers needing one shared layer, merged (built concurrently,
    sharing a memo map); the build is interrupted from a thread. The shared
    layer is built once and released once."""
    live = _Live(w, "layer")
    building = Slot[AnyFiber]()
    shared = _shared_layer(live)

    class A(fx.Tag[int]): ...

    class B(fx.Tag[int]): ...

    a = layer.effect(A, _Shared().tap(lambda _: fx.yield_now())).pipe(layer.provide(shared))
    b = layer.effect(B, _Shared()).pipe(layer.provide(shared))
    both = layer.merge(a, b)

    @fx.gen
    def main():
        building.set((yield from fx.scoped(both.build().and_then(fx.yield_now())).fork()))
        yield from building.get().await_exit()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", building)

    def check() -> Problems:
        if live.made > 1:
            return f"the shared layer was built {live.made} times in one build"
        return live.checks()()

    w.check(check)


# --- acquire_release and the interruptibility masks ----------------------------------------------


class _Regions:
    """Regions that must run to the end once entered: ``enter`` / ``leave``
    around a yield, so an interrupt that lands inside shows."""

    def __init__(self) -> None:
        self.inside: dict[str, int] = {}
        self.entered: list[str] = []
        self.left: list[str] = []

    def region(self, name: str) -> fx.Effect[None]:
        def enter() -> None:
            self.entered.append(name)

        def leave() -> None:
            self.left.append(name)

        return (
            fx.sync(enter)
            .and_then(fx.yield_now())
            .and_then(fx.yield_now())
            .and_then(fx.sync(leave))
        )

    def check(self) -> Problems:
        if sorted(self.entered) != sorted(self.left):
            return (
                f"interrupted inside a protected region: entered {self.entered}, left {self.left}"
            )
        return None


def _mask_restore(w: World) -> None:
    """``restore`` gives back the interruptibility from outside the mask: in
    an ``uninterruptible_mask`` nested inside an uninterruptible region it is
    the identity (the region stays protected), and an ``interruptible_mask``
    inside an uninterruptible region restores to uninterruptible. A fiber
    runs both, with interruptible yields between, and is interrupted by a
    fiber and from a thread: never inside a protected region."""
    regions = _Regions()
    victim = Slot[AnyFiber]()
    reached: list[str] = []

    nested = fx.uninterruptible_mask(
        lambda restore: regions.region("mask").and_then(restore(regions.region("restored")))
    ).uninterruptible()
    inner = fx.interruptible_mask(
        lambda restore: fx.yield_now().and_then(restore(regions.region("interruptible restored")))
    ).uninterruptible()
    double = fx.uninterruptible_mask(
        lambda outer: fx.uninterruptible_mask(
            lambda restore: restore(regions.region("double restored"))
        ).and_then(outer(fx.yield_now().map(lambda _: reached.append("outer restore"))))
    )

    @fx.gen
    def body():
        yield from nested
        yield from fx.yield_now()
        yield from inner
        yield from fx.yield_now()
        yield from double
        reached.append("end")

    @fx.gen
    def main():
        victim.set((yield from body.fork()))
        yield from fx.yield_now()
        yield from victim.get().interrupt()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", victim)
    w.check(regions.check)

    def check() -> Problems:
        # The outermost ``restore`` of ``double`` is interruptible again:
        # an interrupt sent before it must not let the fiber go on past it.
        ex = victim.get()._exit
        if "end" in reached and not isinstance(ex, Success):
            return f"reached the end but ended with {ex}"
        return None

    w.check(check)


def _mask_acquire_release(w: World) -> None:
    """``acquire_use_release`` and ``scope.acquire_release`` with acquires
    and releases that yield inside, the use sleeping; interrupted by a fiber
    and from a thread. Acquire and release are never interrupted inside;
    a release runs once exactly when its acquire finished."""
    regions = _Regions()
    victim = Slot[AnyFiber]()

    def counted(name: str) -> fx.Effect[None]:
        return regions.region(f"acquire {name}").and_then(w.bump(f"acquire {name}"))

    def release(name: str) -> fx.Effect[None]:
        return regions.region(f"release {name}").and_then(w.bump(f"release {name}"))

    aur = scope.acquire_use_release(
        counted("aur"), lambda _: fx.sleep("1 second"), lambda _, __: release("aur")
    )
    scoped_one = fx.scoped(
        scope.acquire_release(counted("scoped"), lambda _, __: release("scoped")).and_then(
            fx.sleep("1 second")
        )
    )

    @fx.gen
    def main():
        victim.set((yield from aur.and_then(scoped_one).fork()))
        yield from fx.yield_now()
        yield from victim.get().interrupt()

    w.fork(main)
    interrupt_from_thread(w, "interrupter", victim)
    w.check(regions.check)

    def check() -> Problems:
        wrong = [
            n
            for n in ("aur", "scoped")
            if w.counts[f"acquire {n}"] > 1 or w.counts[f"release {n}"] != w.counts[f"acquire {n}"]
        ]
        return f"unbalanced {wrong}: {dict(w.counts)}" if wrong else None

    w.check(check)


# --- Scope finalizers ---------------------------------------------------------------------------


def _scope_finalizers(strategy: scope.Strategy) -> Callable[[World], None]:
    def build(w: World) -> None:
        """One fiber adds finalizers to a scope (one dies, one fails, the
        others yield) while another closes it; a finalizer added once the
        scope is closing runs at once (Effect's ``addFinalizer``). The adder
        is interrupted from a thread. Every finalizer registered runs
        exactly once, whatever the others do."""
        added: list[str] = []
        adder = Slot[AnyFiber]()

        def finalizer(name: str) -> fx.Effect[None]:
            ran = w.bump(f"ran {name}")
            if name == "dies":
                return ran.and_then(fx.die(RuntimeError("finalizer died")))
            if name == "fails":
                return ran.and_then(fx.fail("finalizer failed")).or_die()
            return ran.and_then(fx.yield_now())

        def add(sc: scope.CloseableScope, name: str) -> fx.Effect[None]:
            return (
                sc.add_finalizer(lambda _: finalizer(name)).exit().map(lambda _: added.append(name))
            )

        @fx.gen
        def main():
            sc = yield from scope.make(strategy)
            names = ["first", "dies", "fails", "last"]
            adder.set(
                (
                    yield from fx.for_each(
                        names, lambda n: add(sc, n).and_then(fx.yield_now())
                    ).fork()
                )
            )
            closer = yield from fx.yield_now().and_then(sc.close(exit_void)).exit().fork()
            yield from adder.get().await_exit()
            yield from closer.await_exit()

        w.fork(main)
        interrupt_from_thread(w, "interrupter", adder)

        def check() -> Problems:
            ran = {k.removeprefix("ran "): v for k, v in w.counts.items() if k.startswith("ran ")}
            wrong = [n for n in added if ran.get(n) != 1]
            extra = [n for n, v in ran.items() if v > 1]
            if wrong or extra:
                return f"added {added}, ran {ran}"
            return None

        w.check(check)

    return build


SCENARIOS: list[Scenario] = [
    Scenario("pool_ttl_usage", _pool_ttl("usage"), timers="when_idle", runs=300),
    Scenario("pool_ttl_creation", _pool_ttl("creation"), timers="when_idle", runs=150),
    Scenario("pool_invalidate_idle", _pool_invalidate_idle, runs=300),
    Scenario("pool_shutdown_waiters", _pool_shutdown_waiters, runs=300),
    Scenario("pool_concurrency", _pool_concurrency, runs=300),
    Scenario("rc_ref_shared", _rc_ref_shared, runs=300),
    Scenario("rc_ref_idle_ttl", _rc_ref_idle_ttl, runs=300),
    Scenario("rc_ref_invalidate", _rc_ref_invalidate, runs=300),
    Scenario("rc_ref_acquire_interrupt", _rc_ref_acquire_interrupt, runs=300),
    Scenario("rc_map_shared", _rc_map_shared, runs=300),
    Scenario("rc_map_idle_ttl", _rc_map_idle_ttl, runs=300),
    Scenario("rc_map_invalidate", _rc_map_invalidate, runs=300),
    Scenario("scoped_ref", _scoped_ref, runs=300),
    Scenario("cache_dedupe", _cache_dedupe, runs=300),
    Scenario("cache_invalidate_refresh", _cache_invalidate_refresh, runs=300),
    Scenario("cache_ttl_capacity", _cache_ttl_capacity, runs=300),
    Scenario("scoped_cache", _scoped_cache, runs=300),
    Scenario("memo_map_shared", _memo_map_shared, runs=300),
    Scenario("memo_map_merge", _memo_map_merge, runs=300),
    Scenario("mask_restore", _mask_restore, runs=300),
    Scenario("mask_acquire_release", _mask_acquire_release, runs=300),
    Scenario("scope_finalizers_sequential", _scope_finalizers("sequential"), runs=300),
    Scenario("scope_finalizers_parallel", _scope_finalizers("parallel"), runs=300),
]
