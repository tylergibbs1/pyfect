"""Cross-run cases for the core shared-state primitives: refs, transactions, Deferred, Latch,
Semaphore and Queue."""

from __future__ import annotations

import random
import threading
from collections import Counter
from collections.abc import Callable
from typing import Any

import pyfect as fx
from pyfect.option import Some

from ._hammer import THREADS, Case, barrier, expect, on_threads

N = 1500
"""Operations per thread, each in a run of its own."""

ROUNDS = 150
"""Rounds of the wake-up cases: waiters park in their runs, others wake them from theirs."""


def _increments[T](
    what: str,
    make: Callable[[], T],
    bump: Callable[[T], fx.Effect[Any]],
    read: Callable[[T], fx.Effect[int]],
) -> Callable[[], list[str]]:
    """Every thread bumps one shared counter ``N`` times, one run per bump."""

    def run() -> list[str]:
        shared = make()

        def work(_: int) -> None:
            for _ in range(N):
                fx.run_blocking(bump(shared))

        problems = on_threads(work)
        held = fx.run_blocking(read(shared))
        return problems + expect(f"{what} after {THREADS * N} increments", held, THREADS * N)

    return run


def _ref_mixed(ref: fx.Ref[int]) -> fx.Effect[Any]:
    """One of Ref's read-modify-write operations, each adding 1."""
    ops: list[Callable[[], fx.Effect[Any]]] = [
        lambda: ref.update(lambda v: v + 1),
        lambda: ref.update_and_get(lambda v: v + 1),
        lambda: ref.get_and_update(lambda v: v + 1),
        lambda: ref.modify(lambda v: (None, v + 1)),
        lambda: ref.update_some(lambda v: Some(v + 1)),
        lambda: ref.update_some_and_get(lambda v: Some(v + 1)),
        lambda: ref.get_and_update_some(lambda v: Some(v + 1)),
        lambda: ref.modify_some(lambda v: (None, Some(v + 1))),
    ]
    return random.choice(ops)()


def _ref_get_and_set() -> list[str]:
    """Each value set is handed back exactly once by a later ``get_and_set``."""
    ref = fx.Ref(-1)
    seen: list[list[int]] = [[] for _ in range(THREADS)]

    def work(i: int) -> None:
        for k in range(N):
            seen[i].append(fx.run_blocking(ref.get_and_set(i * N + k)))

    problems = on_threads(work)
    returned = Counter(v for values in seen for v in values)
    returned[ref.get_unsafe()] += 1
    twice = [v for v, n in returned.items() if n > 1]
    return problems + ([f"get_and_set handed back {len(twice)} values twice"] if twice else [])


