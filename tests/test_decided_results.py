"""A result a step has decided is never lost (CLAUDE.md runtime rules).

Effect's ``Queue.test.ts`` "take interrupted at a yield keeps its message",
generalized: every operation that claims state (takes an item, applies an
update, grabs a permit) runs with every step budget and prefix length, and
is interrupted at each point where it gives the scheduler a turn (a yield
or a step-budget pause). Whatever it claimed must reach its own
continuation, or stay where it was. A primitive breaks this by returning
the claimed value as an effect for a later step (``_Succeed``) instead of
an ``Exit``, by claiming in one step and returning in another, or by
claiming in a frame not marked ``claims``. The loop may pause before a
continuation only every ``_INLINE_STEPS`` steps, which a sweep rarely
lines up with a frame's exit, so each case also runs with every
continuation a possible pause.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest

import pyfect as fx
import pyfect._fiber as fiber_module
from pyfect._wake_tracking import WakeTracker
from pyfect.duration import Seconds
from pyfect.scheduler import Cancel, Scheduler, Task

_BUDGETS = (1, 2, 3, 31, 32, 33)
_PREFIXES = range(0, 36)


class _InterruptAt:
    """The run's scheduler, except that the ``at``-th task scheduled for
    the target is preceded by an interrupt of the target, sent from the
    scheduler's thread (so it is delivered at once)."""

    def __init__(self, inner: Scheduler, at: int) -> None:
        self.inner = inner
        self.at = at
        self.seen = 0
        self.target: fx.Fiber[Any, Any] | None = None
        self.fired = False

    def schedule(self, task: Task) -> None:
        self.seen += 1
        target = self.target
        if self.seen == self.at and target is not None:
            self.fired = True
            self.inner.schedule(lambda: target.interrupt_as_unsafe(None))
        self.inner.schedule(task)

    def call_later(self, delay: Seconds, task: Task, *, daemon: bool = False) -> Cancel:
        return self.inner.call_later(delay, task, daemon=daemon)

    def track(self, tracker: WakeTracker, f: Callable[[], None]) -> None:
        self.inner.track(tracker, f)


@dataclass
class _Case:
    """``setup`` makes the state; ``op`` claims from it (the target fiber);
    ``wake`` runs after the target has started (e.g. offers the item a
    parked taker waits for); ``check`` names what was lost, if anything."""

    setup: Callable[[], fx.Effect[Any, Any, Any]]
    op: Callable[[Any, list[Any]], fx.Effect[Any, Any]]
    check: Callable[[Any, list[Any]], fx.Effect[str | None]]
    wake: Callable[[Any], fx.Effect[Any]] = field(default=lambda _: fx.void)


def _once_parked(eff: fx.Effect[Any]) -> fx.Effect[Any]:
    """``eff`` after enough turns for the target to get through its prefix
    (one pause per step at the smallest budget) and park: started by
    ``fork``, it has not run yet when ``wake`` starts."""
    return fx.for_each(range(2 * max(_PREFIXES) + 8), lambda _: fx.yield_now()).and_then(eff)


def _prefixed(k: int, eff: fx.Effect[Any, Any]) -> fx.Effect[Any, Any]:
    @fx.gen
    def body():
        for _ in range(k):
            yield from fx.void
        return (yield from eff)

    return body


def _attempt(case: _Case, budget: int, k: int, at: int) -> tuple[bool, str | None]:
    seen: list[Any] = []

    def under(inner: Scheduler) -> fx.Effect[tuple[bool, str | None]]:
        sched = _InterruptAt(inner, at)

        @fx.gen
        def program():
            state = yield from case.setup()
            target = (
                yield from _prefixed(k, case.op(state, seen))
                .pipe(fx.provide_service(fx.MaxOpsBeforeYield, budget))
                .pipe(fx.provide_service(fx.CurrentScheduler, sched))
                .fork()
            )
            sched.target = target
            yield from case.wake(state)
            yield from target.await_exit()
            for _ in range(4):
                yield from fx.yield_now()
            return sched.fired, (yield from case.check(state, seen))

        return fx.scoped(program)

    return fx.run_sync(fx.CurrentScheduler().flat_map(under))


