"""A deterministic interleaving harness for the fiber runtime (see README.md).

One run of a scenario is driven entirely by ``InterleaveScheduler``: every
point where the runtime hands work over (a scheduled task, a ``call_later``
timer, a ``wake_soon``, a resume or interrupt sent from another thread) is
recorded as a pending action instead of being run. At each step the harness
lists the enabled actions in a fixed order and asks a ``Chooser`` which one
runs next. Simulated threads are generators the harness steps one yield at a
time, outside any fiber and with the scheduler not running, so what they do
takes the runtime's cross-thread paths (through the scheduler), not nested
runs.

A run is a list of choice indices, so any run replays exactly from its
schedule string. ``explore`` enumerates schedules with a bounded number of
deviations from the FIFO order (exhaustive when the tree is small), then
spends the rest of its budget on random walks and PCT-style priority
schedules, each from a seed. Every failure names the schedule that replays
it.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import contextvars
import itertools
import os
import random
import threading
import time
import warnings
from collections import Counter
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Protocol, cast

import pyfect as fx
from pyfect._fiber import Fiber, current_fiber, current_run_scheduler
from pyfect.duration import Duration
from pyfect.exit import Exit
from pyfect.scheduler import Cancel, StalledError, SyncOnlyScheduler, SyncScheduler, Task

type Guard = Callable[[], bool]
"""Yielded by a simulated thread: its next step waits until this holds."""

type ThreadBody = Generator[Guard | None]
type Problems = str | Sequence[str] | None
type Order = Literal["any", "fifo"]
"""``any``: every ready task is a choice. ``fifo``: only the oldest is, as
the real schedulers run them; timers and threads still interleave."""
type Timers = Literal["anytime", "when_idle"]
"""``anytime``: a due timer may fire between any two tasks. ``when_idle``:
only once no task is ready (virtual time moves when the run is idle)."""

BUDGET_ENV = "PYFECT_INTERLEAVE_BUDGET"
SEED_ENV = "PYFECT_INTERLEAVE_SEED"
"""The first seed of the random phase (default 0, as in CI): a deeper run
started at another seed explores schedules CI never tried."""


# --- recorded actions ----------------------------------------------------------------


@dataclass(eq=False)
class _Pending:
    seq: int
    task: Task
    label: str


@dataclass(eq=False)
class _Timer:
    seq: int
    when: float
    task: Task
    label: str
    daemon: bool
    alive: bool = True


@dataclass(frozen=True)
class Action:
    """One enabled choice. ``key`` identifies it across steps (PCT gives
    each key a priority)."""

    kind: Literal["task", "timer", "thread"]
    key: tuple[str, int | str]
    label: str


def _describe(task: Callable[..., object]) -> str:
    """A task's function, and the fibers its closure holds, for the log."""
    inner = task
    while hasattr(inner, "func"):  # functools.partial
        inner = inner.func  # type: ignore[attr-defined]
    name = getattr(inner, "__qualname__", type(inner).__name__)
    name = name.replace(".<locals>", "").replace(".<lambda>", "")
    fibers: list[str] = []
    for cell in getattr(inner, "__closure__", None) or ():
        try:
            value = cell.cell_contents
        except ValueError:
            continue
        if isinstance(value, Fiber):
            fibers.append(f"Fiber(#{value.id})")
    return f"{name}({', '.join(fibers)})" if fibers else name


class InterleaveScheduler(SyncOnlyScheduler):
    """Records what the runtime hands over; ``World`` decides when it runs.

    A ``SyncOnlyScheduler``, so it can also stand in for a
    ``ManagedRuntime``'s own scheduler (``run_sync`` flushes it, ``run_blocking``
    and ``dispose`` drive it, from a simulated thread)."""

    def __init__(self, world: World) -> None:
        super().__init__()
        self._world = world
        self.tasks: list[_Pending] = []
        self.timers: list[_Timer] = []
        self.now = 0.0

    def runs_here(self) -> bool:
        return self._world.driving

    def driver(self) -> int | None:
        return threading.get_ident() if self._world.driving else None

    def schedule(self, task: Task, priority: int = 0) -> None:
        # As ``SyncOnlyScheduler`` while a ``run_sync`` flushes it.
        if (
            self.root is not None
            and current_run_scheduler() is self
            and current_fiber() is not self.root
        ):
            self._held.append((task, priority))
            return
        self._enqueue(task)

    def schedule_as_root(self, task: Task) -> None:
        self._enqueue(task)

    def adopt(self, into: SyncScheduler) -> None:
        """Kept: the world goes on choosing what runs after a run's caller returns."""

    def _enqueue(self, task: Task) -> None:
        world = self._world
        label = _describe(task)
        if world.thread_running is not None:
            label += f" <from {world.thread_running}>"
        self.tasks.append(_Pending(next(world.seq), self._tracked(task), label))

    def call_later(self, delay: Duration, task: Task, *, daemon: bool = False) -> Cancel:
        world = self._world
        when = self.now + max(delay.to_seconds(), 0.0)
        timer = _Timer(next(world.seq), when, task, f"timer@{when:g}s {_describe(task)}", daemon)
        self.timers.append(timer)

        def cancel() -> None:
            timer.alive = False

        return cancel

    def flush(self) -> None:
        self._world.run_nested(lambda: False, timers=False)

    def flush_as(self, root: object) -> None:
        self.root = root
        try:
            self.flush()
        finally:
            self.root = None
            held, self._held = self._held, []
            for task, _ in held:
                self._enqueue(task)

    def run_until(self, done: Callable[[], bool], *, stall_timeout: float | None = None) -> None:
        self._world.run_nested(done, timers=True)


