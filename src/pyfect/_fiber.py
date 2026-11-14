"""The fiber runtime.

A fiber runs one effect. It keeps an explicit stack of continuation frames
(so deep chains never hit Python's recursion limit) and runs on a
``Scheduler``. It never blocks: when it has to wait, it registers a resume
callback and parks (``SUSPEND``).

Resumes follow Effect's ``evaluate``: a resume, an interrupt or a start
called on the thread running the fiber's run runs the fiber at once,
nested in the caller, up to its next wait or yield, before the call
returns. A fork with ``start_immediately`` runs the child before the fork
returns. Nesting is bounded (``_MAX_NESTED_RUNS``): deeper than that, the
fiber runs right after the innermost running fiber's run instead, so a
chain of wake-ups cannot overflow the stack. Calls from other threads go
through the fiber's scheduler.

Interruption follows Effect's rules:

- Interrupting a fiber records an ``Interrupt`` at once when the caller is
  on the thread of the fiber's run (otherwise via the scheduler). If the
  fiber is interruptible and not running, it is unwound right away: a fiber
  that has not started never runs its body, a parked fiber has its wait
  cancelled (running its canceler), and a fiber queued after a yield or a
  step-budget pause is unwound instead of resuming. A running fiber,
  including one that interrupts itself, stops at its next step. A fiber
  whose resume another thread already queued gets the interrupt after that
  resumed run, since in Effect the resume would already have run.
- While interruptible and interrupted, the loop turns whatever comes next
  into a failure, so the stack unwinds. Recovery handlers are skipped;
  finalizers run, because they run in uninterruptible regions. The exit a
  step returns reaches its continuation with no pause in between, so a
  result the step decided (a taken item, an applied update) is never
  dropped by an interrupt landing at a yield.
- Inside an uninterruptible region the interrupt waits until the region
  ends.

Supervision: a fiber's children (from ``fork``) are interrupted and awaited
before the fiber completes.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import contextlib
import contextvars
import itertools
import math
import threading
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any, Generic, Literal, Never, TypeVar

from pyfect._core import (
    SUSPEND,
    Effect,
    Frame,
    Register,
    Step,
    _Callback,
    _FromExit,
    _RestoreInterruptible,
    _run_finalizer,
    _Succeed,
    _Sync,
    _WithFiber,
    run_known,
)
from pyfect._effect_base import Decided, HandedOn
from pyfect._interrupt_reason import closed
from pyfect._metric_ref import FiberRuntimeMetrics
from pyfect._primitives import known_exit
from pyfect._priority_buckets import PriorityBuckets
from pyfect._stack_frame import CurrentStackFrame, InterruptorStackTrace, StackFrame, StackTrace
from pyfect._tracer_ref import CurrentTracer
from pyfect._wake_tracking import Tracking, WakeTracker
from pyfect.cause import Cause
from pyfect.cause import interrupt as interrupt_cause
from pyfect.context import Context, Reference, Tag
from pyfect.duration import Duration
from pyfect.exit import Exit, Failure, Success
from pyfect.exit import die as exit_die
from pyfect.scheduler import (
    AsyncioScheduler,
    BoundScheduler,
    Cancel,
    CurrentScheduler,
    EffectScheduler,
    MaxOpsBeforeYield,
    PreventSchedulerYield,
    Scheduler,
    SyncOnlyScheduler,
    SyncScheduler,
    Task,
)

if TYPE_CHECKING:
    from pyfect._metric_ref import FiberRuntimeMetricsService
    from pyfect.scope import CloseableScope
    from pyfect.tracer import ContextHook

A_co = TypeVar("A_co", covariant=True)
E_co = TypeVar("E_co", covariant=True, default=Never)

# Effect's ``maxInlineSteps`` (a power of two): of the successes frames
# hand on with ``succeed_with``, every this-many-th goes back through the
# loop, where the fiber may yield.
_INLINE_STEPS = 32

# How many fiber runs may nest on one thread (a resume running the woken
# fiber inside the resumer's step, and so on). Past it, a run waits for the
# innermost one to finish, so the Python stack stays bounded.
_MAX_NESTED_RUNS = 16

_EXITS = (Success, Failure)
_VOID: Effect[None] = _Succeed(None)

type RunScheduler = SyncScheduler | AsyncioScheduler
"""The schedulers pyfect runs fibers on: each fiber of one keeps its own batch."""

_fiber_ids = itertools.count(1)
_resume_lock = threading.Lock()


type _Run = tuple[Fiber[Any, Any], Step]


class _Drain:
    """Fiber runs of one run scheduler on this thread, nested ``depth``
    runs deep: the fiber running now, then ``queue``, the runs that came in
    while it ran but could not nest any deeper. ``first`` collects the runs
    the current run hands over that way (children started immediately,
    then the rest of the forking fiber), which go before everything
    queued."""

    __slots__ = ("current", "depth", "first", "queue", "run_scheduler")

    def __init__(self, run_scheduler: Scheduler, depth: int) -> None:
        self.run_scheduler = run_scheduler
        self.depth = depth
        self.current: Fiber[Any, Any] | None = None
        # Made on first use: most drains run one fiber once.
        self.queue: deque[_Run] | None = None
        self.first: list[_Run] | None = None

    def push(self, run: _Run) -> None:
        if self.queue is None:
            self.queue = deque()
        self.queue.append(run)

    def push_first(self, run: _Run) -> None:
        if self.first is None:
            self.first = []
        self.first.append(run)


class _ThreadState(threading.local):
    """The drain running fibers on this thread, if any. It also knows the
    fiber running now, so a fiber switch costs no thread-local writes."""

    drain: _Drain | None = None


_thread = _ThreadState()


def current_fiber() -> Fiber[Any, Any] | None:
    """The fiber running on this thread, if any."""
    drain = _thread.drain
    return None if drain is None else drain.current


def current_run_scheduler() -> Scheduler | None:
    """The scheduler of the run whose fiber is running on this thread."""
    drain = _thread.drain
    return None if drain is None or drain.current is None else drain.run_scheduler


type Uninterruptible = bool | Literal["inherit"]
"""A forked fiber's starting interruptibility: ``False`` (interruptible),
``True``, or ``"inherit"`` the forking fiber's."""

