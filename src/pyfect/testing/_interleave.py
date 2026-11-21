"""One run of an effect under a schedule the caller chooses (the engine of
``pyfect.testing.explore`` and of ``tests/interleave``).

``InterleaveScheduler`` runs nothing itself: every point where the runtime
hands work over (a scheduled task, a ``call_later`` timer, a ``wake_soon``,
a resume or interrupt sent from another thread) becomes a pending action.
At each step ``World`` lists the enabled actions in a fixed order (tasks
oldest first, then the due timers, then the simulated threads that can go
on) and asks a ``Chooser`` which one runs next, so a run is its list of
choices and replays exactly. Simulated threads are generators stepped one
yield at a time, outside any fiber and with the scheduler not running, so
what they do takes the runtime's cross-thread paths. Timers use virtual
time: only the soonest fire, and firing one moves time to it.

The fibers of a run are counted through ``FiberRuntimeMetrics``, the
runtime's own hook for fiber starts and ends: a root forked with
``World.fork`` (or started with ``World.context``) carries it, and so does
every fiber it forks.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import contextvars
import itertools
import threading
import warnings
from collections import Counter
from collections.abc import Callable, Generator, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol

from pyfect._core import Effect
from pyfect._fiber import Fiber, current_fiber, current_run_scheduler
from pyfect._metric_ref import FiberRuntimeMetrics
from pyfect.context import Context
from pyfect.duration import Duration
from pyfect.effect import provide_service, sync
from pyfect.exit import Exit, Success
from pyfect.run import run_fork
from pyfect.scheduler import (
    Cancel,
    MaxOpsBeforeYield,
    StalledError,
    SyncOnlyScheduler,
    SyncScheduler,
    Task,
)

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
    inner: object = task
    while hasattr(inner, "func"):  # functools.partial
        inner = getattr(inner, "func")  # noqa: B009
    name: str = getattr(inner, "__qualname__", type(inner).__name__)
    name = name.replace(".<locals>", "").replace(".<lambda>", "")
    fibers: list[str] = []
    cells: tuple[Any, ...] = getattr(inner, "__closure__", None) or ()
    for cell in cells:
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


# --- the run's fibers ------------------------------------------------------------------------


class _FiberLedger:
    """The run's ``FiberRuntimeMetrics``: how many fibers started, how often
    each ended, and the fibers that started others (to name the ones that
    never ended). A fiber ends in its own run, so ``current_fiber()`` is the
    one ending."""

    def __init__(self) -> None:
        self.started = 0
        self.ended: Counter[int] = Counter()
        self.parents: dict[int, Fiber[Any, Any]] = {}
        self.stray_ends = 0

    def record_fiber_start(self, context: Context[Any]) -> None:
        self.started += 1
        parent = current_fiber()
        if parent is not None:
            self.parents[parent.id] = parent

    def record_fiber_end(self, context: Context[Any], exit: Exit[Any, Any]) -> None:
        fiber = current_fiber()
        if fiber is None:
            self.stray_ends += 1
        else:
            self.ended[fiber.id] += 1


def _fiber_state(fiber: Fiber[Any, Any]) -> str:
    return "parked" if fiber._waiting is not None else fiber._phase


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


# --- choosing --------------------------------------------------------------------------------


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


# --- one run -------------------------------------------------------------------------------


class World:
    """The state of one run: the scheduler, the simulated threads, the
    run's fibers and what the scenario asked to check."""

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
        self.counts: Counter[str] = Counter()
        self.notes: list[object] = []
        self.driving = False
        self.thread_running: str | None = None
        self.driver_context = contextvars.copy_context()
        self._ledger = _FiberLedger()
        self.context: Context[Any] = Context.make(FiberRuntimeMetrics, self._ledger)
        """The context a run started outside ``fork`` takes, so its fibers are
        counted (``fx.run_fork(eff, scheduler=w.scheduler, context=w.context)``)."""
        self._roots: list[Fiber[Any, Any]] = []
        self._threads: list[_SimThread] = []
        self._checks: list[Callable[[], Problems]] = []
        self._in_driver_context = False

    # --- what scenarios call ---

    def fork[A, E](self, eff: Effect[A, E], *, must_succeed: bool = True) -> Fiber[A, E]:
        """Start ``eff`` as a root fiber on the scheduler; it first runs
        when the harness picks its start task. Unless ``must_succeed`` is
        off, the run fails if it ends any other way."""
        fiber = run_fork(self.budgeted(eff), scheduler=self.scheduler, context=self.context)
        self._roots.append(fiber)
        if must_succeed:
            self.check(lambda: _succeeded(fiber))
        return fiber

    def budgeted[A, E, R](self, eff: Effect[A, E, R]) -> Effect[A, E, R]:
        """``eff`` with the scenario's step budget (``Scenario.ops``); for
        runs a scenario starts itself, from a simulated thread."""
        if self.ops is None:
            return eff
        return eff.pipe(provide_service(MaxOpsBeforeYield, self.ops))

    def thread(self, name: str, body: Callable[[], ThreadBody]) -> None:
        """A simulated thread: each ``yield`` is a point where others may
        run; yielding a ``Guard`` waits until it holds."""
        self._threads.append(_SimThread(name, body))

    def check(self, f: Callable[[], Problems]) -> None:
        """Run ``f`` once the run is over; it names what went wrong."""
        self._checks.append(f)

    def bump(self, name: str) -> Effect[None]:
        """An effect counting one ``name`` (a finalizer, an acquire)."""
        return sync(lambda: self.counts.update((name,)))

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

    def _fiber_problems(self) -> list[str]:
        ledger = self._ledger
        problems = [f"Fiber(#{fid}) ended {n} times" for fid, n in ledger.ended.items() if n > 1]
        if ledger.stray_ends:
            problems.append(f"{ledger.stray_ends} fiber ends outside any fiber's run")
        unfinished = ledger.started - len(ledger.ended)
        if unfinished <= 0:
            return problems
        named = [f for f in self._known_fibers() if f._exit is None]
        problems += [
            f"{f!r} never ended ({_fiber_state(f)}): a lost wake-up or a deadlock" for f in named
        ]
        if unfinished > len(named):
            problems.append(
                f"{unfinished - len(named)} more fibers never ended: a lost wake-up or a deadlock"
            )
        return problems

    def _known_fibers(self) -> list[Fiber[Any, Any]]:
        """The roots, the fibers that started others, and their children."""
        found: dict[int, Fiber[Any, Any]] = {}
        todo = [*self._roots, *self._ledger.parents.values()]
        while todo:
            fiber = todo.pop()
            if fiber.id not in found:
                found[fiber.id] = fiber
                todo += fiber._children
        return sorted(found.values(), key=lambda f: f.id)

    def final_problems(self) -> list[str]:
        problems = [*self.problems, *self._fiber_problems()]
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
    if ex is None or isinstance(ex, Success):
        return None  # never ending is reported for every fiber
    return f"{fiber!r} (a root) failed: {ex.cause.pretty()}"


class _Stop(Exception):
    """Ends a run early: something raised, or it ran too long."""


# --- scenarios -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Scenario:
    """``build`` sets up one run on the ``World`` it is given: root fibers
    (``world.fork``), simulated threads and checks. It must do the same
    thing every time, so a schedule replays. ``runs`` is the default
    budget (schedules)."""

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
    with warnings.catch_warnings(record=True) as warned:
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
