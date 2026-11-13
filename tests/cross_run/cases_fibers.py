"""Cross-run cases for fibers and what holds them: a fiber awaited, observed or interrupted from
another run, ``FiberSet`` / ``FiberMap`` / ``FiberHandle`` fed by runs on several threads, and
``CloseableScope`` finalizers registered while another run closes the scope.

A fiber forked into a shared collection belongs to the run that forked it, and only that run
drives it (delivers its interrupt, finishes it), so each thread here keeps one run going while
its fibers live, as an app's long-lived runs on a thread pool do."""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from typing import Any

import pyfect as fx
from pyfect.exit import Success

from ._hammer import THREADS, Case, barrier, expect, on_threads

ROUNDS = 150
"""Rounds of the cases where one run's fiber ends while other runs wait on it."""

FORKS = 300
"""Fibers each thread forks into a shared collection."""

SETTLE = 20.0
"""Seconds the fibers replaced in a collection get to finish interrupting."""


def _child(rng: random.Random) -> fx.Effect[int]:
    """A fiber body that yields a few times, so it ends while others look at it."""

    @fx.gen
    def body():
        for _ in range(rng.randrange(4)):
            yield from fx.yield_now()
        return 1

    return body


def _awaited_from_other_runs(observe: bool) -> Callable[[], list[str]]:
    """Each round one thread's run forks a fiber and keeps going until it ends; the other
    threads wait for it from runs of their own (``await_exit``), or register an observer from
    plain code (``add_observer_unsafe``). Every waiter wakes, every observer runs once."""

    def run() -> list[str]:
        slot: list[fx.Fiber[int] | None] = [None]
        published = threading.Event()
        gate = barrier(THREADS, action=published.clear)
        calls = [0] * (ROUNDS * THREADS)
        count_lock = threading.Lock()
        exits: list[list[object]] = [[] for _ in range(ROUNDS)]

        def owner(r: int, rng: random.Random) -> fx.Effect[None]:
            @fx.gen
            def body():
                fiber = yield from _child(rng).fork()
                slot[0] = fiber
                published.set()
                yield from fiber.await_exit()

            return body

        def work(i: int) -> None:
            rng = random.Random(i)
            for r in range(ROUNDS):
                gate.wait()
                if i == 0:
                    fx.run_blocking(owner(r, rng))
                    continue
                published.wait()
                fiber = slot[0]
                assert fiber is not None
                if observe:
                    at = r * THREADS + i

                    def seen(_: object, at: int = at) -> None:
                        with count_lock:
                            calls[at] += 1

                    fiber.add_observer_unsafe(seen)
                else:
                    exits[r].append(fx.run_blocking(fiber.await_exit()))

        problems = on_threads(work)
        if observe:
            deadline = time.monotonic() + SETTLE
            while time.monotonic() < deadline and any(
                calls[r * THREADS + i] == 0 for r in range(ROUNDS) for i in range(1, THREADS)
            ):
                time.sleep(0.01)
            wrong = [n for r in range(ROUNDS) for n in calls[r * THREADS + 1 : (r + 1) * THREADS]]
            missed, twice = wrong.count(0), sum(1 for n in wrong if n > 1)
            problems += expect("observers never called", missed, 0)
            problems += expect("observers called twice", twice, 0)
        else:
            bad = [ex for round_exits in exits for ex in round_exits if ex != Success(1)]
            problems += expect("waiters that saw another exit", len(bad), 0)
        return problems

    return run


def _interrupted_from_other_runs() -> list[str]:
    """One run's fiber waits forever; another run interrupts it and waits for it to end."""
    slot: list[fx.Fiber[Any] | None] = [None]
    published = threading.Event()
    gate = barrier(2, action=published.clear)
    exits: list[fx.Exit[Any, Any]] = []

    @fx.gen
    def owner():
        fiber = yield from fx.never.fork()
        slot[0] = fiber
        published.set()
        exits.append((yield from fiber.await_exit()))

    def work(i: int) -> None:
        for _ in range(ROUNDS):
            gate.wait()
            if i == 0:
                fx.run_blocking(owner)
            else:
                published.wait()
                fiber = slot[0]
                assert fiber is not None
                fx.run_blocking(fiber.interrupt())

    problems = on_threads(work, threads=2)
    survived = [
        ex for ex in exits if not (isinstance(ex, fx.Failure) and ex.cause.has_interrupts_only)
    ]
    return problems + expect("fibers not interrupted", len(survived), 0)