type _Phase = Literal["pending", "running", "idle"]
"""``pending``: forked, first run not yet started. ``running``: inside
``_run``. ``idle``: parked in a wait, or queued to run again."""


class _Wait:
    """One suspension. ``resume`` is safe to call from any thread, any
    number of times; only the first call counts. ``done``, ``registering``
    and ``sync_result`` change together under ``_resume_lock``: a resume
    racing the end of registration on another thread (free-threaded
    builds have no GIL to order them) either lands in ``sync_result``
    before registration reads it, or sees registration over and resumes
    the parked fiber.

    The wait lets go of its fiber once claimed: ``resume`` is handed to the
    outside (a future's callbacks, a listener list), which may keep it
    after it fired, and must not keep the fiber, and its result, alive."""

    __slots__ = ("canceler", "done", "fiber", "registering", "sync_result")

    def __init__(self, fiber: Fiber[Any, Any]) -> None:
        self.fiber: Fiber[Any, Any] | None = fiber
        self.done = False  # pragma: no mutate, falsy until claimed
        self.registering = True
        self.sync_result: Effect[Any, Any, Any] | None = None
        self.canceler: Effect[Any, Any, Any] | None = None

    def claim(self) -> bool:
        with _resume_lock:
            if self.done:
                return False
            self.done = True  # pragma: no mutate, read only before a claim
            self.fiber = None
            return True

    def end_registration(self) -> Effect[Any, Any, Any] | None:
        """Registration is over; the effect a resume during it left."""
        with _resume_lock:
            self.registering = False  # pragma: no mutate, falsy either way
            result, self.sync_result = self.sync_result, None
            return result

    def resume(self, effect: Effect[Any, Any, Any]) -> None:
        with _resume_lock:
            fiber = self.fiber
            if fiber is None:
                return
            self.done = True
            self.fiber = None
            canceler, self.canceler = self.canceler, None
            if self.registering:
                self.sync_result = effect
                return
        if fiber._on_run_thread():
            fiber._resume(self, effect, canceler)
        else:
            fiber._scheduler.schedule(lambda: fiber._resume(self, effect, canceler))


class _Yielded:
    """A run queued on the scheduler after a yield or a step-budget pause.
    An interrupt takes it over (``Fiber._deliver_interrupt``); the queued
    task then finds it gone and does nothing."""

    __slots__ = ("decided", "ops", "step")

    def __init__(self, step: Step, *, ops: int, decided: bool) -> None:
        self.step = step
        # The ops the resumed run starts with spent (see ``Fiber._pause_due``).
        self.ops = ops
        # ``step`` holds a claimed result (``run_known``): an interrupt that
        # lands in the pause waits until it has reached its continuation.
        self.decided = decided


class _ReturnExit(Frame):
    """Finish with a stored exit, ignoring whatever ran above it."""

    __slots__ = ("exit",)

    def __init__(self, ex: Exit[Any, Any]) -> None:
        self.exit = ex

    def _on_success(self, value: Any, fiber: Fiber[Any, Any]) -> Step:
        return self.exit

    def _on_failure(self, cause: Cause[Any], fiber: Fiber[Any, Any]) -> Step:
        return self.exit