def _tx_transfer() -> list[str]:
    """Transfers between two TxRefs keep their sum; a committed read of both sees that sum."""
    total = 1000
    a, b = fx.TxRef(total), fx.TxRef(0)
    sums: list[int] = []

    def move(n: int) -> fx.Effect[None]:
        return fx.tx(a.update(lambda v: v - n).and_then(b.update(lambda v: v + n)))

    read = fx.tx(a.get().zip_with(b.get(), lambda x, y: x + y))

    def work(i: int) -> None:
        rng = random.Random(i)
        for _ in range(N // 2):
            fx.run_blocking(move(rng.randint(-5, 5)))
            sums.append(fx.run_blocking(read))

    problems = on_threads(work)
    torn = [s for s in sums if s != total]
    return (
        problems
        + expect("a + b at the end", fx.run_blocking(read), total)
        + ([f"{len(torn)} committed reads saw a + b != {total}"] if torn else [])
    )


def _rounds(
    setup: Callable[[], Any],
    waiter: Callable[[Any], fx.Effect[Any]],
    waker: Callable[[Any], fx.Effect[Any]],
    *,
    wakers: int = 1,
    check: Callable[[Any, list[Any], list[Any]], list[str]] | None = None,
) -> Callable[[], list[str]]:
    """``ROUNDS`` rounds: each round's shared value comes from ``setup``; ``wakers`` threads
    run ``waker`` on it while the others run ``waiter``, each in a run of its own, released
    together. A waiter never woken hangs the case."""

    def run() -> list[str]:
        shared: list[Any] = [None]
        gate = barrier(THREADS, action=lambda: shared.__setitem__(0, setup()))
        waited: list[list[Any]] = [[] for _ in range(ROUNDS)]
        woke: list[list[Any]] = [[] for _ in range(ROUNDS)]
        problems: list[str] = []

        def work(i: int) -> None:
            for r in range(ROUNDS):
                gate.wait()
                if i < wakers:
                    woke[r].append(fx.run_blocking(waker(shared[0])))
                else:
                    waited[r].append(fx.run_blocking(waiter(shared[0])))

        problems += on_threads(work)
        if check is not None and not problems:
            for r in range(ROUNDS):
                problems += check(shared[0], waited[r], woke[r])
        return problems

    return run


def _deferred_check(_: object, waited: list[int], woke: list[bool]) -> list[str]:
    won = woke.count(True)
    return expect("completions that won", won, 1) + expect(
        "waiters that saw one value", len(set(waited)), 1
    )


def _semaphore_exclusive() -> list[str]:
    """A one-permit semaphore lets one fiber in at a time, across runs."""
    semaphore = fx.Semaphore(1)
    box = [0]
    inside = [0]
    overlaps = [0]

    def critical() -> None:
        inside[0] += 1
        if inside[0] != 1:
            overlaps[0] += 1
        value = box[0]
        box[0] = value + 1
        inside[0] -= 1

    guarded = semaphore.with_permits(fx.sync(critical))

    def work(_: int) -> None:
        for _ in range(N):
            fx.run_blocking(guarded)

    problems = on_threads(work)
    return (
        problems
        + expect("entries", box[0], THREADS * N)
        + expect("overlapping entries", overlaps[0], 0)
        + expect("permits free at the end", fx.run_blocking(semaphore.available), 1)
    )


def _queue_case(make: Callable[[], fx.Effect[fx.Queue[int]]]) -> Callable[[], list[str]]:
    """Half the threads offer distinct items, half take them, one run per item: every item is
    taken exactly once."""

    def run() -> list[str]:
        queue = fx.run_blocking(make())
        producers = THREADS // 2
        taken: list[list[int]] = [[] for _ in range(THREADS)]

        def work(i: int) -> None:
            if i < producers:
                for k in range(N):
                    fx.run_blocking(queue.offer(i * N + k))
            else:
                for _ in range(N):
                    taken[i].append(fx.run_blocking(queue.take()))

        problems = on_threads(work)
        counts = Counter(v for values in taken for v in values)
        twice = [v for v, n in counts.items() if n > 1]
        return (
            problems
            + expect("items taken", sum(counts.values()), producers * N)
            + ([f"{len(twice)} items taken twice"] if twice else [])
        )

    return run


def _tx_waiter(ref: fx.TxRef[int]) -> fx.Effect[int]:
    return fx.tx(ref.get().flat_map(lambda v: fx.tx_retry if v == 0 else fx.succeed(v)))


CASES = [
    Case(
        "Ref read-modify-write",
        (fx.Ref,),
        _increments("Ref", lambda: fx.Ref[int](0), _ref_mixed, lambda ref: ref.get()),
    ),
    Case("Ref.get_and_set", (fx.Ref,), _ref_get_and_set),
    Case(
        "TxRef.update in fx.tx",
        (fx.TxRef,),
        _increments(
            "TxRef",
            lambda: fx.TxRef[int](0),
            lambda ref: fx.tx(ref.update(lambda v: v + 1)),
            lambda ref: ref.get(),
        ),
    ),
    Case(
        "TxRef.update without fx.tx",
        (fx.TxRef,),
        _increments(
            "TxRef",
            lambda: fx.TxRef[int](0),
            lambda ref: ref.update(lambda v: v + 1),
            lambda ref: ref.get(),
        ),
    ),
    Case("TxRef transfers", (fx.TxRef,), _tx_transfer),
    Case(
        "tx_retry woken from another run",
        (fx.TxRef,),
        _rounds(lambda: fx.TxRef[int](0), _tx_waiter, lambda ref: fx.tx(ref.set(1))),
    ),
    Case(
        "SynchronizedRef.update",
        (fx.SynchronizedRef,),
        _increments(
            "SynchronizedRef",
            lambda: fx.run_blocking(fx.SynchronizedRef[int].make(0)),
            lambda ref: ref.update(lambda v: v + 1),
            lambda ref: ref.get(),
        ),
    ),
    Case(
        "SynchronizedRef.update_effect",
        (fx.SynchronizedRef,),
        _increments(
            "SynchronizedRef",
            lambda: fx.run_blocking(fx.SynchronizedRef[int].make(0)),
            lambda ref: ref.update_effect(lambda v: fx.succeed(v + 1)),
            lambda ref: ref.get(),
        ),
    ),
    Case(
        "SubscriptionRef.update",
        (fx.SubscriptionRef,),
        _increments(
            "SubscriptionRef",
            lambda: fx.run_blocking(fx.SubscriptionRef[int].make(0)),
            lambda ref: ref.update(lambda v: v + 1),
            lambda ref: ref.get(),
        ),
    ),
    Case(
        "Deferred completed and awaited from several runs",
        (fx.Deferred,),
        _rounds(
            fx.Deferred[int],
            lambda d: d.wait(),
            lambda d: d.succeed(threading.get_ident()),
            wakers=THREADS // 2,
            check=_deferred_check,
        ),
    ),
    Case(
        "Latch opened from another run",
        (fx.Latch,),
        _rounds(fx.Latch, lambda latch: latch.wait(), lambda latch: latch.open()),
    ),
    Case("Semaphore mutual exclusion", (fx.Semaphore,), _semaphore_exclusive),
    Case(
        "Semaphore released from another run",
        (fx.Semaphore,),
        _rounds(lambda: fx.Semaphore(0), lambda s: s.take(1), lambda s: s.release(THREADS - 1)),
    ),
    Case("Queue.unbounded", (fx.Queue,), _queue_case(fx.Queue[int].unbounded)),
    Case("Queue.bounded(2)", (fx.Queue,), _queue_case(lambda: fx.Queue[int].bounded(2))),
    Case("Queue.bounded(0)", (fx.Queue,), _queue_case(lambda: fx.Queue[int].bounded(0))),
]