def _sweep(
    case: _Case, budgets: Sequence[int] = _BUDGETS, prefixes: Sequence[int] = _PREFIXES
) -> list[tuple[int, int, int, str]]:
    lost: list[tuple[int, int, int, str]] = []
    for budget in budgets:
        for k in prefixes:
            at = 0
            while True:
                at += 1
                fired, problem = _attempt(case, budget, k, at)
                if problem is not None:
                    lost.append((budget, k, at, problem))
                if not fired:
                    break
    return lost


def _queue_case(
    take: Callable[[fx.Queue[int], list[Any]], fx.Effect[Any]], *, parked: bool
) -> _Case:
    def setup() -> fx.Effect[fx.Queue[int]]:
        made = fx.Queue[int].unbounded()
        return made if parked else made.tap(lambda q: q.offer(1))

    def check(q: fx.Queue[int], seen: list[Any]) -> fx.Effect[str | None]:
        return q.clear().map(
            lambda left: None if [*seen, *left] == [1] else f"saw {seen}, left {list(left)}"
        )

    def wake(q: fx.Queue[int]) -> fx.Effect[Any]:
        return _once_parked(q.offer(1)) if parked else fx.void

    return _Case(setup, take, check, wake)


# Each hands what it took straight to its own continuation (Effect's
# guarantee: that continuation gets it; later ones are ordinary steps).
_QUEUE_TAKES: dict[str, Callable[[fx.Queue[int], list[Any]], fx.Effect[Any]]] = {
    "take": lambda q, seen: q.take().map(seen.append),
    "take_all": lambda q, seen: q.take_all().map(seen.extend),
    "take_n": lambda q, seen: q.take_n(1).map(seen.extend),
    "take_between": lambda q, seen: q.take_between(1, 2).map(seen.extend),
}


def _pubsub_case(*, parked: bool) -> _Case:
    def setup() -> fx.Effect[Any, Any, Any]:
        @fx.gen
        def made():
            ps = yield from fx.PubSub[int].unbounded()
            sub = yield from ps.subscribe()
            if not parked:
                yield from ps.publish(1)
            return ps, sub

        return made

    def op(state: Any, seen: list[Any]) -> fx.Effect[Any]:
        return state[1].take().map(seen.append)

    def check(state: Any, seen: list[Any]) -> fx.Effect[str | None]:
        def verdict(left: Sequence[int]) -> str | None:
            return None if [*seen, *left] == [1] else f"saw {seen}, left {list(left)}"

        return state[1].take_up_to(10).map(verdict)

    def wake(state: Any) -> fx.Effect[Any]:
        return _once_parked(state[0].publish(1)) if parked else fx.void

    return _Case(setup, op, check, wake)


def _ref_case() -> _Case:
    def op(ref: fx.Ref[int], seen: list[Any]) -> fx.Effect[Any]:
        return ref.update(lambda x: x + 1).map(lambda _: seen.append(1))

    def check(ref: fx.Ref[int], seen: list[Any]) -> fx.Effect[str | None]:
        return ref.get().map(lambda v: None if v == len(seen) else f"value {v}, saw {seen}")

    return _Case(lambda: fx.Ref.make(0), op, check)


def _synchronized_ref_case() -> _Case:
    """The update runs under the lock, inside ``with_permits``' interruptible
    region; as in Effect, an interrupt landing after it but before the
    region ends fails the caller with the update applied. What must hold:
    it is applied at most once, a caller that saw it applied it, and the
    lock is free again."""

    def op(ref: fx.SynchronizedRef[int], seen: list[Any]) -> fx.Effect[Any]:
        return ref.update(lambda x: x + 1).map(lambda _: seen.append(1))

    def check(ref: fx.SynchronizedRef[int], seen: list[Any]) -> fx.Effect[str | None]:
        def verdict(v: int) -> str | None:
            return None if v in (0, 1) and v >= len(seen) else f"value {v}, saw {seen}"

        free = ref.update(lambda x: x).timeout(1).exit()
        return (
            ref.get()
            .map(verdict)
            .zip(free)
            .map(lambda t: t[0] or (None if isinstance(t[1], fx.Success) else "lock still held"))
        )

    return _Case(lambda: fx.SynchronizedRef.make(0), op, check)