class Fiber(Generic[A_co, E_co]):
    """A running effect. Obtain one with ``eff.fork()``."""

    __slots__ = (
        "__weakref__",
        "_async_context",
        "_batch",
        "_batch_first",
        "_batch_others",
        "_batch_run",
        "_children",
        "_ctx",
        "_decided_on_resume",
        "_exit",
        "_interrupt",
        "_interrupt_fresh",
        "_interruptible",
        "_interrupts_after_resume",
        "_observers",
        "_ops_budget",
        "_ops_on_resume",
        "_parent",
        "_phase",
        "_run_scheduler",
        "_runtime_metrics",
        "_scheduler",
        "_should_yield",
        "_stack",
        "_stack_frame",
        "_tracer_hook",
        "_view",
        "_waiting",
        "_yielded",
        "current_op_count",
        "id",
    )

    def __init__(
        self,
        run_scheduler: Scheduler,
        context: Context,
        parent: Fiber[Any, Any] | None,
        *,
        interruptible: bool = True,
    ) -> None:
        """A fiber of the run driven by ``run_scheduler``. It runs on
        ``context``'s ``CurrentScheduler``."""
        self.id = next(_fiber_ids)
        self._run_scheduler = run_scheduler
        self.current_op_count = 0  # pragma: no mutate, set before every read
        self._parent = parent
        self._stack: list[Frame] = []
        self._interruptible = interruptible
        self._interrupt: Cause[Never] | None = None
        # Interrupts that arrived while a resume was queued (see _resume).
        self._interrupts_after_resume: list[tuple[int | None, Context | None]] = []
        # A dict, not a set: children are interrupted in fork order, as in Effect.
        self._children: dict[Fiber[Any, Any], None] = {}
        self._observers: list[Callable[[Exit[Any, Any]], None]] = []
        self._exit: Exit[Any, Any] | None = None
        self._waiting: _Wait | None = None
        self._yielded: _Yielded | None = None
        self._ops_on_resume = 0
        self._decided_on_resume = False  # pragma: no mutate, taken at every run's start
        # An interrupt delivered to the running fiber that its loop has not met
        # yet (Effect's ``_deferredInterrupt``): it replaces whatever comes
        # next, a failure too, where one met later is added to failures.
        self._interrupt_fresh = False
        self._phase: _Phase = "pending"
        # The ``contextvars`` context the fiber parked or paused in, which
        # it resumes in (Effect's captured async context), or that started
        # it, when its first run is scheduled (see _start).
        self._async_context: contextvars.Context | None = None
        self._batch_first: Task | _Yielded | None = None
        self._batch: list[Task] | None = None
        self._batch_others: PriorityBuckets | None = None
        self._set_context(context)
        if self._runtime_metrics is not None:
            self._runtime_metrics.record_fiber_start(self._ctx)

    def __repr__(self) -> str:
        return f"Fiber(#{self.id})"

    # --- public API (all effects, except the ``unsafe_`` reads) ------------

    def await_exit(self) -> Effect[Exit[A_co, E_co], Never, Never]:
        """Wait for the fiber and succeed with its ``Exit``."""
        # As Effect's ``fiberAwait``: ``succeed(exit)``.
        return self._when_exited(_Succeed)

    def join(self) -> Effect[A_co, E_co, Never]:
        """Wait for the fiber and take on its result: its value, or its
        failure."""
        # As Effect's ``fiberJoin``: the exit itself.
        return self._when_exited(_FromExit)

    def _when_exited[B, EB](
        self, then: Callable[[Exit[A_co, E_co]], Effect[B, EB]]
    ) -> Effect[B, EB]:
        """``then(exit)`` once the fiber has ended: at once for an ended
        fiber (no callback, as Effect's), else on its observer."""
        if self._exit is not None:
            return then(self._exit)

        def register(resume: Callable[[Effect[Any, Any, Any]], None]) -> Effect[None] | None:
            if self._exit is not None:
                resume(then(self._exit))
                return None

            def observer(ex: Exit[Any, Any]) -> None:
                resume(then(ex))

            self._observers.append(observer)
            if self._exit is not None:
                # It finished on another thread (a fiber of another run)
                # between the check and the append; resume counts once.
                resume(then(self._exit))
                return None
            return _Sync(lambda: self._remove_observer(observer))

        return _Callback(register)

    def interrupt(self) -> Effect[None, Never, Never]:
        """Interrupt the fiber and wait until it has finished cleaning up.
        Read the outcome with ``await_exit``."""
        # As Effect: ``withFiber`` giving its id to ``interruptAs``.
        return _WithFiber(lambda me: self.interrupt_as(me.id))

    def interrupt_as(
        self, by: int | None, annotations: Context | None = None
    ) -> Effect[None, Never, Never]:
        """``interrupt``, attributed to the fiber with id ``by``; ``annotations`` are
        added to the interruption, after the interrupting fiber's own."""
        return _WithFiber(lambda me: self._interrupt_from(me, by, annotations))

    def _interrupt_from(
        self, me: Fiber[Any, Any], by: int | None, annotations: Context | None = None
    ) -> Effect[None, Never, Never]:
        own = me._interruptor_annotations()
        if own is not None and annotations is not None:
            own = own.merge(annotations)
        self.interrupt_as_unsafe(by, own if own is not None else annotations)
        return self.await_exit().as_void()

    def run_in(self, scope: CloseableScope) -> Fiber[A_co, E_co]:
        """Tie the fiber to ``scope``: closing it interrupts the fiber, and
        the fiber leaves the scope when it exits. Registering again moves
        the fiber's finalizer to the end, so it runs first. A fiber in an
        already closed scope is interrupted. Call on the scheduler thread."""
        if self._exit is not None:
            return self
        if scope._closed is not None:
            self.interrupt_as_unsafe(self.id, closed("Scope"))
        else:
            scope._watch(self)
        return self

    def get_ref[S](self, reference: type[Reference[S]]) -> S:
        """The value of ``reference`` in this fiber's current context (its
        default when nobody provided one). Loggers read the log annotations
        and spans with it."""
        return self._ctx.get_unsafe(reference)

    @staticmethod
    def get_current() -> Fiber[Any, Any] | None:
        """The fiber running on this thread, if any."""
        return current_fiber()

    @staticmethod
    def await_all[A, E](fibers: Iterable[Fiber[A, E]]) -> Effect[list[Exit[A, E]], Never, Never]:
        """Wait for every fiber; succeed with their exits in order."""
        from pyfect._fiber_all import await_all

        return await_all(fibers)

    @staticmethod
    def join_all[A, E](fibers: Iterable[Fiber[A, E]]) -> Effect[list[A], E, Never]:
        """Wait for every fiber and succeed with their values in order, or
        fail with the first failure (the others keep running)."""
        from pyfect._fiber_all import join_all

        return join_all(fibers)

    @staticmethod
    def interrupt_all(fibers: Iterable[Fiber[Any, Any]]) -> Effect[None, Never, Never]:
        """Interrupt every fiber and wait for all of them to finish."""
        from pyfect._fiber_all import interrupt_all

        return interrupt_all(fibers)

    @staticmethod
    def interrupt_all_as(
        fibers: Iterable[Fiber[Any, Any]], by: int | None
    ) -> Effect[None, Never, Never]:
        """``interrupt_all``, attributed to the fiber with id ``by``."""
        from pyfect._fiber_all import interrupt_all_as

        return interrupt_all_as(fibers, by)

    def poll_unsafe(self) -> Exit[A_co, E_co] | None:
        """The exit if the fiber is done. Only meaningful on the fiber's
        scheduler thread."""
        return self._exit

    def interrupt_as_unsafe(self, by: int | None, annotations: Context | None = None) -> None:
        """Ask the fiber to stop. Safe from any thread; does not wait.

        From the thread running the fiber's run (a fiber of it, or code
        outside any fiber there) it takes effect at once (as Effect's
        ``interruptUnsafe``); from other threads it goes through the
        scheduler. The interruption carries ``annotations`` (the
        interrupting fiber's ``InterruptorStackTrace``) and the frame this
        fiber is in (``StackTrace``)."""
        if self._on_run_thread():
            self._deliver_interrupt(by, annotations)
        else:
            self._scheduler.schedule(lambda: self._deliver_interrupt(by, annotations))

    def add_observer_unsafe(
        self, observer: Callable[[Exit[A_co, E_co]], None]
    ) -> Callable[[], None]:
        """Call ``observer`` with the exit once the fiber is done (at once if
        it already is), exactly once, from any thread. Returns a function
        that removes the observer."""
        if self._exit is not None:
            observer(self._exit)
            return _no_op
        observers = self._observers
        observers.append(observer)
        ex = self._exit
        if ex is not None:
            # It finished meanwhile on another thread (its run's), and the
            # finish may or may not have seen the append: whichever of the two
            # takes the observer out of the list calls it.
            try:
                observers.remove(observer)
            except ValueError:
                return _no_op
            observer(ex)
            return _no_op
        return lambda: self._remove_observer(observer)

    # --- runtime internals --------------------------------------------------

    @property
    def _context(self) -> Context:
        return self._ctx

    def _set_context(self, context: Context) -> None:
        """Switch context, and with it the scheduler and step budget read
        from it (Effect's fiber context cache)."""
        view = _last_view[0]
        if (
            view is None
            or (view.given is not context and view.context is not context)
            or view.run_scheduler is not self._run_scheduler
        ):
            view = _last_view[0] = _RunView.of(context, self._run_scheduler)
        self._use_view(view)

    def _use_view(self, view: _RunView) -> None:
        """Switch to ``view``'s context (one this fiber computed before)."""
        _last_view[0] = view
        self._view = view
        self._ctx = view.context
        self._scheduler: Scheduler = view.scheduler
        self._ops_budget: float = view.ops_budget
        self._should_yield: EffectScheduler | None = view.should_yield
        self._tracer_hook: ContextHook | None = view.tracer_hook
        self._runtime_metrics: FiberRuntimeMetricsService | None = view.runtime_metrics
        self._stack_frame: StackFrame | None = view.stack_frame
        self._batch_run: RunScheduler | None = view.batch_run

    def _on_run_thread(self) -> bool:
        """Whether this thread runs this fiber's run now: one of its fibers
        is running here, or its scheduler is running tasks here. Resumes
        and interrupts from here run the fiber at once."""
        return _runs_here(self._run_scheduler)

    def dispatcher(self) -> Scheduler:
        """Where this fiber's tasks wait (Effect's ``fiber.currentDispatcher``):
        the children it forks without starting them, its yields, the wakes
        it makes. On the run's own scheduler that is the fiber's own batch,
        seen as a ``Scheduler`` (``FiberDispatcher``); a provided scheduler,
        or ``run_sync``'s, keeps them itself. Code running in this fiber
        queues with ``_queue`` instead, which needs no view."""
        if self._batch_run is None:
            return self._scheduler
        return FiberDispatcher(self)

    def _queue(self, task: Task, priority: int = 0) -> None:
        """``dispatcher().schedule`` from this fiber's run on this thread (its
        yields, the children it forks, the wakes it makes). Most batches are
        one task at priority 0 and allocate nothing: ``_batch_first`` holds
        the first priority 0 task, ``_batch`` the later ones and
        ``_batch_others`` other priorities, each made on demand. A batch is
        queued on the run while any of them is set."""
        run = self._batch_run
        if run is None:
            self.dispatcher().schedule(task, priority)
            return
        first, others = self._batch_first, self._batch_others
        if first is None and others is None:
            # The run counts the batch for the test clock, and runs it under
            # this task's tracker: that counts its first task too.
            run.schedule(self._run_batch)
        elif run._tracking.tracker is not None:
            task = run._tracked(task)
        if priority != 0:
            if others is None:
                others = self._batch_others = PriorityBuckets()
            others.schedule_task(task, priority)
        elif first is None:
            self._batch_first = task
        else:
            more = self._batch
            if more is None:
                self._batch = [task]
            else:
                more.append(task)

    def _take_batch(self) -> list[Task]:
        """The pending batch in order: lower priorities, then 0, then higher."""
        first, more, others = self._batch_first, self._batch, self._batch_others
        self._batch_first = self._batch = self._batch_others = None
        if isinstance(first, _Yielded):
            first = self._go_on(first)
        ready = ([] if first is None else [first]) + (more or [])
        if others is None:
            return ready
        buckets = others.drain()
        return [
            *(t for p, ts in buckets if p < 0 for t in ts),
            *ready,
            *(t for p, ts in buckets if p > 0 for t in ts),
        ]

    def _run_batch(self) -> None:
        first = self._batch_first
        if self._batch is None and self._batch_others is None:
            # One task: nothing after it for a raise to cut off.
            self._batch_first = None
            if isinstance(first, _Yielded):
                self._resume_yielded(first)
            elif first is not None:
                first()
            return
        batch = self._take_batch()
        done = 0
        try:
            for task in batch:
                done += 1
                task()
        except BaseException:
            # A KeyboardInterrupt, say: the tasks after it still run, ahead of
            # those queued since.
            left = batch[done:]
            if left:
                pending = self._batch_first is not None or self._batch_others is not None
                newer = self._take_batch()
                self._batch_first, self._batch = left[0], left[1:] + newer
                if not pending:
                    self._run_scheduler.schedule(self._run_batch)
            raise

    def _interruptor_annotations(self) -> Context | None:
        """What an interruption this fiber sends records about it."""
        frame = self._stack_frame
        return None if frame is None else Context.make(InterruptorStackTrace, frame)

    def _start(
        self,
        effect: Effect[Any, Any, Any],
        *,
        caller_drives: bool = False,
        parent: Fiber[Any, Any] | None = None,
    ) -> None:
        """Schedule the fiber's first run, in a copy of the caller's
        ``contextvars``, not in the context of whatever drains the scheduler
        then: a scheduler is shared by other callers' runs (a
        ``ManagedRuntime``'s, a loop's), and one request's ContextVars must
        not leak into another's. With ``caller_drives`` (``run_sync``,
        ``run_blocking``) the caller drives the scheduler itself before it
        returns, so the run is in the caller's own context, as Effect's
        synchronous start is. A forked fiber's start waits in its
        ``parent``'s dispatcher, as in Effect."""
        if not caller_drives:
            self._async_context = contextvars.copy_context()
        if parent is None:
            self._scheduler.schedule(lambda: self._drive(effect))
        else:
            parent._queue(lambda: self._drive(effect))

    def _push(self, frame: Frame) -> None:
        self._stack.append(frame)

    def _interrupted_and_interruptible(self) -> bool:
        return self._interrupt is not None and self._interruptible

    def _run(self, start: Step) -> None:
        if self._exit is not None:
            return  # finished early by an interrupt; a stale start or resume
        self._phase = "running"
        parked_in, self._async_context = self._async_context, None
        try:
            if parked_in is None:
                self._loop(start)
            else:
                parked_in.run(self._loop, start)
        finally:
            self._phase = "idle"
            if self._exit is None:
                # Parked or paused: resume in this context, not the waker's.
                self._async_context = contextvars.copy_context() if parked_in is None else parked_in

    def _loop(self, start: Step) -> None:  # noqa: PLR0912
        cur: Step = start
        # Ops are counted as Effect's ``currentOpCount``: one per effect
        # stepped, and one per success a frame hands on with
        # ``succeed_with`` (Effect's ``succeedWith``), every
        # ``_INLINE_STEPS``-th of which goes back through the loop as one
        # more op. Before each op that goes through the loop the fiber
        # pauses once the budget is spent (Effect's ``shouldYield``); an
        # exit handed straight to the next frame is no op, as in Effect.
        ops, self._ops_on_resume = self._ops_on_resume, 0
        # A claimed result the fiber paused before reaches its continuations
        # before an interrupt that landed in the pause: in Effect they all
        # run within the claiming op, so the interrupt waits for the next op.
        guard, self._decided_on_resume = self._decided_on_resume, False
        inline_mask = _INLINE_STEPS - 1
        while True:
            if (
                self._interrupt is not None
                and self._interruptible
                and not (guard and (cur is start or not isinstance(cur, Effect)))
            ):
                guard = False  # pragma: no mutate, cur holds the interrupt now
                cur = self._interrupting(cur, self._interrupt)

            if isinstance(cur, Effect):
                ops += 1
                if ops >= self._ops_budget and self._pause_due(cur, ops):
                    return
                try:
                    hook = self._tracer_hook
                    cur = cur._step(self) if hook is None else _run_hooked(hook, cur, self)
                except BaseException as exc:
                    cur = self._raised(exc)
            elif isinstance(cur, _EXITS):
                # A claimed success is Effect's exit op.
                if type(cur) is Decided:
                    ops += 1
                    if ops >= self._ops_budget and self._pause_due(cur, ops):
                        return
                if not self._stack:
                    nxt = self._finish(cur)
                    if nxt is None:
                        return
                    cur = nxt
                    continue
                # A ``succeed_with`` counts; every ``_INLINE_STEPS``-th
                # goes through the loop as one more op.
                if type(cur) is HandedOn and not (ops := ops + 1) & inline_mask:
                    ops += 1
                    if ops >= self._ops_budget and self._pause_due(cur, ops):
                        return
                frame = self._stack.pop()
                if self._tracer_hook is None and isinstance(cur, Success):
                    # ``_continue``'s common case, inlined: this runs for
                    # every frame a success reaches.
                    try:
                        cur = frame._on_success(cur.value, self)
                    except BaseException as exc:
                        cur = self._raised(exc)
                else:
                    cur = self._continue(frame, cur)
            elif cur is SUSPEND:
                return  # a resume callback will call _run again
            else:  # untyped user code handed back something that is not an effect
                cur = exit_die(TypeError(f"not a valid effect: {cur!r}"))

    def _interrupting(self, cur: Step, interrupt: Cause[Any]) -> Step:
        """``cur`` with ``interrupt`` delivered: a fresh interrupt replaces
        it (Effect's ``_deferredInterrupt``, failures included); a pending
        one is merged into a failure (``_with_interrupt``)."""
        if self._interrupt_fresh:
            self._interrupt_fresh = False
            return _failing(interrupt)
        return self._with_interrupt(cur, interrupt)

    def _pause_due(self, cur: Step, ops: int) -> bool:
        """The budget is spent: pause before ``cur``, unless an
        ``EffectScheduler`` (asked before each op, as in Effect) says not
        to. If ``cur`` is a result just claimed (``run_known``), an
        interrupt that lands in the pause waits until it has reached its
        continuation, where Effect would drop it. A raising
        ``should_yield`` is a defect, which the fiber goes on with after
        the pause."""
        check = self._should_yield
        if check is not None:
            self.current_op_count = ops
            try:
                if not check.should_yield(self):
                    return False
            except BaseException as exc:
                # A plain exit, no op: Effect would ask the raising check
                # again before its ``exitDie`` op, and spin forever.
                died = self._raised(exc)
                cur = died.outcome if isinstance(died, _FromExit) else died
        # Effect pauses with ``flatMap(yieldNow, () => cur)``: the resumed
        # run counts that continuation as its first op and ``cur`` as its
        # second. An exit ``cur`` is a frame's ``succeed_with`` at the
        # inline limit, which Effect hands back to the loop as an op, or a
        # claimed success, Effect's exit op.
        resumed = 1
        decided = isinstance(cur, Effect) and cur._holds_decided
        if type(cur) is HandedOn or type(cur) is Decided:
            # A claimed success is an op too, which the resumed run counts.
            decided = type(cur) is Decided
            cur = Success(cur.value)
            resumed += 1
        self._queue_yielded(_Yielded(cur, ops=resumed, decided=decided), 0)
        return True

    def _queue_yielded(self, yielded: _Yielded, priority: int) -> None:
        self._yielded = yielded
        run = self._batch_run
        if (
            run is not None
            and priority == 0
            and self._batch_first is None
            and self._batch_others is None
        ):
            # ``_queue``'s commonest case, inline: a yield starting a batch.
            # The batch holds the yield itself, which ``_run_batch`` resumes
            # with no task made for it.
            self._batch_first = yielded
            run.schedule(self._run_batch)
        else:
            self._queue(self._go_on(yielded), priority)

    def _go_on(self, yielded: _Yielded) -> Task:
        """The task resuming the fiber after ``yielded``: nothing if an
        interrupt took it over meanwhile."""

        def go_on() -> None:
            self._resume_yielded(yielded)

        return go_on

    def _resume_yielded(self, yielded: _Yielded) -> None:
        if self._yielded is yielded:
            self._yielded = None
            self._ops_on_resume = yielded.ops
            self._decided_on_resume = yielded.decided
            self._drive(yielded.step)

    def _continue(self, frame: Frame, ex: Exit[Any, Any]) -> Step:
        hook = self._tracer_hook
        try:
            if isinstance(ex, Success):
                if hook is None:
                    return frame._on_success(ex.value, self)
            else:
                # A failure meets its next handler (or the end of the fiber,
                # in _loop) annotated with the frame it failed in, as
                # Effect's failure exits are.
                if self._stack_frame is not None:
                    ex = self._in_frame(ex, self._stack_frame)
                if hook is None:
                    return frame._on_failure(ex.cause, self)
            step: Callable[[], Step] = partial(_hand_over, frame, ex, self)
            return hook(step, self)
        except BaseException as exc:
            return self._raised(exc)

    def _raised(self, exc: BaseException) -> Step:
        """What the fiber goes on with when user code (a step or a
        continuation) raised ``exc``: a defect, as Effect makes anything
        thrown, whatever the exception's class.

        Ctrl-C is not the program's own error: the step it cut short ends
        as interrupted (the fiber goes on with that on its next turn), and
        the ``KeyboardInterrupt`` goes on to the runner, which interrupts
        the main fiber and waits for its finalizers, as when Ctrl-C lands
        while every fiber is parked.

        Effect's loop catches the raise and goes on with ``exitDie``, an op
        of its own."""
        if isinstance(exc, KeyboardInterrupt):
            interrupted = Failure(self._record_interrupt(None, None))
            unwind = _Yielded(interrupted, ops=1, decided=False)  # pragma: no mutate, unwinds only
            self._queue_yielded(unwind, 0)
            raise exc
        return _FromExit(exit_die(exc))

    @staticmethod
    def _in_frame(failure: Failure[Any], frame: StackFrame) -> Failure[Any]:
        """Effect's failure annotation: reasons without a ``StackTrace`` get
        the frame the fiber fails in."""
        annotated = failure.cause.annotate(Context.make(StackTrace, frame))
        return failure if annotated is failure.cause else Failure(annotated)

    @staticmethod
    def _with_interrupt(cur: Step, cause: Cause[Never]) -> Step:
        """``cur`` once the fiber is interrupted: a failure, or an op that is
        one (Effect's failure exits add the interrupts as they run), gains
        the interrupt; anything else becomes it, an op of its own, as
        Effect's ``failCause`` in place of the next op or continuation."""
        if isinstance(cur, Failure):
            return Failure(cur.cause.add_interrupts(cause))
        known = known_exit(cur) if isinstance(cur, Effect) else None
        if isinstance(known, Failure):
            return _failing(known.cause.add_interrupts(cause))
        return _failing(cause)

    def _finish(self, ex: Exit[Any, Any]) -> Step | None:
        """The stack is empty. Interrupt children first; then complete."""
        if type(ex) is HandedOn or type(ex) is Decided:
            ex = Success(ex.value)
        elif self._stack_frame is not None and isinstance(ex, Failure):
            ex = self._in_frame(ex, self._stack_frame)
        if self._children:
            children = list(self._children)
            self._interruptible = False  # pragma: no mutate, falsy either way
            self._push(_ReturnExit(ex))
            return interrupt_all(children, self.id, self._interruptor_annotations())
        self._exit = ex
        if self._runtime_metrics is not None:
            self._runtime_metrics.record_fiber_end(self._ctx, ex)
        view = _last_view[0]
        if view is not None and view.context is self._ctx:
            parent = self._parent
            if parent is None or parent._ctx is not self._ctx:
                # Keep the context of a fiber that is done alive no longer
                # than a fiber that still uses it (a closed scope's exit,
                # say), as Effect, whose cache is per fiber.
                _last_view[0] = None
        if self._parent is not None:
            self._parent._children.pop(self, None)
        observers, self._observers = self._observers, []
        # Each taken out before it is called: an observer added from another
        # thread as the fiber finishes is called by whichever side takes it
        # (see ``add_observer_unsafe``), and a waiter of another run may take
        # its own out meanwhile.
        while observers:
            try:
                observer = observers.pop(0)
            except IndexError:
                break
            # As Effect: a raise stops the observers after it.
            observer(ex)
        return None

    def _remove_observer(self, observer: Callable[[Exit[Any, Any]], None]) -> None:
        if self._exit is None:
            with contextlib.suppress(ValueError):
                self._observers.remove(observer)

    def _fork(
        self,
        effect: Effect[Any, Any, Any],
        *,
        daemon: bool,
        start_immediately: bool,
        uninterruptible: Uninterruptible = False,
    ) -> Fiber[Any, Any]:
        """A fiber running ``effect``, a child of this one unless ``daemon``.
        With ``start_immediately`` it runs now, up to its first wait or
        yield, before this fiber goes on (Effect's ``runForkWith``, and
        ``fork*`` with ``startImmediately``); otherwise it is scheduled.
        Required, so each port states which of the two Effect does."""
        interruptible = self._interruptible if uninterruptible == "inherit" else not uninterruptible
        child: Fiber[Any, Any] = Fiber(
            self._run_scheduler, self._ctx, None if daemon else self, interruptible=interruptible
        )
        if not daemon:
            self._children[child] = None
        if start_immediately:
            child._drive_first(effect)
        else:
            child._start(effect, parent=self)
        return child

    def _after_started(self, then: Step) -> Step:
        """Go on with ``then`` once the fibers this run started immediately
        have run (up to their first wait or yield)."""
        drain = _thread.drain
        if drain is None or not drain.first:
            return then
        drain.push_first((self, then))
        return SUSPEND

    def _yield_now(self, priority: int = 0) -> Step:  # pragma: no mutate, callers pass priority
        # Effect resumes with ``exitVoid``, the resumed run's first op.
        self._queue_yielded(_Yielded(_VOID, ops=0, decided=False), priority)
        return SUSPEND

    def _suspend(self, register: Register[Any, Any, Any]) -> Step:
        wait = _Wait(self)
        try:
            canceler = register(wait.resume)
        except BaseException:
            wait.claim()
            raise
        sync_result = wait.end_registration()
        if sync_result is not None:
            # Resumed while registering: ``register`` may have claimed state
            # (an offer admitted as it parked), so its result is this step's
            # outcome, never an effect for a later step a pause could drop.
            return run_known(sync_result)
        wait.canceler = canceler
        self._waiting = wait
        if self._interrupted_and_interruptible():
            return self._cancel_wait(wait)
        return SUSPEND

    def _resume(
        self, wait: _Wait, effect: Effect[Any, Any, Any], canceler: Effect[Any, Any, Any] | None
    ) -> None:
        """Run a claimed resume now. In Effect a resume runs the fiber at
        once, so an interrupt that arrived while another thread's resume
        was queued lands only once the resumed run has finished, parked or
        yielded."""
        if self._waiting is wait:
            self._waiting = None
            if canceler is not None:
                # Effect keeps the canceler's frame under every wait: an
                # interrupt the wait resumes with runs it too.
                self._push(_AsyncFinalizer(canceler))
            self._evaluate(effect)
        deferred, self._interrupts_after_resume = self._interrupts_after_resume, []
        for by, interruptor in deferred:
            self._deliver_interrupt(by, interruptor)

    def _deliver_interrupt(self, by: int | None, annotations: Context | None) -> None:
        if self._exit is not None:
            return
        wait = self._waiting
        if wait is not None and self._interruptible and self._phase != "running":
            if not wait.claim():
                self._interrupts_after_resume.append((by, annotations))
                return
            self._record_interrupt(by, annotations)
            step = self._abandon_wait(wait)
            self._evaluate(step)
            return
        if wait is not None and wait.done:
            self._interrupts_after_resume.append((by, annotations))
            return
        interrupt = self._record_interrupt(by, annotations)
        if not self._interruptible:
            return  # met when the fiber becomes interruptible again
        yielded = self._yielded
        if self._phase == "running":
            self._interrupt_fresh = True  # the loop raises it at its next step
        elif yielded is not None:
            # Queued after a yield or a pause: unwind now (Effect's evaluate of
            # a yielded fiber with ``failCause``, which drops the op it paused
            # before); the queued task does nothing. A result the fiber had
            # claimed first reaches its continuations, as in Effect.
            self._yielded = None
            self._decided_on_resume = yielded.decided
            self._interrupt_fresh = True
            self._evaluate(yielded.step)
        elif self._phase == "pending":
            self._evaluate(Failure(interrupt))
        else:
            # Queued to run on this thread, nested deeper than runs may go:
            # it meets the interrupt at its first step.
            self._interrupt_fresh = True

    def _record_interrupt(self, by: int | None, annotations: Context | None) -> Cause[Never]:
        cause = interrupt_cause(by)
        if self._stack_frame is not None:
            cause = cause.annotate(Context.make(StackTrace, self._stack_frame))
        if annotations is not None:
            cause = cause.annotate(annotations)
        if self._interrupt is not None:
            cause = self._interrupt.add_interrupts(cause)
        self._interrupt = cause
        return cause

    def _evaluate(self, step: Step) -> None:
        """Run this fiber with ``step`` now, nested in whatever runs on this
        thread (Effect's ``evaluate``). Past ``_MAX_NESTED_RUNS`` nested
        runs of this run it runs right after the innermost one instead."""
        outer = _thread.drain
        if outer is None:
            self._drain((self, step), 0)
        elif outer.depth >= _MAX_NESTED_RUNS and outer.run_scheduler is self._run_scheduler:
            outer.push((self, step))
        else:
            self._drain((self, step), outer.depth + 1)

    def _drive(self, step: Step) -> None:
        """Run this fiber from a scheduled task: now, or, if the scheduler
        runs its tasks inside a fiber of the run, right after that fiber's
        run."""
        outer = _thread.drain
        if outer is not None and outer.run_scheduler is self._run_scheduler:
            outer.push((self, step))
        else:
            self._evaluate(step)

    def _drain(self, start: _Run, depth: int) -> None:
        outer = _thread.drain
        _thread.drain = drain = _Drain(self._run_scheduler, depth)
        fiber, nxt = start
        try:
            while True:
                drain.current = fiber
                fiber._run(nxt)
                drain.current = None
                first = drain.first
                if first:
                    drain.first = None
                    if drain.queue is None:
                        drain.queue = deque(first)
                    else:
                        drain.queue.extendleft(reversed(first))
                queue = drain.queue
                if not queue:
                    break  # pragma: no mutate, last statement in try
                fiber, nxt = queue.popleft()
        finally:
            _thread.drain = outer
            # Only left over if a run raised (Ctrl-C): queue the rest, so no
            # fiber is lost.
            for fiber, nxt in [*(drain.first or ()), *(drain.queue or ())]:
                fiber._scheduler.schedule(lambda f=fiber, n=nxt: f._drive(n))

    def _drive_first(self, step: Step) -> None:
        """Start this fiber now, nested in the running one (Effect's
        ``startImmediately``); past ``_MAX_NESTED_RUNS`` nested runs, right
        after the current run, before anything else queued."""
        drain = _thread.drain
        if (
            drain is not None
            and drain.run_scheduler is self._run_scheduler
            and drain.depth >= _MAX_NESTED_RUNS
        ):
            drain.push_first((self, step))
        else:
            self._evaluate(step)

    def _cancel_wait(self, wait: _Wait) -> Step:
        """An interrupted fiber just parked: abandon the wait, unless another
        thread resumed it meanwhile (that run then meets the interrupt at
        its first step)."""
        if not wait.claim():
            return SUSPEND
        return self._abandon_wait(wait)

    def _abandon_wait(self, wait: _Wait) -> Step:
        """Give up a claimed wait because of an interrupt. Returns the step
        to continue with (the canceler, then the interrupt)."""
        self._waiting = None
        assert self._interrupt is not None
        # As Effect's ``evaluate(failCause(interrupted))``: the interrupt is
        # an op, which meets the canceler's frame.
        if wait.canceler is not None:
            self._push(_AsyncFinalizer(wait.canceler))
        return _failing(self._interrupt)