def _scoped[T](make: fx.Effect[T, Any, fx.scope.Scope]) -> tuple[T, fx.scope.CloseableScope]:
    scope = fx.run_blocking(fx.scope.make())
    return fx.run_blocking(make.pipe(fx.scope.provide(scope))), scope


def _fork_into(
    fork: Callable[[int], fx.Effect[fx.Fiber[Any]]], closer: Callable[[], None] | None = None
) -> tuple[Callable[[], list[str]], list[list[fx.Fiber[Any]]]]:
    """Each thread's run forks ``FORKS`` fibers with ``fork(k)``, then keeps running until they
    have all ended; ``closer``, if given, runs on one more thread meanwhile. Returns a function
    that waits for the threads and gives their problems, and the fibers each thread forked."""
    forked: list[list[fx.Fiber[Any]]] = [[] for _ in range(THREADS)]
    workers = THREADS - (closer is not None)

    def work(i: int) -> None:
        if closer is not None and i == workers:
            time.sleep(0.005)
            closer()
            return

        @fx.gen
        def body():
            for k in range(FORKS):
                forked[i].append((yield from fork(i * FORKS + k)))
                if k % 7 == 0:
                    yield from fx.yield_now()
            for fiber in forked[i]:
                yield from fiber.await_exit()

        fx.run_blocking(body)

    problems: list[str] = []
    runner = threading.Thread(target=lambda: problems.extend(on_threads(work)), daemon=True)
    runner.start()

    def finish() -> list[str]:
        runner.join()
        return problems

    return finish, forked


def _fiber_set_close_race() -> list[str]:
    """Runs fork into a set while another run closes it: every fiber ends (interrupted, as
    the set closes or as it joins a closed set)."""
    fibers, scope = _scoped(fx.FiberSet[Any, Any].make())

    finish, _ = _fork_into(
        lambda _: fibers.run(fx.never),
        closer=lambda: fx.run_blocking(scope.close(Success(None))),
    )
    return finish()


def _fiber_set_members() -> list[str]:
    """Fibers that end on their own leave a set fed by several runs: it ends up empty."""
    fibers, scope = _scoped(fx.FiberSet[Any, Any].make())
    rng = random.Random(7)
    finish, _ = _fork_into(lambda _: fibers.run(_child(rng)))
    problems = finish()
    left = fx.run_blocking(fibers.size())
    fx.run_blocking(scope.close(Success(None)))
    return problems + expect("fibers left in the set", left, 0)


def _keyed_survivors(
    fork: Callable[[int], fx.Effect[fx.Fiber[Any]]],
    current: Callable[[], list[fx.Fiber[Any]]],
    close: Callable[[], None],
) -> list[str]:
    """Runs fork fibers that wait forever under shared keys, each replacing the one there: once
    the replaced ones have ended, the fibers still running are exactly the current ones."""
    finish, forked = _fork_into(fork)
    deadline = time.monotonic() + SETTLE
    while True:
        all_forked = all(len(fibers) == FORKS for fibers in forked)
        alive = {f for fibers in forked for f in fibers if f.poll_unsafe() is None}
        if (all_forked and len(alive) <= len(current())) or time.monotonic() > deadline:
            break
        time.sleep(0.01)
    kept = set(current())
    problems = expect("fibers running that the collection lost", len(alive - kept), 0)
    problems += expect("current fibers not running", len(kept - alive), 0)
    close()
    return problems + finish()


def _fiber_map_keys() -> list[str]:
    keys = 4
    fibers, scope = _scoped(fx.FiberMap[int, Any, Any].make())
    return _keyed_survivors(
        lambda k: fibers.run(k % keys, fx.never),
        lambda: [fiber for _, fiber in fibers],
        lambda: fx.run_blocking(scope.close(Success(None))),
    )