def _semaphore_case(*, parked: bool) -> _Case:
    def setup() -> fx.Effect[fx.Semaphore]:
        made = fx.Semaphore.make(1)
        return made.tap(lambda s: s.take(1)) if parked else made

    def op(sem: fx.Semaphore, seen: list[Any]) -> fx.Effect[Any]:
        return sem.take(1).map(seen.append)

    def check(sem: fx.Semaphore, seen: list[Any]) -> fx.Effect[str | None]:
        return sem.available.map(
            lambda free: None if free + len(seen) == 1 else f"free {free}, saw {seen}"
        )

    def wake(sem: fx.Semaphore) -> fx.Effect[Any]:
        return _once_parked(sem.release(1)) if parked else fx.void

    return _Case(setup, op, check, wake)


def _partitioned_semaphore_case(*, parked: bool) -> _Case:
    def setup() -> fx.Effect[fx.PartitionedSemaphore[str]]:
        made = fx.PartitionedSemaphore[str].make(1)
        return made.tap(lambda s: s.take("a")) if parked else made

    def op(sem: fx.PartitionedSemaphore[str], seen: list[Any]) -> fx.Effect[Any]:
        return sem.take("b").map(seen.append)

    def check(sem: fx.PartitionedSemaphore[str], seen: list[Any]) -> fx.Effect[str | None]:
        return sem.available.map(
            lambda free: None if free + len(seen) == 1 else f"free {free}, saw {seen}"
        )

    def wake(sem: fx.PartitionedSemaphore[str]) -> fx.Effect[Any]:
        return _once_parked(sem.release(1)) if parked else fx.void

    return _Case(setup, op, check, wake)


# Not transactions (``TxQueue.take``): as in Effect's ``tx``, the commit runs
# in an uninterruptible region, and an interrupt that arrives meanwhile fails
# the caller when the region ends, with the commit applied.
_CASES: dict[str, _Case] = {
    **{f"queue.{n} (item there)": _queue_case(t, parked=False) for n, t in _QUEUE_TAKES.items()},
    **{f"queue.{n} (parked)": _queue_case(t, parked=True) for n, t in _QUEUE_TAKES.items()},
    "queue.poll": _queue_case(
        lambda q, seen: q.poll().map(lambda o: o is not None and seen.append(o.value)),
        parked=False,
    ),
    "queue.clear": _queue_case(lambda q, seen: q.clear().map(seen.extend), parked=False),
    "pubsub.take (item there)": _pubsub_case(parked=False),
    "pubsub.take (parked)": _pubsub_case(parked=True),
    "ref.update": _ref_case(),
    "synchronized_ref.update": _synchronized_ref_case(),
    "semaphore.take (free)": _semaphore_case(parked=False),
    "semaphore.take (woken)": _semaphore_case(parked=True),
    "partitioned_semaphore.take (free)": _partitioned_semaphore_case(parked=False),
    "partitioned_semaphore.take (woken)": _partitioned_semaphore_case(parked=True),
}


@pytest.mark.parametrize("name", list(_CASES))
def test_a_claimed_result_survives_an_interrupt_at_every_yield(name: str):
    assert _sweep(_CASES[name])[:3] == []


@pytest.mark.parametrize("name", list(_CASES))
def test_a_claimed_result_survives_an_interrupt_before_any_continuation(
    name: str, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(fiber_module, "_INLINE_STEPS", 1)
    assert _sweep(_CASES[name], budgets=(1, 2), prefixes=range(4))[:3] == []