class _AsyncFinalizer(Frame):
    """Effect's ``asyncFinalizer``, under a wait with a canceler: when the
    wait ends with a cause holding interrupts (the fiber's, or one the wait
    resumed with), the canceler, run uninterruptibly, then that cause; a
    failing canceler is a failing finalizer. Any other failure goes back
    through the loop, an op of its own, as in Effect."""

    __slots__ = ("canceler",)

    def __init__(self, canceler: Effect[Any, Any, Any]) -> None:
        self.canceler = canceler

    def _on_failure(self, cause: Cause[Any], fiber: Fiber[Any, Any]) -> Step:
        if fiber._interruptible:
            fiber._push(_RestoreInterruptible(True))
            fiber._interruptible = False
        if not cause.has_interrupts:
            return _failing(cause)
        return _run_finalizer(self.canceler, Failure(cause))


def _no_op() -> None:
    pass


def _failing(cause: Cause[Never]) -> Effect[Never]:
    return _FromExit(Failure(cause))


def _run_hooked(hook: ContextHook, cur: Effect[Any, Any, Any], fiber: Fiber[Any, Any]) -> Step:
    # An exit runs no user code, so it needs no context. Hooking it would
    # make a raising hook turn the defect it raised into another one,
    # forever (Effect hooks its ``exitDie`` too, and spins).
    if isinstance(cur, _FromExit):
        known = known_exit(cur)
        if known is not None:
            return known
    step: Callable[[], Step] = partial(cur._step, fiber)
    return hook(step, fiber)


