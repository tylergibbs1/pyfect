"""Guard: no schedule dies on a delay that grows past float range.

Effect's delays are JavaScript numbers, which saturate to ``Infinity``;
Python's ``float ** n`` and big-int conversions raise ``OverflowError``
instead (DOGFOOD outlay #10: ``exponential`` died after ~14.5 h of polling).
Every public constructor and combinator of ``pyfect.schedule`` (found by
walking the module and the ``Schedule`` class, so a new one fails here until
it is listed) runs 10,000 recurrences under the TestClock, with time moved
to infinity, and must not die. Combinators wrap growing schedules.
"""

import inspect
import math
from collections.abc import Callable
from typing import Any

import pytest

import pyfect as fx
from pyfect import schedule, testing
from pyfect.cause import Die
from pyfect.duration import seconds, zero
from pyfect.exit import Failure
from pyfect.schedule import Schedule

RECURRENCES = 10_000
type AnySchedule = Schedule[Any, Any, Any, Any]


def growing() -> list[AnySchedule]:
    """Schedules whose delays pass float range well before 10,000 steps."""
    return [
        schedule.exponential("1 second", 10),
        schedule.fibonacci("1 second"),
        schedule.exponential("1 second", 1.5),
    ]


def each_growing(f: Callable[[AnySchedule], AnySchedule]) -> list[AnySchedule]:
    return [f(s) for s in growing()]


def fixed_input(s: AnySchedule) -> AnySchedule:
    return s.pipe(schedule.set_input_type(object))


# Every public name of ``pyfect.schedule`` that makes or combines schedules.
MODULE_CASES: dict[str, Callable[[], list[AnySchedule]]] = {
    "cron": lambda: [schedule.cron("* * * * *")],
    "duration": lambda: [schedule.duration(seconds(1e308)), schedule.duration(math.inf)],
    "during": lambda: [schedule.during(math.inf)],
    "exponential": lambda: [
        schedule.exponential("200 millis", 1.5),
        schedule.exponential(seconds(1e300), 1e300),
    ],
    "fibonacci": lambda: [schedule.fibonacci("1 second"), schedule.fibonacci(seconds(1e300))],
    "fixed": lambda: [
        schedule.fixed("1 second"),
        schedule.fixed(seconds(1e300)),
        schedule.fixed(math.inf),
    ],
    "forever": lambda: [schedule.forever],
    "identity": lambda: [schedule.identity()],
    "max": lambda: [schedule.max(*growing(), schedule.spaced("30 seconds"))],
    "min": lambda: [schedule.min(*growing(), schedule.spaced("30 seconds"))],
    "once": lambda: [schedule.once],
    "recurs": lambda: [schedule.recurs(RECURRENCES)],
    "spaced": lambda: [schedule.spaced(seconds(1e308)), schedule.spaced(math.inf)],
    "windowed": lambda: [schedule.windowed("1 second"), schedule.windowed(seconds(1e300))],
    "jittered": lambda: each_growing(schedule.jittered),
    "passthrough": lambda: each_growing(schedule.passthrough),
    "from_step": lambda: [schedule.from_step(schedule.to_step(s)) for s in growing()],
    "set_input_type": lambda: each_growing(fixed_input),
}

# Public names that neither make nor combine schedules.
NOT_SCHEDULES = {
    "Continue",
    "CurrentMetadata",
    "Decision",
    "InputMetadata",
    "Metadata",
    "Schedule",
    "SetInputType",
    "StepFn",
    "Stop",
    "from_step_with_metadata",  # pinned through every metadata-based constructor
    "to_step",
    "to_step_with_metadata",
    "to_step_with_sleep",
}

# Every public method of ``Schedule``, applied to growing schedules.
METHOD_CASES: dict[str, Callable[[AnySchedule], AnySchedule]] = {
    "map": lambda s: s.map(lambda m: m.duration),
    "map_effect": lambda s: s.map_effect(lambda m: fx.succeed(m.elapsed)),
    "tap": lambda s: s.tap(lambda m: fx.succeed(m.elapsed_since_previous)),
    "while_": lambda s: s.while_(lambda m: m.duration >= zero),
    "while_effect": lambda s: s.while_effect(lambda _: fx.succeed(True)),
    "modify_delay": lambda s: s.modify_delay(lambda m: fx.succeed(m.duration * 2)),
    "add_delay": lambda s: s.add_delay(lambda m: fx.succeed(m.duration)),
    "jittered": lambda s: s.jittered(),
    "pipe": lambda s: s.pipe(schedule.jittered),
    "passthrough": lambda s: s.passthrough(),
    "up_to": lambda s: s.up_to(duration=seconds(1e300)),
    "concat_result": lambda s: schedule.recurs(3).concat_result(s),
    "concat": lambda s: s.concat(schedule.spaced("1 second")),
}


def public_methods() -> set[str]:
    return {
        name
        for name, member in inspect.getmembers(Schedule)
        if not name.startswith("_") and callable(member)
    }


def test_every_public_schedule_name_is_covered():
    unlisted = set(schedule.__all__) - MODULE_CASES.keys() - NOT_SCHEDULES
    assert not unlisted, f"add these to MODULE_CASES or NOT_SCHEDULES: {sorted(unlisted)}"
    assert not (set(MODULE_CASES) | NOT_SCHEDULES) - set(schedule.__all__)


def test_every_schedule_method_is_covered():
    assert public_methods() == METHOD_CASES.keys()


def run_to_the_end(s: AnySchedule) -> fx.Exit[object, object]:
    """Repeat a no-op ``RECURRENCES`` times on ``s``, moving the TestClock to
    infinity so every delay, finite or not, elapses."""

    @fx.gen
    def go():
        bounded = s.up_to(times=RECURRENCES)
        running = yield from fx.void.repeat(bounded).exit().fork()
        yield from testing.set_time(math.inf)
        return (yield from running.join())

    return testing.run_test(go)


def defects(exit: fx.Exit[object, object]) -> list[BaseException | object]:
    if not isinstance(exit, Failure):
        return []
    return [r.defect for r in exit.cause.reasons if isinstance(r, Die)]


@pytest.mark.parametrize("name", sorted(MODULE_CASES))
def test_constructor_never_dies(name: str):
    for s in MODULE_CASES[name]():
        assert defects(run_to_the_end(s)) == [], name


@pytest.mark.parametrize("name", sorted(METHOD_CASES))
def test_combinator_never_dies(name: str):
    for s in growing():
        assert defects(run_to_the_end(METHOD_CASES[name](s))) == [], name