# --- simulated threads ------------------------------------------------------------------


class _SimThread:
    """A generator stepped one ``yield`` at a time, in a ``contextvars``
    context of its own, as a real thread has."""

    def __init__(self, name: str, body: Callable[[], ThreadBody]) -> None:
        self.name = name
        self.context = contextvars.Context()
        self._body = body
        self._gen: ThreadBody | None = None
        self.guard: Guard | None = None
        self.finished = False

    def enabled(self) -> bool:
        return not self.finished and (self.guard is None or self.guard())

    def step(self) -> None:
        self.context.run(self._advance)

    def _advance(self) -> None:
        if self._gen is None:
            self._gen = self._body()
        try:
            self.guard = next(self._gen)
        except StopIteration:
            self.finished = True


# --- choosers ----------------------------------------------------------------------------


class Chooser(Protocol):
    def choose(self, actions: Sequence[Action], step: int) -> int: ...


class DivergedError(Exception):
    """A replayed schedule offered different choices than when recorded:
    the scenario is not deterministic."""


class Replay:
    """The choices of ``prefix``, then always the first enabled action.

    ``strict`` (exploring, debugging): a choice past the enabled actions
    raises ``DivergedError``. Otherwise (a regression test, whose schedule
    was recorded against the runtime before its fix, which may take other
    steps now) it wraps around, and ``diverged_at`` records where."""

    def __init__(self, prefix: Sequence[int], *, strict: bool = True) -> None:
        self.prefix = list(prefix)
        self.strict = strict
        self.diverged_at: int | None = None

    def choose(self, actions: Sequence[Action], step: int) -> int:
        if step >= len(self.prefix):
            return 0
        choice = self.prefix[step]
        if choice < len(actions):
            return choice
        if self.strict:
            raise DivergedError(
                f"step {step} chose {choice} of {len(actions)} enabled actions; "
                "the scenario does not replay deterministically"
            )
        if self.diverged_at is None:
            self.diverged_at = step
        return choice % len(actions)


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


# --- one run -------------------------------------------------------------------------------