def _hand_over(frame: Frame, ex: Exit[Any, Any], fiber: Fiber[Any, Any]) -> Step:
    if isinstance(ex, Success):
        return frame._on_success(ex.value, fiber)
    return frame._on_failure(ex.cause, fiber)


class _RunScheduler(Tag[Scheduler]):
    """The scheduler of the run a context was made in."""


@dataclass(frozen=True, slots=True)
class _RunView:
    """What a fiber of the run on ``run_scheduler`` reads from ``given``.
    Contexts are immutable, so the last one computed is kept for the next
    fiber switching to the same context (every fork does)."""

    given: Context
    run_scheduler: Scheduler
    context: Context
    scheduler: Scheduler
    ops_budget: float
    should_yield: EffectScheduler | None
    tracer_hook: ContextHook | None
    runtime_metrics: FiberRuntimeMetricsService | None
    stack_frame: StackFrame | None
    # The run whose fibers keep their own batches (``Fiber._queue``): only
    # the run's own scheduler, not a provided one nor ``run_sync``'s.
    batch_run: RunScheduler | None

    @staticmethod
    def of(given: Context, run_scheduler: Scheduler) -> _RunView:
        context = given
        if context.lookup(_RunScheduler)[1] is not run_scheduler:
            context = _into_run(context, run_scheduler)
        scheduler = context.lookup(CurrentScheduler)[1]
        if isinstance(scheduler, BoundScheduler) and scheduler.run is not run_scheduler:
            scheduler = scheduler.effect_scheduler
        if isinstance(scheduler, EffectScheduler):
            scheduler = BoundScheduler(scheduler, run_scheduler)
            context = context.add(CurrentScheduler, scheduler)
        should_yield = scheduler.effect_scheduler if isinstance(scheduler, BoundScheduler) else None
        if context.lookup(PreventSchedulerYield)[1]:
            budget = math.inf
            should_yield = None
        elif should_yield is not None:
            budget = 0  # pragma: no mutate, ops >= 1 at every check
        else:
            # Under 3 Effect's fiber yields before every op it resumes
            # with, forever; here it gets 3's one op per run.
            budget = max(3, context.lookup(MaxOpsBeforeYield)[1])
        hook = context.lookup(CurrentTracer)[1].context
        runtime_metrics = context.lookup(FiberRuntimeMetrics)[1]
        frame = context.lookup(CurrentStackFrame)[1]
        batch_run = (
            run_scheduler
            if scheduler is run_scheduler
            and isinstance(run_scheduler, (SyncScheduler, AsyncioScheduler))
            and not isinstance(run_scheduler, SyncOnlyScheduler)
            else None
        )
        return _RunView(
            given,
            run_scheduler,
            context,
            scheduler,
            budget,
            should_yield,
            hook,
            runtime_metrics,
            frame,
            batch_run,
        )


