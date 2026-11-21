"""Exploring a scenario's schedules (see ``_interleave``).

``explore`` enumerates schedules with a bounded number of deviations from
the FIFO order (exhaustive when the tree is small), then spends the rest of
its budget on random walks and PCT-style priority schedules, each from a
seed. Every failure names the schedule that replays it.
"""

from __future__ import annotations

import itertools
import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from pyfect.testing._interleave import (
    Action,
    Chooser,
    DivergedError,
    Outcome,
    Replay,
    Scenario,
    run_once,
)


class RandomWalk:
    def __init__(self, seed: int) -> None:
        self._rng = random.Random(seed)

    def choose(self, actions: Sequence[Action], step: int) -> int:
        return self._rng.randrange(len(actions))


class Priorities:
    """PCT-style: each action key gets a random priority when first seen and
    the highest enabled one runs; at ``depth - 1`` random steps the action
    about to run is pushed below everything instead (a delay)."""

    def __init__(self, seed: int, *, depth: int, length: int) -> None:
        self._rng = random.Random(seed)
        self._priority: dict[tuple[str, int | str], float] = {}
        self._changes = {self._rng.randrange(max(length, 1)) for _ in range(depth - 1)}
        self._low = itertools.count(-1, -1)

    def choose(self, actions: Sequence[Action], step: int) -> int:
        for action in actions:
            if action.key not in self._priority:
                self._priority[action.key] = self._rng.random()
        while True:
            best = max(range(len(actions)), key=lambda i: self._priority[actions[i].key])
            if step not in self._changes or len(actions) == 1:
                return best
            self._changes.discard(step)
            self._priority[actions[best].key] = next(self._low)


def encode(choices: Sequence[int]) -> str:
    """``[0, 0, 0, 2, 0, 1]`` as ``"0*3.2.0.1"``; trailing zeros dropped
    (``Replay`` picks the first action once the prefix ends)."""
    trimmed = list(choices)
    while trimmed and trimmed[-1] == 0:
        trimmed.pop()
    parts: list[str] = []
    for value, group in itertools.groupby(trimmed):
        n = len(list(group))
        if value == 0 and n > 1:
            parts.append(f"0*{n}")
        else:
            parts.extend([str(value)] * n)
    return ".".join(parts)


def decode(schedule: str) -> list[int]:
    choices: list[int] = []
    for part in filter(None, schedule.split(".")):
        if "*" in part:
            value, n = part.split("*")
            choices += [int(value)] * int(n)
        else:
            choices.append(int(part))
    return choices


type Hint = Callable[[Scenario, str], str]
"""How a failure tells the reader to replay ``schedule`` of ``scenario``."""


def _default_hint(scenario: Scenario, schedule: str) -> str:
    return f"schedule {schedule!r}"


class InterleaveFailure(AssertionError):
    """A schedule broke an invariant. ``seed`` is the random phase's seed
    that found it, ``None`` when the bounded search did."""

    def __init__(
        self, scenario: Scenario, how: str, outcome: Outcome, seed: int | None, hint: Hint
    ) -> None:
        self.scenario = scenario
        self.how = how
        self.outcome = outcome
        self.seed = seed
        self.schedule = encode(outcome.choices)
        tail = outcome.log[-40:]
        skipped = len(outcome.log) - len(tail)
        lines = [
            f"interleaving scenario {scenario.name!r} failed ({how}).",
            f"Replay it with: {hint(scenario, self.schedule)}",
            "Problems:",
            *(f"  - {p}" for p in outcome.problems),
            f"Last {len(tail)} of {len(outcome.log)} steps:",
            *(f"  {skipped + i}: {label}" for i, label in enumerate(tail)),
        ]
        super().__init__("\n".join(lines))


def replay(
    scenario: Scenario, schedule: str, *, strict: bool = True, hint: Hint = _default_hint
) -> Outcome:
    """Run ``scenario`` under exactly ``schedule``; raise if it fails. A
    regression test passes ``strict=False`` (see ``Replay``)."""
    outcome = run_once(scenario, Replay(decode(schedule), strict=strict))
    if outcome.problems:
        raise InterleaveFailure(scenario, f"replaying {schedule!r}", outcome, None, hint)
    return outcome


@dataclass
class Report:
    scenario: str
    runs: int = 0
    distinct: int = 0
    exhaustive: bool = False
    deviations: int = 0
    seeds: int = 0
    seen: set[str] = field(default_factory=set[str], repr=False)

    def __str__(self) -> str:
        how = "exhaustive" if self.exhaustive else f"deviations<={self.deviations}"
        return (
            f"{self.scenario}: {self.distinct} distinct schedules in {self.runs} runs "
            f"({how}, {self.seeds} seeded)"
        )


