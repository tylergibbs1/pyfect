"""Racing combinators interrupted from outside. Effect's ``raceAll`` and
``raceAllFirst`` interrupt and await the racers in an exit finalizer
(``onExitUnsafe(parent, () => fiberInterruptAll(fibers))``), and that
finalizer succeeds with ``void``: the race waits for every racer to clean
up, then reports the outside Interrupt alone. Unlike ``forEach`` (#12), the
racers' own causes are not kept. Each expected result below was checked
against Effect 4.0.6."""

from collections.abc import Callable

import pytest

import pyfect as fx
from pyfect.cause import Interrupt

type Race = Callable[[list[fx.Effect[None, str]]], fx.Effect[None, str]]

RACES: dict[str, Race] = {
    "race": lambda es: es[0].race(es[1]),
    "race_first": lambda es: es[0].race_first(es[1]),
    "race_all": lambda es: fx.race_all(*es),
    "timeout": lambda es: es[0].timeout(3600).catch_all(lambda _: fx.void),
}


def _slow_cleanup(name: str, log: list[str]) -> fx.Effect[None, str]:
    """Logs ``started:name`` when it runs and ``name`` once its cleanup,
    which takes real time, has finished."""
    cleanup = fx.sleep(0.01).and_then(fx.sync(lambda: log.append(name)))
    started = fx.sync(lambda: log.append(f"started:{name}"))
    return started.and_then(fx.never.on_interrupt(cleanup))


def _until_started(log: list[str], n: int) -> fx.Effect[None]:
    """pyfect forks racers on the next scheduler turn (Effect starts them
    at once), so wait until they are running."""
    started = fx.sync(lambda: sum(e.startswith("started:") for e in log))
    return (
        fx.yield_now()
        .and_then(started)
        .flat_map(lambda k: fx.void if k >= n else _until_started(log, n))
    )


def _cleaned(log: list[str]) -> list[str]:
    return sorted(e for e in log if not e.startswith("started:"))


@pytest.mark.parametrize("name", list(RACES))
def test_an_outside_interrupt_waits_for_every_racer_and_reports_only_the_interrupt(name: str):
    log: list[str] = []
    racers = [_slow_cleanup("a", log), _slow_cleanup("b", log)]

    @fx.gen
    def program():
        me = yield from fx.fiber_id()
        fiber = yield from RACES[name](racers).fork()
        yield from _until_started(log, 1 if name == "timeout" else 2)
        yield from fiber.interrupt()
        return me, (yield from fiber.await_exit())

    me, ex = fx.run_sync(program)
    assert isinstance(ex, fx.Failure) and ex.cause.reasons == (Interrupt(me),)
    expected = ["a"] if name == "timeout" else ["a", "b"]
    assert _cleaned(log) == expected


def test_a_racer_that_already_failed_is_not_reported_after_an_outside_interrupt():
    log: list[str] = []

    @fx.gen
    def program():
        me = yield from fx.fiber_id()
        fiber = yield from fx.fail("early").race(_slow_cleanup("b", log)).fork()
        yield from _until_started(log, 1)
        yield from fiber.interrupt()
        return me, (yield from fiber.await_exit())

    me, ex = fx.run_sync(program)
    assert isinstance(ex, fx.Failure) and ex.cause.reasons == (Interrupt(me),)
    assert _cleaned(log) == ["b"]