# One entry: the view the last fiber switch computed.
_last_view: list[_RunView | None] = [None]


def _into_run(context: Context, run_scheduler: Scheduler) -> Context:
    """``context`` for a fiber of the run on ``run_scheduler``. A context
    from another run (kept by a finalizer, say) keeps a scheduler it was
    explicitly given, but not that run's own, which may no longer run."""
    found, earlier = context.lookup(_RunScheduler)
    in_run = context.add(_RunScheduler, run_scheduler)
    if CurrentScheduler in context.tags():
        given = context.lookup(CurrentScheduler)[1]
        if not found or given is not earlier:
            return in_run
    return in_run.add(CurrentScheduler, run_scheduler)


def _runs_here(run: Scheduler) -> bool:
    """Whether this thread runs ``run`` now: one of its fibers is running
    here, or it is running its tasks here."""
    return current_run_scheduler() is run or (isinstance(run, Tracking) and run.runs_here())


class FiberDispatcher:
    """A fiber's batch as a ``Scheduler``, for code outside the fiber's own
    steps (wakes, a queue made in it), as the dispatcher Effect's default
    ``MixedScheduler`` makes for each fiber: its tasks run together in one
    task of the run, queued when the first of them arrives, so a task that
    comes while that one is pending joins it, ahead of whatever other fibers
    queued since. The test clock counts each task as it is queued. A task
    from another thread goes through the run first, so only the run's thread
    touches the batch."""

    __slots__ = ("fiber", "run")

    def __init__(self, fiber: Fiber[Any, Any]) -> None:
        self.fiber = fiber
        self.run = fiber._run_scheduler

    def schedule(self, task: Task, priority: int = 0) -> None:
        if not _runs_here(self.run):
            self.run.schedule(lambda: self.schedule(task, priority))
            return
        self.fiber._queue(task, priority)

    def runs_here(self) -> bool:
        return _runs_here(self.run)

    def call_later(self, delay: Duration, task: Task, *, daemon: bool = False) -> Cancel:
        return self.run.call_later(delay, task, daemon=daemon)

    def track(self, tracker: WakeTracker, f: Callable[[], None]) -> None:
        self.run.track(tracker, f)

    def outside_work(self) -> WakeTracker:
        return self.run.outside_work()


def root_fiber(scheduler: Scheduler, context: Context) -> Fiber[Any, Any]:
    """A fiber with no parent, running on ``scheduler`` unless an effect
    provides another ``CurrentScheduler``."""
    return Fiber(scheduler, context, None)


def interrupt_all(
    fibers: list[Fiber[Any, Any]], by: int | None, annotations: Context | None
) -> Effect[None, Never, Never]:
    """Interrupt every fiber and wait for all of them to finish."""

    def register(resume: Callable[[Effect[Any, Any, Any]], None]) -> None:
        remaining = len(fibers)
        if remaining == 0:
            resume(_Succeed(None))
            return

        def observer(_: Exit[Any, Any]) -> None:
            nonlocal remaining
            remaining -= 1
            if remaining == 0:
                resume(_Succeed(None))

        for f in fibers:
            f.interrupt_as_unsafe(by, annotations)
        for f in fibers:
            f.add_observer_unsafe(observer)

    return _Callback(register)
