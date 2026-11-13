"""Cross-run cases for ``PubSub`` and what is built on it (``SubscriptionRef``): subscribers
each in a run of their own take while publishers on other threads publish, one run per
publish."""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from typing import Any, Never

import pyfect as fx
from pyfect.pubsub import BackPressureStrategy

from ._hammer import THREADS, Case, expect, on_threads

N = 400
"""Messages per publisher."""

PUBLISHERS = THREADS // 2


def _fan_out(
    make: Callable[[], fx.Effect[fx.PubSub[int | None]]],
    *,
    batch: int = 1,
    complete: bool = True,
) -> Callable[[], list[str]]:
    """Half the threads subscribe, the others publish ``N`` distinct messages each (``batch``
    at a time with ``publish_all``); the last publisher to finish ends the hub with ``None``.
    Every subscriber reads each publisher's messages in order, none twice; with ``complete``
    every message published (``publish`` returned ``True``) reaches every subscriber."""

    def run() -> list[str]:
        pubsub = fx.run_blocking(make())
        ready = threading.Barrier(THREADS)
        lock = threading.Lock()
        finished = [0]
        published: list[list[int]] = [[] for _ in range(PUBLISHERS)]
        seen: list[list[int]] = [[] for _ in range(THREADS)]

        def publish(i: int) -> None:
            ready.wait()
            for k in range(0, N, batch):
                items = [i * N + j for j in range(k, min(k + batch, N))]
                if batch == 1:
                    ok = fx.run_blocking(pubsub.publish(items[0]))
                else:
                    ok = fx.run_blocking(pubsub.publish_all(items))
                if ok:
                    published[i].extend(items)
            with lock:
                finished[0] += 1
                last = finished[0] == PUBLISHERS
            if last:
                fx.run_blocking(pubsub.end(None))

        def subscribe(i: int) -> None:
            @fx.gen
            def body():
                subscription = yield from pubsub.subscribe()
                yield from fx.blocking(ready.wait)
                while (message := (yield from subscription.take())) is not None:
                    seen[i].append(message)

            fx.run_blocking(fx.scoped(body))

        def work(i: int) -> None:
            (publish if i < PUBLISHERS else subscribe)(i)

        problems = on_threads(work)
        if problems:
            return problems
        everything = sorted(m for messages in published for m in messages)
        for i in range(PUBLISHERS, THREADS):
            got = seen[i]
            if len(set(got)) != len(got):
                problems.append(f"subscriber {i} read {len(got) - len(set(got))} messages twice")
            for p in range(PUBLISHERS):
                mine = [m for m in got if m // N == p]
                if mine != sorted(mine):
                    problems.append(f"subscriber {i} read publisher {p}'s messages out of order")
            if complete:
                problems += expect(f"subscriber {i}'s messages", sorted(got), everything)
        return problems

    return run


def _read_some(pubsub: fx.PubSub[int]) -> fx.Effect[Sequence[int], Never, fx.Scope]:
    return pubsub.subscribe().flat_map(lambda subscription: subscription.take_up_to(4))


def _shutdown_race() -> list[str]:
    """Publishers park on a full hub, a subscriber reads, and another run shuts the hub
    down: every run ends (publishers interrupted or done), none hangs."""
    rounds = 100
    shared: list[Any] = [None]
    gate = threading.Barrier(
        THREADS, action=lambda: shared.__setitem__(0, fx.run_blocking(fx.PubSub[int].bounded(1)))
    )
    outcomes: list[str] = []

    def work(i: int) -> None:
        for _ in range(rounds):
            gate.wait()
            pubsub: fx.PubSub[int] = shared[0]
            if i == 0:
                fx.run_blocking(pubsub.shutdown())
            elif i == 1:
                fx.run_blocking_exit(fx.scoped(_read_some(pubsub)))
            else:
                ex = fx.run_blocking_exit(pubsub.publish_all([i, i]))
                if not isinstance(ex, fx.Success) and not ex.cause.has_interrupts_only:
                    outcomes.append(f"publisher {i}: {ex}")

    return on_threads(work) + outcomes


def _subscription_ref_changes() -> list[str]:
    """Runs on other threads update a ``SubscriptionRef``; each subscriber, in a run of its
    own, reads every value from 0 to the last, in order, once."""
    ref = fx.run_blocking(fx.SubscriptionRef[int].make(0))
    updaters = PUBLISHERS
    each = N
    total = updaters * each
    ready = threading.Barrier(THREADS)
    seen: list[list[int]] = [[] for _ in range(THREADS)]

    def work(i: int) -> None:
        if i < updaters:
            ready.wait()
            for _ in range(each):
                fx.run_blocking(ref.update(lambda v: v + 1))
            return

        @fx.gen
        def body():
            subscription = yield from ref.subscribe()
            yield from fx.blocking(ready.wait)
            while True:
                value = yield from subscription.take()
                seen[i].append(value)
                if value == total:
                    return

        fx.run_blocking(fx.scoped(body))

    problems = on_threads(work)
    for i in range(updaters, THREADS):
        got: Sequence[int] = seen[i]
        problems += expect(f"subscriber {i}'s values", list(got), list(range(total + 1)))
    return problems


CASES: list[Case] = [
    Case("PubSub.unbounded", (fx.PubSub,), _fan_out(fx.PubSub[int | None].unbounded)),
    Case(
        "PubSub.unbounded(replay=4)",
        (fx.PubSub,),
        _fan_out(lambda: fx.PubSub[int | None].unbounded(replay=4)),
    ),
    Case(
        "PubSub.bounded(2)",
        (fx.PubSub, BackPressureStrategy),
        _fan_out(lambda: fx.PubSub[int | None].bounded(2)),
    ),
    Case(
        "PubSub.bounded(2).publish_all",
        (fx.PubSub,),
        _fan_out(lambda: fx.PubSub[int | None].bounded(2), batch=3),
    ),
    Case("PubSub.dropping(4)", (fx.PubSub,), _fan_out(lambda: fx.PubSub[int | None].dropping(4))),
    Case(
        "PubSub.sliding(4)",
        (fx.PubSub,),
        _fan_out(lambda: fx.PubSub[int | None].sliding(4), complete=False),
    ),
    Case("PubSub.shutdown racing publishers", (fx.PubSub,), _shutdown_race),
    Case("SubscriptionRef.subscribe", (fx.SubscriptionRef,), _subscription_ref_changes),
]
