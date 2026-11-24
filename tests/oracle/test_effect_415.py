"""Ports of the titles Effect 4.1.5 added to ``effect/test/Effect.test.ts``: fork options,
interrupted work waiting for its cleanup, and races under an uninterruptible parent.

Each test's docstring is the Effect test title. ``forkChild`` is ``fork``, ``forkDetach`` is
``fork_daemon``.
"""

from collections.abc import Callable
from typing import Any, Literal, Never

import pytest
from _fork_registration import registers_during_startup

import pyfect as fx
from pyfect import duration, testing
from pyfect import scope as Scope
from pyfect.errors import TimeoutException
from pyfect.result import Ok


def _interrupted(ex: fx.Exit[Any, Any] | None) -> bool:
    return isinstance(ex, fx.Failure) and ex.cause.has_interrupts


def _timed_out(ex: fx.Exit[Any, Any]) -> bool:
    if not isinstance(ex, fx.Failure):
        return False
    found = ex.cause.find_error()
    return isinstance(found, Ok) and found.value == TimeoutException(
        duration.millis(10), "Operation timed out after '10ms'"
    )


@testing.effect
def test_suspend_treats_a_thrown_value_as_a_defect():
    """suspend treats a thrown value as a defect"""
    thrown = ValueError("boom")

    def throw() -> fx.Effect[Never]:
        raise thrown

    ex = yield from fx.suspend(throw).exit()
    assert isinstance(ex, fx.Failure)
    assert ex.cause.defects == (thrown,)


type _Run = Callable[[fx.Effect[Never], fx.Effect[str], fx.Effect[Never, str]], fx.Effect[Any, Any]]
_CLEANUP: list[tuple[str, _Run]] = [
    ("race", lambda worker, winner, _: worker.race(winner)),
    ("raceFirst", lambda worker, winner, _: worker.race_first(winner)),
    ("raceAll", lambda worker, winner, _: fx.race_all(worker, winner)),
    ("raceAllFirst", lambda worker, winner, _: fx.race_all_first(worker, winner)),
    ("all", lambda worker, _, failure: fx.all(worker, failure, concurrency=2)),
    (
        "forEach",
        lambda worker, _, failure: fx.for_each([worker, failure], lambda e: e, concurrency=2),
    ),
    ("timeout", lambda worker, _w, _f: worker.timeout("10 millis")),
]


@pytest.mark.parametrize(
    ("name", "run"), _CLEANUP, ids=[f"{n} waits for asynchronous finalizers" for n, _ in _CLEANUP]
)
@testing.effect
def test_interrupted_work_waits_for_asynchronous_finalizers(name: str, run: _Run):
    """\\x00 waits for asynchronous finalizers"""
    started = fx.Deferred[None]()
    cleaning = fx.Deferred[None]()
    release = fx.Deferred[None]()
    worker: fx.Effect[Never] = (
        started.succeed(None)
        .and_then(fx.never)
        .ensuring(cleaning.succeed(None).and_then(release.wait()))
    )
    winner = started.wait().as_("winner")
    failure: fx.Effect[Never, str] = started.wait().and_then(fx.fail("failure"))
    fiber = yield from run(worker, winner, failure).exit().fork()
    yield from started.wait()
    yield from testing.adjust("10 millis")
    yield from cleaning.wait()
    yield from fx.yield_now()
    assert fiber.poll_unsafe() is None
    yield from release.succeed(None)
    ex = yield from fiber.join()
    if name in ("all", "forEach"):
        assert ex == fx.exit.fail("failure")
    elif name == "timeout":
        assert _timed_out(ex)
    else:
        assert ex == fx.Success("winner")


@testing.effect
def test_race_all_interrupts_losers_under_an_uninterruptible_parent():
    """raceAll interrupts losers under an uninterruptible parent"""
    interrupted: list[int] = []

    def racer(ms: int) -> fx.Effect[int, str]:
        eff: fx.Effect[int, str] = fx.fail("boom") if ms == 0 else fx.succeed(ms)
        return eff.delay(f"{ms} millis").on_interrupt(fx.sync(lambda: interrupted.append(ms)))

    fiber = (
        yield from fx.race_all(*(racer(ms) for ms in (500, 300, 200, 0, 100)))
        .uninterruptible()
        .fork()
    )
    yield from testing.adjust("500 millis")
    assert (yield from fiber.join()) == 100
    assert sorted(interrupted) == [200, 300, 500]


@testing.effect
def test_race_first_interrupts_the_loser_under_an_uninterruptible_parent():
    """raceFirst interrupts the loser under an uninterruptible parent"""
    interrupted: list[str] = []

    def racer(label: str, ms: int) -> fx.Effect[str]:
        return (
            fx.succeed(label)
            .delay(f"{ms} millis")
            .on_interrupt(fx.sync(lambda: interrupted.append(label)))
        )

    fiber = yield from racer("fast", 100).race_first(racer("slow", 500)).uninterruptible().fork()
    yield from testing.adjust("500 millis")
    assert (yield from fiber.join()) == "fast"
    assert interrupted == ["slow"]