class _Budget:
    """Runs left, or with ``seconds``, the time left; a phase's share
    charges its parent."""

    def __init__(self, runs: int, seconds: float | None, parent: _Budget | None = None) -> None:
        self._runs = runs
        self._seconds = seconds
        self._deadline = None if seconds is None else time.monotonic() + seconds
        self._parent = parent
        self.used = 0

    def take(self) -> bool:
        if self._deadline is not None:
            return time.monotonic() < self._deadline and (
                self._parent is None or self._parent.take()
            )
        if self.used >= self._runs:
            return False
        self.used += 1
        if self._parent is not None:
            self._parent.used += 1
        return True

    def share(self, fraction: float) -> _Budget:
        """A budget for one phase: ``fraction`` of what is left (of the time,
        ``fraction`` of the whole, ending when this budget's time does)."""
        if self._seconds is None:
            return _Budget(int((self._runs - self.used) * fraction), None, self)
        return _Budget(0, self._seconds * fraction, self)


@dataclass(frozen=True)
class _Search:
    scenario: Scenario
    report: Report
    hint: Hint

    def record(self, outcome: Outcome, how: str, seed: int | None = None) -> None:
        report = self.report
        report.runs += 1
        key = encode(outcome.choices)
        if key not in report.seen:
            report.seen.add(key)
            report.distinct += 1
        if outcome.problems:
            raise InterleaveFailure(self.scenario, how, outcome, seed, self.hint)


def explore(
    scenario: Scenario,
    *,
    runs: int | None = None,
    seconds: float | None = None,
    first_seed: int = 0,
    hint: Hint = _default_hint,
) -> Report:
    """Run ``scenario`` under many schedules; raise ``InterleaveFailure``
    naming the first that breaks an invariant. The budget is ``runs``
    schedules (the scenario's own by default), or ``seconds`` of exploring.
    Half of it goes to schedules with few deviations from FIFO order (all of
    them, if the tree is that small), the rest to seeded random walks and
    PCT-style priority schedules, from seed ``first_seed`` on."""
    budget = _Budget(scenario.runs if runs is None else runs, seconds)
    search = _Search(scenario, Report(scenario.name), hint)
    baseline = _bounded_dfs(search, budget.share(0.5))
    if not search.report.exhaustive:
        _seeded(search, budget.share(1.0), baseline, first_seed)
    return search.report


def _bounded_dfs(search: _Search, budget: _Budget) -> int:
    """Depth-first over the choice tree, allowing at most ``k`` non-first
    choices, for k = 0, 1, 2, ... A level that pruned nothing has seen the
    whole tree. Returns the length of the FIFO run (PCT's horizon)."""
    scenario, report = search.scenario, search.report
    baseline = 0
    k = 0
    while True:
        prefix: list[int] = []
        previous: list[tuple[int, int]] | None = None
        pruned = False
        while True:
            if not budget.take():
                report.deviations = max(k - 1, 0)
                return baseline
            outcome = run_once(scenario, Replay(prefix))
            if previous is not None:
                shared = len(prefix) - 1
                if [n for _, n in outcome.trace[:shared]] != [n for _, n in previous[:shared]]:
                    raise DivergedError(
                        f"{scenario.name}: replaying a prefix offered different choices; "
                        "the scenario does not replay deterministically"
                    )
            baseline = baseline or len(outcome.trace)
            search.record(outcome, f"exploring with at most {k} deviations")
            previous = outcome.trace
            nxt: list[int] | None = None
            used = [0]
            for c, _ in outcome.trace:
                used.append(used[-1] + (c != 0))
            for i in range(len(outcome.trace) - 1, -1, -1):
                c, n = outcome.trace[i]
                if c + 1 < n:
                    if used[i] + 1 <= k:
                        nxt = [ch for ch, _ in outcome.trace[:i]] + [c + 1]
                        break
                    pruned = True
            if nxt is None:
                break
            prefix = nxt
        report.deviations = k
        if not pruned:
            report.exhaustive = True
            return baseline
        k += 1


def _seeded(search: _Search, budget: _Budget, baseline: int, first_seed: int) -> None:
    seed = first_seed
    while budget.take():
        chooser: Chooser
        if seed % 2 == 0:
            chooser = RandomWalk(seed)
            how = f"random walk, seed {seed}"
        else:
            chooser = Priorities(seed, depth=3, length=baseline)
            how = f"PCT-style priorities, seed {seed}"
        outcome = run_once(search.scenario, chooser)
        search.report.seeds += 1
        search.record(outcome, how, seed)
        seed += 1