class World:
    """The state of one run: the scheduler, the simulated threads, every
    fiber made during it and what the scenario asked to check."""

    def __init__(
        self,
        chooser: Chooser,
        *,
        order: Order,
        timers: Timers,
        max_steps: int,
        ops: int | None = None,
    ) -> None:
        self.ops = ops
        self.seq = itertools.count()
        self.scheduler = InterleaveScheduler(self)
        self.chooser = chooser
        self.order: Order = order
        self.timers: Timers = timers
        self.max_steps = max_steps
        self.trace: list[tuple[int, int]] = []
        self.log: list[str] = []
        self.problems: list[str] = []
        self.fibers: list[Fiber[Any, Any]] = []
        self.exits: Counter[int] = Counter()
        self.counts: Counter[str] = Counter()
        self.notes: list[object] = []
        self.driving = False
        self.thread_running: str | None = None
        self.driver_context = contextvars.copy_context()
        self._threads: list[_SimThread] = []
        self._checks: list[Callable[[], Problems]] = []
        self._may_stay: set[int] = set()
        self._in_driver_context = False

    # --- what scenarios call ---

    def fork[A, E](self, eff: fx.Effect[A, E], *, must_succeed: bool = True) -> Fiber[A, E]:
        """Start ``eff`` as a root fiber on the scheduler; it first runs
        when the harness picks its start task. Unless ``must_succeed`` is
        off, the run fails if it ends any other way."""
        fiber = fx.run_fork(self.budgeted(eff), scheduler=self.scheduler)
        if must_succeed:
            self.check(lambda: _succeeded(fiber))
        return fiber

    def budgeted[A, E, R](self, eff: fx.Effect[A, E, R]) -> fx.Effect[A, E, R]:
        """``eff`` with the scenario's step budget (``Scenario.ops``); for
        runs a scenario starts itself, from a simulated thread."""
        if self.ops is None:
            return eff
        return eff.pipe(fx.provide_service(fx.MaxOpsBeforeYield, self.ops))

    def thread(self, name: str, body: Callable[[], ThreadBody]) -> None:
        """A simulated thread: each ``yield`` is a point where others may
        run; yielding a ``Guard`` waits until it holds."""
        self._threads.append(_SimThread(name, body))

    def check(self, f: Callable[[], Problems]) -> None:
        """Run ``f`` once the run is over; it names what went wrong."""
        self._checks.append(f)

    def bump(self, name: str) -> fx.Effect[None]:
        """An effect counting one ``name`` (a finalizer, an acquire)."""
        return fx.sync(lambda: self.counts.update((name,)))

    def may_stay_unfinished(self, fiber: Fiber[Any, Any]) -> None:
        """``fiber`` is allowed to still be running when the run is over."""
        self._may_stay.add(fiber.id)

    # --- driving ---

    def enabled(self, *, timers: bool = True, threads: bool = True) -> list[Action]:
        sched = self.scheduler
        tasks = sched.tasks if self.order == "any" else sched.tasks[:1]
        actions = [Action("task", ("task", p.seq), p.label) for p in tasks]
        if timers and (self.timers == "anytime" or not sched.tasks):
            live = [t for t in sched.timers if t.alive and not t.daemon]
            if live:
                soonest = min(t.when for t in live)
                actions += [
                    Action("timer", ("timer", t.seq), t.label) for t in live if t.when == soonest
                ]
        if threads:
            actions += [
                Action("thread", ("thread", t.name), f"thread {t.name}")
                for t in self._threads
                if t.enabled()
            ]
        return actions

    def _take(self, action: Action) -> Callable[[], None]:
        sched = self.scheduler
        if action.kind == "task":
            index = next(i for i, p in enumerate(sched.tasks) if p.seq == action.key[1])
            return self._as_driver(sched.tasks.pop(index).task)
        if action.kind == "timer":
            timer = next(t for t in sched.timers if t.seq == action.key[1])
            sched.timers.remove(timer)
            sched.now = max(sched.now, timer.when)
            return self._as_driver(timer.task)
        thread = next(t for t in self._threads if t.name == action.key[1])
        return lambda: self._as_thread(thread)

    def _as_driver(self, task: Task) -> Callable[[], None]:
        def run() -> None:
            driving, self.driving = self.driving, True
            try:
                if self._in_driver_context:
                    task()
                else:
                    self._in_driver_context = True
                    try:
                        self.driver_context.run(task)
                    finally:
                        self._in_driver_context = False
            finally:
                self.driving = driving

        return run

    def _as_thread(self, thread: _SimThread) -> None:
        self.thread_running = thread.name
        try:
            thread.step()
        finally:
            self.thread_running = None

    def _step(self, actions: list[Action]) -> None:
        if len(self.trace) >= self.max_steps:
            raise _Stop(f"no end after {self.max_steps} steps (a livelock, or raise max_steps)")
        choice = self.chooser.choose(actions, len(self.trace))
        self.trace.append((choice, len(actions)))
        action = actions[choice]
        self.log.append(action.label)
        run = self._take(action)
        try:
            run()
        except _Stop:
            raise
        except BaseException as exc:
            raise _Stop(f"{action.label} raised {exc!r}") from exc

    def run(self) -> None:
        while actions := self.enabled():
            self._step(actions)

    def run_nested(self, done: Callable[[], bool], *, timers: bool) -> None:
        """A simulated thread drives the scheduler itself (``run_sync``,
        ``run_blocking``): tasks (and timers) run, chosen as usual, until
        ``done``; the other threads wait for it."""
        thread = self.thread_running
        self.thread_running = None
        try:
            while not done():
                actions = self.enabled(timers=timers, threads=False)
                if not actions:
                    if timers:
                        raise StalledError("every fiber is waiting and nothing can wake them")
                    return
                self._step(actions)
        finally:
            self.thread_running = thread

    def final_problems(self) -> list[str]:
        problems = list(self.problems)
        for fiber in self.fibers:
            ended = self.exits[fiber.id]
            if ended > 1:
                problems.append(f"{fiber!r} ended {ended} times")
            elif ended == 0 and fiber.id not in self._may_stay:
                state = "parked" if fiber._waiting is not None else fiber._phase
                problems.append(f"{fiber!r} never ended ({state}): a lost wake-up or a deadlock")
        problems += [f"thread {t.name} never finished" for t in self._threads if not t.finished]
        for check in self._checks:
            found = check()
            if isinstance(found, str):
                problems.append(found)
            elif found:
                problems.extend(found)
        return problems


