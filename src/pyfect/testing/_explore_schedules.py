"""``explore.schedules``: an effect run under many fiber schedules (the
interleaving engine of ``_interleave``), checked after each."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast, overload

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect._fiber import Fiber
from pyfect.exit import Exit
from pyfect.testing._interleave import Outcome, Problems, Replay, Scenario, ThreadBody, World
from pyfect.testing._interleave_search import InterleaveFailure, decode, explore, run_once

type Check[A, E] = Callable[[Exit[A, E]], str | None]
"""Gets the run's exit; returns what went wrong, or ``None``."""

type Case[A, E] = tuple[Effect[A, E], Check[A, E]]
"""One run's effect and the check of it, made fresh for each run."""

_INTERRUPTER = "interrupt"


@dataclass(frozen=True)
class Report:
    """What ``schedules`` explored: ``runs`` runs, ``distinct`` of them
    with different schedules; ``exhaustive`` when they were every schedule
    there is (with ``interrupts``, every point the interrupt can land)."""

    runs: int
    distinct: int
    exhaustive: bool


class ScheduleFailure(AssertionError):
    """A schedule broke the check, or left a fiber that never ended.

    ``schedule`` replays it (``schedules(..., replay=schedule)``); ``seed``
    is the seed of the random run that found it (``None`` when the
    systematic search did); ``interrupted_at`` is the step the interrupt
    was sent at, with ``interrupts``."""

    def __init__(
        self,
        message: str,
        *,
        schedule: str,
        seed: int | None,
        interrupted_at: int | None,
        problems: tuple[str, ...],
    ) -> None:
        super().__init__(message)
        self.schedule = schedule
        self.seed = seed
        self.interrupted_at = interrupted_at
        self.problems = problems


def _positive(name: str, value: int) -> int:
    if value < 1:
        raise ValueError(f"{name} must be at least 1, got {value}")
    return value


def _checked[A, E](check: Check[A, E], fiber: Fiber[A, E]) -> Problems:
    ex = fiber.poll_unsafe()
    if ex is None:
        return None  # the engine reports a fiber that never ended
    try:
        return check(ex)
    except Exception as exc:  # a raising check is a problem of this run
        return f"the check raised {exc!r}"


def _build[A, E](scenario: Callable[[], Case[A, E]], interrupts: bool) -> Callable[[World], None]:
    def build(world: World) -> None:
        effect, check = scenario()
        require_effect(effect, "the scenario's effect")
        root = world.fork(effect, must_succeed=False)
        world.check(lambda: _checked(check, root))
        if interrupts:

            def interrupter() -> ThreadBody:
                root.interrupt_as_unsafe(None)
                yield

            world.thread(_INTERRUPTER, interrupter)

    return build


def _interrupted_at(outcome: Outcome) -> int | None:
    label = f"thread {_INTERRUPTER}"
    return next((i for i, step in enumerate(outcome.log) if step == label), None)


def _failure(outcome: Outcome, schedule: str, how: str, seed: int | None) -> ScheduleFailure:
    at = _interrupted_at(outcome)
    tail = outcome.log[-40:]
    skipped = len(outcome.log) - len(tail)
    lines = [
        f"explore.schedules: a schedule broke the check ({how}).",
        f"Replay it with: explore.schedules(..., replay={schedule!r})",
    ]
    if seed is not None:
        lines.append(f"Exploring again with seed={seed} finds it at once.")
    if at is not None:
        before = outcome.log[at - 1] if at > 0 else "the start"
        lines.append(f"The interrupt was sent at step {at}, after {before}.")
    lines += [
        "Problems:",
        *(f"  - {p}" for p in outcome.problems),
        f"Last {len(tail)} of {len(outcome.log)} steps:",
        *(f"  {skipped + i}: {label}" for i, label in enumerate(tail)),
    ]
    return ScheduleFailure(
        "\n".join(lines),
        schedule=schedule,
        seed=seed,
        interrupted_at=at,
        problems=tuple(outcome.problems),
    )


@overload
def schedules[A, E](
    scenario: Effect[A, E],
    check: Check[A, E],
    /,
    *,
    runs: int = 1000,
    seed: int = 0,
    interrupts: bool = False,
    max_ops_before_yield: int | None = None,
    max_steps: int = 10_000,
    replay: str | None = None,
) -> Report: ...
@overload
def schedules[A, E](
    scenario: Callable[[], Case[A, E]],
    /,
    *,
    runs: int = 1000,
    seed: int = 0,
    interrupts: bool = False,
    max_ops_before_yield: int | None = None,
    max_steps: int = 10_000,
    replay: str | None = None,
) -> Report: ...
def schedules(
    scenario: Effect[Any, Any] | Callable[[], Case[Any, Any]],
    check: Check[Any, Any] | None = None,
    /,
    *,
    runs: int = 1000,
    seed: int = 0,
    interrupts: bool = False,
    max_ops_before_yield: int | None = None,
    max_steps: int = 10_000,
    replay: str | None = None,
) -> Report:
    """Run ``scenario`` under up to ``runs`` distinct fiber schedules and
    ``check`` its exit after each; raise ``ScheduleFailure`` naming the
    first schedule that breaks it, or that leaves a fiber never ending.

    ``scenario`` is an effect needing no services, with ``check``, or a
    function making a fresh ``(effect, check)`` pair for each run (for a
    check that reads state kept outside the effect). Half the runs go to
    every schedule with few deviations from first-come order, the rest to
    random ones from ``seed`` on. ``interrupts`` also sends the effect's
    fiber an interrupt, which the search lands at each step.
    ``max_ops_before_yield`` makes a fiber pause after that many steps, so
    others run between them; ``max_steps`` bounds one run. ``replay``
    runs only the schedule a failure printed."""
    _positive("runs", runs)
    _positive("max_steps", max_steps)
    if max_ops_before_yield is not None:
        _positive("max_ops_before_yield", max_ops_before_yield)
    if isinstance(scenario, Effect):
        if check is None:
            raise TypeError("explore.schedules(effect, check): the check is missing")
        effect, given = cast("Effect[Any, Any]", scenario), check

        def make() -> Case[Any, Any]:
            return effect, given

    else:
        make = scenario
    engine = Scenario(
        "explore.schedules",
        _build(make, interrupts),
        runs=runs,
        max_steps=max_steps,
        ops=max_ops_before_yield,
    )
    if replay is not None:
        return _replay(engine, replay)
    try:
        found = explore(engine, first_seed=seed)
    except InterleaveFailure as failure:
        raise _failure(failure.outcome, failure.schedule, failure.how, failure.seed) from None
    return Report(found.runs, found.distinct, found.exhaustive)


def _replay(engine: Scenario, schedule: str) -> Report:
    outcome = run_once(engine, Replay(decode(schedule)))
    if outcome.problems:
        raise _failure(outcome, schedule, f"replaying {schedule!r}", None)
    return Report(runs=1, distinct=1, exhaustive=False)