def _fiber_handle() -> list[str]:
    handle, scope = _scoped(fx.FiberHandle[Any, Any].make())
    return _keyed_survivors(
        lambda _: handle.run(fx.never),
        lambda: [f for f in [handle.get_unsafe()] if f is not None],
        lambda: fx.run_blocking(scope.close(Success(None))),
    )


def _scope_close_race(
    register: Callable[[fx.scope.CloseableScope, list[int], int], None],
) -> Callable[[], list[str]]:
    """Each round one run closes a scope while the other threads' runs register on it with
    ``register(scope, ran, at)``, which counts in ``ran[at]``: everything registered runs once,
    at the close or at once."""

    def run() -> list[str]:
        shared: list[fx.scope.CloseableScope] = [fx.scope.CloseableScope()]
        gate = barrier(THREADS, action=lambda: shared.__setitem__(0, fx.scope.CloseableScope()))
        ran = [0] * (ROUNDS * THREADS)

        def work(i: int) -> None:
            for r in range(ROUNDS):
                gate.wait()
                scope = shared[0]
                if i == 0:
                    fx.run_blocking(scope.close(Success(None)))
                else:
                    register(scope, ran, r * THREADS + i)

        problems = on_threads(work)
        wrong = [n for r in range(ROUNDS) for n in ran[r * THREADS + 1 : (r + 1) * THREADS]]
        return problems + expect(
            "registrations that did not run once", sum(n != 1 for n in wrong), 0
        )

    return run


def _add_finalizer(scope: fx.scope.CloseableScope, ran: list[int], at: int) -> None:
    def finalizer(_: object) -> fx.Effect[None]:
        def bump() -> None:
            ran[at] += 1

        return fx.sync(bump)

    fx.run_blocking(scope.add_finalizer(finalizer))


def _fork_in(scope: fx.scope.CloseableScope, ran: list[int], at: int) -> None:
    """A fiber forked into the scope is interrupted by the close, or at once if it was closed."""
    ex = fx.run_blocking(fx.scope.fork_in(fx.never, scope).flat_map(lambda f: f.await_exit()))
    ran[at] += isinstance(ex, fx.Failure) and ex.cause.has_interrupts_only


def _fork_scope(scope: fx.scope.CloseableScope, ran: list[int], at: int) -> None:
    """A child scope of a scope closing on another thread is closed with it, or at once."""
    child = fx.run_blocking(scope.fork())
    deadline = time.monotonic() + SETTLE
    while not child.is_closed and time.monotonic() < deadline:
        time.sleep(0.0005)
    ran[at] += child.is_closed


CASES = [
    Case("Fiber.await_exit from other runs", (fx.Fiber,), _awaited_from_other_runs(observe=False)),
    Case(
        "Fiber.add_observer_unsafe from other threads",
        (fx.Fiber,),
        _awaited_from_other_runs(observe=True),
    ),
    Case("Fiber.interrupt from another run", (fx.Fiber,), _interrupted_from_other_runs),
    Case("FiberSet closed while runs fork into it", (fx.FiberSet,), _fiber_set_close_race),
    Case("FiberSet members leave from several runs", (fx.FiberSet,), _fiber_set_members),
    Case("FiberMap keys replaced from several runs", (fx.FiberMap,), _fiber_map_keys),
    Case("FiberHandle replaced from several runs", (fx.FiberHandle,), _fiber_handle),
    Case(
        "CloseableScope.add_finalizer while another run closes it",
        (fx.scope.CloseableScope,),
        _scope_close_race(_add_finalizer),
    ),
    Case(
        "fork_in a scope another run closes",
        (fx.scope.CloseableScope,),
        _scope_close_race(_fork_in),
    ),
    Case(
        "CloseableScope.fork while another run closes it",
        (fx.scope.CloseableScope,),
        _scope_close_race(_fork_scope),
    ),
]