@testing.effect
def test_timeout_waits_for_an_uninterruptible_source_but_discards_its_success():
    """timeout waits for an uninterruptible source but discards its success"""
    started = fx.Deferred[None]()
    release = fx.Deferred[None]()
    completed: list[bool] = []

    def complete() -> str:
        completed.append(True)
        return "value"

    source = started.succeed(None).and_then(release.wait()).and_then(fx.sync(complete))
    fiber = yield from source.uninterruptible().timeout("10 millis").exit().fork()
    yield from started.wait()
    yield from testing.adjust("10 millis")
    assert fiber.poll_unsafe() is None
    yield from release.succeed(None)
    assert _timed_out((yield from fiber.join()))
    assert completed == [True]


@testing.effect
def test_catch_cause_recovers_from_interrupt_with_the_current_fiber_as_interruptor():
    """recovers from Effect.interrupt with the current fiber as interruptor"""
    me = yield from fx.fiber_id()
    cause = yield from fx.interrupt().catch_cause(fx.succeed)
    assert cause.interruptors == frozenset({me})


# --- fork options ---------------------------------------------------------------------------

type _Name = Literal["forkChild", "forkDetach", "forkIn", "forkScoped"]


@pytest.mark.parametrize(
    "name",
    ["forkChild", "forkDetach", "forkIn", "forkScoped"],
    ids=lambda n: f"{n} defers startup by default and starts synchronously when requested",
)
@testing.effect
def test_fork_defers_startup_by_default_and_starts_synchronously_when_requested(name: _Name):
    """\\x00 defers startup by default and starts synchronously when requested"""
    scope = yield from Scope.make()
    events: list[str] = []
    for start_immediately in (False, True):
        release = fx.Deferred[None]()
        events.clear()
        work = (
            fx.sync(lambda: events.append("started"))
            .and_then(release.wait())
            .and_then(fx.sync(lambda: events.append("resumed")))
        )
        match name:
            case "forkChild":
                child = yield from work.fork(start_immediately=start_immediately)
            case "forkDetach":
                child = yield from work.fork_daemon(start_immediately=start_immediately)
            case "forkIn":
                child = yield from work.fork_in(scope, start_immediately=start_immediately)
            case "forkScoped":
                child = yield from work.fork_scoped(start_immediately=start_immediately).pipe(
                    Scope.provide(scope)
                )
        assert events == (["started"] if start_immediately else [])
        yield from release.succeed(None)
        yield from child.join()
        assert events == ["started", "resumed"]


@pytest.mark.parametrize(
    ("uninterruptible", "region"),
    [(False, "uninterruptible"), (True, "interruptible"), ("inherit", "uninterruptible")],
    ids=[
        "uninterruptible: undefined when forked from an uninterruptible region",
        "uninterruptible: true when forked from an interruptible region",
        "uninterruptible: inherit when forked from an uninterruptible region",
    ],
)
@testing.effect
def test_uninterruptible_option_when_forked_from_a_region(
    uninterruptible: bool | Literal["inherit"], region: str
):
    """uninterruptible: \\x00 when forked from an \\x00 region"""
    release = fx.Deferred[str]()
    fork = release.wait().fork(start_immediately=True, uninterruptible=uninterruptible)
    child = yield from (fork.uninterruptible() if region == "uninterruptible" else fork)
    interrupting = yield from child.interrupt().fork(start_immediately=True)
    if uninterruptible is False:
        yield from interrupting.join()
        assert _interrupted((yield from child.await_exit()))
    else:
        assert interrupting.poll_unsafe() is None
        assert child.poll_unsafe() is None
        yield from release.succeed("own result")
        yield from interrupting.join()
        assert (yield from child.await_exit()) == fx.Success("own result")


@testing.effect
def test_an_explicitly_interruptible_region_overrides_the_uninterruptible_fork_option():
    """an explicitly interruptible region overrides the uninterruptible fork option"""
    started = fx.Deferred[None]()
    child = (
        yield from started.succeed(None)
        .and_then(fx.never)
        .interruptible()
        .fork(uninterruptible=True)
    )
    yield from started.wait()
    yield from child.interrupt()
    assert _interrupted((yield from child.await_exit()))


@pytest.mark.parametrize("name", ["forkIn", "forkScoped"])
@testing.effect
def test_registers_a_fiber_even_when_it_interrupts_its_forker_during_startup(name: str):
    """registers a fiber even when it interrupts its forker during startup"""
    if name == "forkIn":
        yield from registers_during_startup(
            lambda work, scope: work.fork_in(scope, start_immediately=True)
        )
    else:
        yield from registers_during_startup(
            lambda work, scope: work.fork_scoped(start_immediately=True).pipe(Scope.provide(scope))
        )
