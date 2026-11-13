"""Cross-run cases for the resource-sharing primitives: pools, caches, ``fx.cached``, RcRef,
RcMap, ScopedRef, LayerMap, ScopedCache and request caches.

Those that live in a scope are made by an owner run on a thread of its own that stays open
while the other threads use them, as an app's main run or a ``ManagedRuntime`` layer would."""

from __future__ import annotations

import threading
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import pyfect as fx
from pyfect import layer
from pyfect.batching import Entry

from ._hammer import DEADLINE, THREADS, Case, expect, on_threads

N = 300
"""Operations per thread, each in a run of its own."""

KEYS = 16


class _Live:
    """Resources acquired and not yet released, numbered in acquisition order."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.live: set[int] = set()
        self.acquired = 0
        self.released = 0
        self.dead_uses = 0
        self.most_live = 0

    def _add(self) -> int:
        with self._lock:
            self.acquired += 1
            self.live.add(self.acquired)
            self.most_live = max(self.most_live, len(self.live))
            return self.acquired

    def _remove(self, n: int) -> None:
        with self._lock:
            self.released += 1
            self.live.discard(n)

    def acquire(self) -> fx.Effect[int, Any, fx.Scope]:
        return fx.acquire_release(fx.sync(self._add), lambda n, _: fx.sync(lambda: self._remove(n)))

    def use(self, n: int) -> fx.Effect[None]:
        """Note a use of ``n``, which must be live, across a yield."""

        def check() -> None:
            with self._lock:
                if n not in self.live:
                    self.dead_uses += 1

        return fx.sync(check).and_then(fx.yield_now()).and_then(fx.sync(check))

    def balanced(self) -> list[str]:
        return (
            expect("uses of a released resource", self.dead_uses, 0)
            + expect("resources still live", sorted(self.live), [])
            + expect("releases", self.released, self.acquired)
        )


def _owned[T](make: fx.Effect[T, Any, fx.Scope], go: Callable[[T], list[str]]) -> list[str]:
    """``go(value)`` while an owner run on its own thread holds the scope ``make`` ran in;
    then the owner closes it."""
    ready = threading.Event()
    made: list[T] = []
    stop = fx.Latch()

    def keep(value: T) -> fx.Effect[None]:
        def store() -> None:
            made.append(value)
            ready.set()

        return fx.sync(store)

    def owner() -> None:
        fx.run_blocking(fx.scoped(make.flat_map(keep).and_then(stop.wait())).or_die())

    thread = threading.Thread(target=owner, name="cross-run-owner", daemon=True)
    thread.start()
    if not ready.wait(DEADLINE):
        return ["the owner run never made the shared value"]
    try:
        problems = go(made[0])
    finally:
        fx.run_blocking(stop.open())
        thread.join(DEADLINE)
    return problems + (["the owner run hung closing its scope"] if thread.is_alive() else [])


def _exclusive_uses(
    live: _Live,
) -> tuple[Callable[[int], fx.Effect[None]], Callable[[], list[str]]]:
    """A use of a pooled item that checks nobody else uses it meanwhile."""
    lock = threading.Lock()
    busy: set[int] = set()
    overlaps = [0]
    uses = [0]

    def enter(n: int) -> None:
        with lock:
            uses[0] += 1
            if n in busy:
                overlaps[0] += 1
            busy.add(n)

    def leave(n: int) -> None:
        with lock:
            busy.discard(n)

    def use(n: int) -> fx.Effect[None]:
        return fx.sync(lambda: enter(n)).and_then(live.use(n)).and_then(fx.sync(lambda: leave(n)))

    def report() -> list[str]:
        return expect("uses", uses[0], THREADS * N) + expect("overlapping uses", overlaps[0], 0)

    return use, report


def _pool_case(
    make: Callable[[fx.Effect[int, Any, fx.Scope]], fx.Effect[fx.Pool[int], Any, fx.Scope]],
    most: int,
    *,
    scoped_get: bool = False,
) -> Callable[[], list[str]]:
    def run() -> list[str]:
        live = _Live()
        use, report = _exclusive_uses(live)

        def go(pool: fx.Pool[int]) -> list[str]:
            borrow: fx.Effect[None] = (
                fx.scoped(pool.get().flat_map(use)) if scoped_get else pool.use(use)
            )

            def work(_: int) -> None:
                for _ in range(N):
                    fx.run_blocking(borrow)

            return on_threads(work) + report()

        problems = _owned(make(live.acquire()), go)
        return (
            problems
            + live.balanced()
            + (
                [f"{live.most_live} items live at once, at most {most}"]
                if live.most_live > most
                else []
            )
        )

    return run


def _cache_case() -> list[str]:
    looked_up: Counter[int] = Counter()
    lock = threading.Lock()

    def lookup(key: int) -> fx.Effect[int]:
        def count() -> int:
            with lock:
                looked_up[key] += 1
            return key * 10

        return fx.sync(count).flat_map(lambda v: fx.yield_now().as_(v))

    cache = fx.run_blocking(fx.Cache.make(lookup, capacity=None))
    wrong: list[int] = []

    def work(i: int) -> None:
        for k in range(N):
            key = (i + k) % KEYS
            if fx.run_blocking(cache.get(key)) != key * 10:
                wrong.append(key)

    problems = on_threads(work)
    twice = sorted(key for key, n in looked_up.items() if n > 1)
    return problems + expect("keys looked up twice", twice, []) + expect("wrong values", wrong, [])


def _scoped_cache_case() -> list[str]:
    live = _Live()
    looked_up: Counter[int] = Counter()
    lock = threading.Lock()

    def lookup(key: int) -> fx.Effect[int, Any, fx.Scope]:
        def count() -> None:
            with lock:
                looked_up[key] += 1

        return fx.sync(count).and_then(live.acquire())

    def go(cache: fx.ScopedCache[int, int]) -> list[str]:
        def work(i: int) -> None:
            for k in range(N):
                fx.run_blocking(cache.get((i + k) % KEYS).flat_map(live.use))

        twice = lambda: sorted(key for key, n in looked_up.items() if n > 1)  # noqa: E731
        problems = on_threads(work)
        return problems + expect("keys looked up twice", twice(), [])

    return _owned(fx.ScopedCache.make(lookup, capacity=None), go) + live.balanced()


def _memoized_case() -> list[str]:
    runs = [0]
    lock = threading.Lock()

    def once() -> int:
        with lock:
            runs[0] += 1
        return 7

    rounds = 50
    problems: list[str] = []
    for _ in range(rounds):
        memo = fx.run_blocking(fx.sync(once).flat_map(lambda v: fx.yield_now().as_(v)).cached())
        got: list[int] = []

        def work(_: int, memo: fx.Effect[int] = memo, got: list[int] = got) -> None:
            got.extend(fx.run_blocking(memo) for _ in range(5))

        problems += on_threads(work)
        if set(got) != {7}:
            problems.append(f"values {sorted(set(got))}")
        if problems:
            break
    return problems + expect("runs of the cached effect", runs[0], rounds)


def _rc_ref_case(idle: str | None) -> Callable[[], list[str]]:
    def run() -> list[str]:
        live = _Live()

        def go(ref: fx.RcRef[int]) -> list[str]:
            def work(_: int) -> None:
                for _ in range(N):
                    fx.run_blocking(fx.scoped(ref.get().flat_map(live.use)))

            return on_threads(work)

        made = fx.RcRef.make(live.acquire(), idle_time_to_live=idle)
        problems = _owned(made, go) + live.balanced()
        return problems + (
            [f"{live.most_live} resources live at once"] if live.most_live > 2 else []
        )

    return run


def _rc_map_case(idle: str | None) -> Callable[[], list[str]]:
    def run() -> list[str]:
        live = _Live()
        keys: dict[int, set[int]] = {}
        lock = threading.Lock()

        def lookup(key: int) -> fx.Effect[int, Any, fx.Scope]:
            def note(n: int) -> int:
                with lock:
                    keys.setdefault(key, set()).add(n)
                return n

            return live.acquire().map(note)

        def go(rc_map: fx.RcMap[int, int]) -> list[str]:
            def work(i: int) -> None:
                for k in range(N):
                    fx.run_blocking(fx.scoped(rc_map.get((i + k) % 4).flat_map(live.use)))

            return on_threads(work)

        made = fx.RcMap.make(lookup, idle_time_to_live=idle)
        return _owned(made, go) + live.balanced()

    return run


def _scoped_ref_case() -> list[str]:
    """Sets race gets. ``get`` does not hold the value (as in Effect), so a set may release
    it while in use; each value set is released once, and the last one is live."""
    live = _Live()

    def go(ref: fx.ScopedRef[int]) -> list[str]:
        def work(i: int) -> None:
            for k in range(N):
                if (i + k) % 3 == 0:
                    fx.run_blocking(ref.set(live.acquire()))
                else:
                    fx.run_blocking(ref.get())

        problems = on_threads(work)
        current = fx.run_blocking(ref.get())
        return problems + expect("resources live", sorted(live.live), [current])

    problems = _owned(fx.ScopedRef.from_acquire(live.acquire()), go)
    return problems + live.balanced()


class _Tenant(fx.Tag[int]):
    pass


def _layer_map_case() -> list[str]:
    live = _Live()
    built: Counter[int] = Counter()
    lock = threading.Lock()

    def build(key: int) -> fx.Layer[_Tenant]:
        def count(n: int) -> int:
            with lock:
                built[key] += 1
            return n

        return layer.effect(_Tenant, live.acquire().map(count))

    def go(layer_map: fx.LayerMap[int, _Tenant]) -> list[str]:
        def work(i: int) -> None:
            for k in range(N):
                key = (i + k) % 4
                eff = layer_map.context_effect(key).flat_map(
                    lambda ctx: live.use(ctx.get_unsafe(_Tenant))
                )
                fx.run_blocking(fx.scoped(eff))

        return on_threads(work)

    return _owned(fx.LayerMap.make(build), go) + live.balanced()


@dataclass(frozen=True)
class _Get(fx.Request[int]):
    id: int


def _request_cache_case() -> list[str]:
    calls: Counter[int] = Counter()
    lock = threading.Lock()

    def run_all(entries: Sequence[Entry[_Get]]) -> fx.Effect[None]:
        def go() -> None:
            for entry in entries:
                with lock:
                    calls[entry.request.id] += 1
                entry.complete_unsafe(fx.Success(entry.request.id))

        return fx.yield_now().and_then(fx.sync(go))

    resolver = fx.run_blocking(fx.RequestResolver(run_all).with_cache(capacity=1000))
    wrong: list[int] = []

    def work(i: int) -> None:
        for k in range(N):
            key = (i + k) % KEYS
            if fx.run_blocking(fx.request(_Get(key), resolver)) != key:
                wrong.append(key)

    problems = on_threads(work)
    twice = sorted(key for key, n in calls.items() if n > 1)
    return problems + expect("requests run twice", twice, []) + expect("wrong answers", wrong, [])


CASES = [
    Case("Pool.make use", (fx.Pool,), _pool_case(lambda acquire: fx.Pool.make(acquire, size=2), 2)),
    Case(
        "Pool.make get",
        (fx.Pool,),
        _pool_case(lambda acquire: fx.Pool.make(acquire, size=2), 2, scoped_get=True),
    ),
    Case(
        "Pool.make_with_ttl growing",
        (fx.Pool,),
        _pool_case(
            lambda acquire: fx.Pool.make_with_ttl(acquire, min=0, max=3, time_to_live="1 minute"), 3
        ),
    ),
    Case("Cache.get", (fx.Cache,), _cache_case),
    Case("ScopedCache.get", (fx.ScopedCache,), _scoped_cache_case),
    Case("fx.cached", (), _memoized_case),
    Case("RcRef.get", (fx.RcRef,), _rc_ref_case(None)),
    Case("RcRef.get with an idle time to live", (fx.RcRef,), _rc_ref_case("1 minute")),
    Case("RcMap.get", (fx.RcMap,), _rc_map_case(None)),
    Case("RcMap.get with an idle time to live", (fx.RcMap,), _rc_map_case("1 minute")),
    Case("ScopedRef.set", (fx.ScopedRef,), _scoped_ref_case),
    Case("LayerMap.context_effect", (fx.LayerMap,), _layer_map_case),
    Case("RequestResolver.with_cache", (fx.RequestResolver,), _request_cache_case),
]