def _succeeded(fiber: Fiber[Any, Any]) -> Problems:
    ex = fiber._exit
    if ex is None or isinstance(ex, fx.Success):
        return None  # never ending is reported for every fiber
    return f"{fiber!r} (a root) failed: {ex.cause.pretty()}"


class _Stop(Exception):
    """Ends a run early: something raised, or it ran too long."""


@contextmanager
def _observing(world: World) -> Generator[None]:
    """Count each fiber's exits for the run (test-only patching; the fiber
    loop itself has no hook)."""
    originals = {name: vars(Fiber)[name] for name in ("__init__", "_finish")}
    init = cast("Callable[..., None]", originals["__init__"])
    finish = cast("Callable[[Fiber[Any, Any], Exit[Any, Any]], object]", originals["_finish"])

    def observed_init(self: Fiber[Any, Any], *args: Any, **kwargs: Any) -> None:
        init(self, *args, **kwargs)
        world.fibers.append(self)

    def observed_finish(self: Fiber[Any, Any], ex: Exit[Any, Any]) -> object:
        before = self._exit
        nxt = finish(self, ex)
        if before is not None:
            world.problems.append(f"{self!r} finished again after its exit")
        elif self._exit is not None:
            world.exits[self.id] += 1
        return nxt

    patches = {"__init__": observed_init, "_finish": observed_finish}
    for name, patched in patches.items():
        setattr(Fiber, name, patched)
    try:
        yield
    finally:
        for name, original in originals.items():
            setattr(Fiber, name, original)


# --- scenarios and exploration --------------------------------------------------------------


@dataclass(frozen=True)
class Scenario:
    """``build`` sets up one run on the ``World`` it is given: root fibers
    (``world.fork``), simulated threads and checks. It must do the same
    thing every time, so a schedule replays.

    ``runs`` is the default budget (schedules); ``PYFECT_INTERLEAVE_BUDGET``
    (seconds per scenario) replaces it for longer runs."""

    name: str
    build: Callable[[World], None]
    order: Order = "any"
    timers: Timers = "anytime"
    runs: int = 2000
    max_steps: int = 3000
    ops: int | None = None
    """The fibers' ``MaxOpsBeforeYield``: a small one makes nearly every
    step a point where a fiber pauses and others run."""

    def __repr__(self) -> str:
        return self.name

    def with_ops(self, ops: int) -> Scenario:
        return replace(self, name=f"{self.name}[ops={ops}]", ops=ops)


@dataclass
class Outcome:
    choices: list[int]
    trace: list[tuple[int, int]]
    log: list[str]
    problems: list[str]
    notes: list[object]


def run_once(scenario: Scenario, chooser: Chooser) -> Outcome:
    world = World(
        chooser,
        order=scenario.order,
        timers=scenario.timers,
        max_steps=scenario.max_steps,
        ops=scenario.ops,
    )
    with _observing(world), warnings.catch_warnings(record=True) as warned:
        # A runtime warning (the test clock giving up on a woken fiber, say)
        # is a failure of the run.
        warnings.simplefilter("always")
        try:
            world.driver_context.run(scenario.build, world)
            world.run()
        except _Stop as stop:
            world.problems.append(str(stop))
        world.problems += [f"warned: {w.category.__name__}: {w.message}" for w in warned]
        problems = world.final_problems()
    return Outcome([c for c, _ in world.trace], world.trace, world.log, problems, world.notes)


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


class InterleaveFailure(AssertionError):
    pass


def _fail(scenario: Scenario, how: str, outcome: Outcome) -> InterleaveFailure:
    schedule = encode(outcome.choices)
    tail = outcome.log[-40:]
    skipped = len(outcome.log) - len(tail)
    lines = [
        f"interleaving scenario {scenario.name!r} failed ({how}).",
        f"Replay it with: replay(BY_NAME[{scenario.name!r}], {schedule!r})",
        "Problems:",
        *(f"  - {p}" for p in outcome.problems),
        f"Last {len(tail)} of {len(outcome.log)} steps:",
        *(f"  {skipped + i}: {label}" for i, label in enumerate(tail)),
    ]
    return InterleaveFailure("\n".join(lines))


