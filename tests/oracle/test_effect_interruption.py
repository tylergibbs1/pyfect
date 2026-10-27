"""Ports of the fork and interruption cases of Effect's ``Effect.test.ts``
that exercise a forked fiber being interrupted: races, ``forEach``
interruption, ``acquireRelease`` and the "interruption" block.

Each test's docstring is the Effect test title. ``Effect.forkChild`` is
``fork``; ``Scope.provide(scope)`` is ``provide_service(fx.Scope, scope)``.
A resume in Effect runs the woken fiber at once; in pyfect it goes through
the scheduler, so a port yields where Effect's fiber would already have run.
"""

from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.scope import CloseableScope


def _interrupted(ex: fx.Exit[Any, Any] | None) -> bool:
    return isinstance(ex, fx.Failure) and ex.cause.has_interrupts


def _on_interrupt[A, E](eff: fx.Effect[A, E], log: list[str], label: str) -> fx.Effect[A, E]:
    return eff.on_interrupt(fx.sync(lambda: log.append(label)))


@testing.effect
def test_race_interrupts_the_loser_when_the_other_side_succeeds():
    """race interrupts the loser when the other side succeeds"""
    interrupted: list[str] = []
    fast = _on_interrupt(fx.succeed("fast").delay(0.1), interrupted, "fast")
    slow = _on_interrupt(fx.succeed("slow").delay(0.5), interrupted, "slow")
    fiber = yield from fast.race(slow).fork()
    yield from testing.adjust(0.5)
    assert (yield from fiber.join()) == "fast"
    assert interrupted == ["slow"]


@testing.effect
def test_race_first_interrupts_the_loser_when_the_other_side_succeeds():
    """raceFirst interrupts the loser when the other side succeeds"""
    interrupted: list[str] = []
    fast = _on_interrupt(fx.succeed("fast").delay(0.1), interrupted, "fast")
    slow = _on_interrupt(fx.succeed("slow").delay(0.5), interrupted, "slow")
    fiber = yield from fast.race_first(slow).fork()
    yield from testing.adjust(0.5)
    assert (yield from fiber.join()) == "fast"
    assert interrupted == ["slow"]


@testing.effect
def test_race_first_interrupts_the_loser_when_the_other_side_fails():
    """raceFirst interrupts the loser when the other side fails"""
    interrupted: list[str] = []
    slow = _on_interrupt(fx.succeed("slow").delay(0.5), interrupted, "slow")
    fiber = yield from fx.fail("boom").delay(0.1).race_first(slow).exit().fork()
    yield from testing.adjust(0.5)
    assert (yield from fiber.join()) == fx.exit.fail("boom")
    assert interrupted == ["slow"]


RACES = ["race", "race_first"]


def _race(name: str, a: fx.Effect[Any, Any], b: fx.Effect[Any, Any]) -> fx.Effect[Any, Any]:
    return a.race(b) if name == "race" else a.race_first(b)


@pytest.mark.parametrize("name", RACES)
@testing.effect
def test_interrupts_a_loser_that_settles_the_race_while_starting(name: str):
    """${name} interrupts a loser that settles the race while starting"""
    interrupted: list[str] = []
    deferred = yield from fx.Deferred[None].make()
    loser = _on_interrupt(deferred.succeed(None).and_then(fx.never), interrupted, "loser")
    yield from _race(name, deferred.wait(), loser)
    assert interrupted == ["loser"]


@pytest.mark.parametrize("name", RACES)
@testing.effect
def test_interrupts_the_loser_when_interrupted_while_starting(name: str):
    """${name} interrupts the loser when interrupted while starting"""
    interrupted: list[str] = []

    @fx.gen
    def body():
        parent = fx.Fiber.get_current()
        assert parent is not None
        loser = _on_interrupt(
            fx.sync(lambda: parent.unsafe_interrupt_as(None)).and_then(fx.never),
            interrupted,
            "loser",
        )
        return (yield from _race(name, loser, fx.void))

    fiber = yield from body.fork()
    yield from fiber.await_exit()
    assert interrupted == ["loser"]


def _record(done: list[int], i: int) -> fx.Effect[int]:
    def go() -> int:
        done.append(i)
        return i

    return fx.sync(go)


@testing.effect
def test_sequential_interrupt():
    """sequential interrupt"""
    done: list[int] = []
    fiber = yield from fx.for_each(range(1, 7), lambda i: _record(done, i).delay(0.3)).fork()
    yield from testing.adjust(0.8)
    yield from fiber.interrupt()
    assert _interrupted((yield from fiber.await_exit()))
    assert done == [1, 2]


@testing.effect
def test_unbounded_interrupt():
    """unbounded interrupt"""
    done: list[int] = []
    fiber = yield from fx.for_each(
        range(1, 4), lambda i: _record(done, i).delay(0.15), concurrency="unbounded"
    ).fork()
    yield from testing.adjust(0.05)
    yield from fiber.interrupt()
    assert _interrupted((yield from fiber.await_exit()))
    assert done == []


@testing.effect
def test_bounded_interrupt():
    """bounded interrupt"""
    done: list[int] = []
    fiber = yield from fx.for_each(
        range(1, 7), lambda i: _record(done, i).delay(0.2), concurrency=2
    ).fork()
    yield from testing.adjust(0.35)
    yield from fiber.interrupt()
    assert _interrupted((yield from fiber.await_exit()))
    assert done == [1, 2]


@testing.live
def test_releases_on_interrupt():
    """releases on interrupt"""
    released: list[bool] = []
    fiber = yield from fx.scoped(
        fx.acquire_release(
            fx.succeed("foo").delay(0.1), lambda _a, _ex: fx.sync(lambda: released.append(True))
        )
    ).fork(start_immediately=True)
    fiber.unsafe_interrupt_as(None)
    yield from fiber.await_exit()
    assert released == [True]


class ATag(fx.Tag[str], key="ATag"): ...


@testing.effect
def test_supports_release_dependencies():
    """supports release dependencies"""
    released: list[str] = []
    scope = CloseableScope()
    yield from (
        fx.acquire_release(
            fx.succeed("foo"),
            lambda _a, _ex: ATag().flat_map(lambda a: fx.sync(lambda: released.append(a))),
        )
        .pipe(fx.provide_service(ATag, "A"))
        .pipe(fx.provide_service(fx.Scope, scope))
    )
    yield from scope.close(fx.exit.succeed(None))
    assert released == ["A"]


@testing.effect
def test_sync_forever_is_interruptible():
    """sync forever is interruptible"""
    fiber = yield from fx.succeed(1).forever().fork()
    yield from fiber.interrupt()
    assert _interrupted(fiber.unsafe_poll())


@testing.effect
def test_interrupt_of_never_is_interrupted_with_cause():
    """interrupt of never is interrupted with cause"""
    fiber = yield from fx.never.fork()
    yield from fiber.interrupt()
    assert _interrupted(fiber.unsafe_poll())


@testing.live
def test_closing_scope_is_uninterruptible():
    """closing scope is uninterruptible"""
    ref: list[bool] = []
    child = fx.sleep(0.01).and_then(fx.sync(lambda: ref.append(True)))
    fiber = yield from child.uninterruptible().fork(start_immediately=True)
    yield from fiber.interrupt()
    assert ref == [True]


@testing.effect
def test_callback_cleanup_effect_runs_on_interrupt():
    """callback cleanup effect runs on interrupt"""
    cleaned_up: list[bool] = []
    fiber = yield from fx.callback(lambda _resume: fx.sync(lambda: cleaned_up.append(True))).fork(
        start_immediately=True
    )
    yield from fiber.interrupt()
    assert cleaned_up == [True]