def replay(scenario: Scenario, schedule: str, *, strict: bool = True) -> Outcome:
    """Run ``scenario`` under exactly ``schedule``; raise if it fails. A
    regression test passes ``strict=False`` (see ``Replay``)."""
    outcome = run_once(scenario, Replay(decode(schedule), strict=strict))
    if outcome.problems:
        raise _fail(scenario, f"replaying {schedule!r}", outcome)
    return outcome


@dataclass
class Report:
    scenario: str
    runs: int = 0
    distinct: int = 0
    exhaustive: bool = False
    deviations: int = 0
    seeds: int = 0
    seconds: float = 0.0
    seen: set[str] = field(default_factory=set[str], repr=False)

    def __str__(self) -> str:
        how = "exhaustive" if self.exhaustive else f"deviations<={self.deviations}"
        return (
            f"{self.scenario}: {self.distinct} distinct schedules in {self.runs} runs "
            f"({how}, {self.seeds} seeded) in {self.seconds:.2f}s"
        )


class _Budget:
    """Runs left (or, with ``PYFECT_INTERLEAVE_BUDGET``, time left); a
    phase's share charges its parent."""

    def __init__(self, runs: int, seconds: float | None, parent: _Budget | None = None) -> None:
        self._runs = runs
        self._deadline = None if seconds is None else time.monotonic() + seconds
        self._parent = parent
        self.used = 0

    def take(self) -> bool:
        if self._deadline is not None:
            return time.monotonic() < self._deadline
        if self.used >= self._runs:
            return False
        self.used += 1
        if self._parent is not None:
            self._parent.used += 1
        return True

    def share(self, fraction: float) -> _Budget:
        """A budget for one phase: ``fraction`` of what is left."""
        if self._deadline is None:
            return _Budget(int((self._runs - self.used) * fraction), None, self)
        left = max(self._deadline - time.monotonic(), 0.0)
        return _Budget(0, left * fraction, self)


def _budget_seconds() -> float | None:
    raw = os.environ.get(BUDGET_ENV)
    return None if not raw else float(raw)


def explore(scenario: Scenario, *, runs: int | None = None) -> Report:
    """Run ``scenario`` under many schedules; raise ``InterleaveFailure``
    naming the first that breaks an invariant. Half the budget goes to
    schedules with few deviations from FIFO order (all of them, if the
    tree is that small), the rest to seeded random walks and PCT-style
    priority schedules."""
    seconds = _budget_seconds()
    budget = _Budget(scenario.runs if runs is None else runs, seconds)
    report = Report(scenario.name)
    start = time.monotonic()
    baseline = _bounded_dfs(scenario, budget.share(0.5), report)
    if not report.exhaustive:
        _seeded(scenario, budget.share(1.0), report, baseline)
    report.seconds = time.monotonic() - start
    return report


def _record(scenario: Scenario, report: Report, outcome: Outcome, how: str) -> None:
    report.runs += 1
    key = encode(outcome.choices)
    if key not in report.seen:
        report.seen.add(key)
        report.distinct += 1
    if outcome.problems:
        raise _fail(scenario, how, outcome)


def _bounded_dfs(scenario: Scenario, budget: _Budget, report: Report) -> int:
    """Depth-first over the choice tree, allowing at most ``k`` non-first
    choices, for k = 0, 1, 2, ... A level that pruned nothing has seen the
    whole tree. Returns the length of the FIFO run (PCT's horizon)."""
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
            _record(scenario, report, outcome, f"exploring with at most {k} deviations")
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


def _first_seed() -> int:
    raw = os.environ.get(SEED_ENV)
    return 0 if not raw else int(raw)


def _seeded(scenario: Scenario, budget: _Budget, report: Report, baseline: int) -> None:
    seed = _first_seed()
    while budget.take():
        chooser: Chooser
        if seed % 2 == 0:
            chooser = RandomWalk(seed)
            how = f"random walk, seed {seed}"
        else:
            chooser = Priorities(seed, depth=3, length=baseline)
            how = f"PCT-style priorities, seed {seed}"
        outcome = run_once(scenario, chooser)
        report.seeds += 1
        _record(scenario, report, outcome, how)
        seed += 1
