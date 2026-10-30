"""The fiber runtime.

A fiber runs one effect. It keeps an explicit stack of continuation frames
(so deep chains never hit Python's recursion limit) and runs on a
``Scheduler``. It never blocks: when it has to wait, it registers a resume
callback and parks (``SUSPEND``); the callback reschedules it.

Interruption follows Effect's rules:

- Interrupting a fiber records an ``Interrupt`` at once when the caller is
  a fiber of the same run (otherwise via the scheduler). If the
  fiber is interruptible and not running, it is unwound right away: a fiber
  that has not started never runs its body, and a parked fiber has its wait
  cancelled (running its canceler). A running fiber, including one that
  interrupts itself, stops at its next step. A fiber whose resume is
  already queued gets the interrupt after that resumed run, since in
  Effect the resume would already have run.
- While interruptible and interrupted, the loop turns whatever comes next
  into a failure, so the stack unwinds. Recovery handlers are skipped;
  finalizers run, because they run in uninterruptible regions.
- Inside an uninterruptible region the interrupt waits until the region
  ends.

Supervision: a fiber's children (from ``fork``) are interrupted and awaited
before the fiber completes.

Fibers run one after another (``_drive``), not nested inside one another;
only an interrupt sent from the same thread unwinds its target inside the
sender's run (``_unwind``), and a cascade from there is queued again. A
child started immediately runs right after the forking fiber's current
step, before anything else queued, and the forking fiber goes on after it.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

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
    _Succeed,
    _Sync,
    _WithFiber,
)
from pyfect._metric_ref import FiberRuntimeMetrics
from pyfect._stack_frame import CurrentStackFrame, InterruptorStackTrace, StackFrame, StackTrace
from pyfect._tracer_ref import CurrentTracer
from pyfect.cause import Cause, Die
from pyfect.cause import interrupt as interrupt_cause
from pyfect.context import Context, Reference, Tag
from pyfect.exit import Exit, Failure, Success
from pyfect.exit import die as exit_die
from pyfect.scheduler import (
    CurrentScheduler,
    MaxOpsBeforeYield,
    PreventSchedulerYield,
    Scheduler,
)

if TYPE_CHECKING:
    from pyfect._metric_ref import FiberRuntimeMetricsService
    from pyfect.scope import CloseableScope
    from pyfect.tracer import ContextHook

A_co = TypeVar("A_co", covariant=True)
E_co = TypeVar("E_co", covariant=True, default=Never)

# Effect's ``maxInlineSteps``: how many continuations run back to back
# before the loop may yield.
_INLINE_STEPS = 32

_fiber_ids = itertools.count(1)
_resume_lock = threading.Lock()


type _Run = tuple[Fiber[Any, Any], Step]


class _Drain:
    """The fiber runs of one run scheduler on this thread, one after
    another: ``queue`` is what runs next, and ``first`` collects the runs
    the current run hands over (children started immediately, then the
    rest of the forking fiber), which go before everything queued. An
    ``unwinding`` drain runs interrupted fibers inside the run that
    interrupted them."""

    __slots__ = ("current", "first", "queue", "run_scheduler", "unwinding")

    def __init__(self, run_scheduler: Scheduler, *, unwinding: bool) -> None:
        self.run_scheduler = run_scheduler
        self.unwinding = unwinding
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
    number of times; only the first call counts."""

    __slots__ = ("canceler", "done", "fiber", "registering", "sync_result")

    def __init__(self, fiber: Fiber[Any, Any]) -> None:
        self.fiber = fiber
        self.done = False
        self.registering = True
        self.sync_result: Effect[Any, Any, Any] | None = None
        self.canceler: Effect[Any, Any, Any] | None = None

    def claim(self) -> bool:
        with _resume_lock:
            if self.done:
                return False
            self.done = True
            return True

    def resume(self, effect: Effect[Any, Any, Any]) -> None:
        if not self.claim():
            return
        if self.registering:
            self.sync_result = effect
            return
        fiber = self.fiber
        fiber._scheduler.schedule(lambda: fiber._resume(self, effect))


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
        "_children",
        "_ctx",
        "_exit",
        "_interrupt",
        "_interruptible",
        "_interrupts_after_resume",
        "_observers",
        "_ops_budget",
        "_parent",
        "_phase",
        "_run_scheduler",
        "_runtime_metrics",
        "_scheduler",
        "_stack",
        "_stack_frame",
        "_tracer_hook",
        "_waiting",
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
        self._phase: _Phase = "pending"
        self._set_context(context)
        if self._runtime_metrics is not None:
            self._runtime_metrics.record_fiber_start(self._ctx)

    def __repr__(self) -> str:
        return f"Fiber(#{self.id})"

    # --- public API (all effects, except the ``unsafe_`` reads) ------------

    def await_exit(self) -> Effect[Exit[A_co, E_co], Never, Never]:
        """Wait for the fiber and succeed with its ``Exit``."""

        def register(resume: Callable[[Effect[Any, Any, Any]], None]) -> Effect[None] | None:
            if self._exit is not None:
                resume(_Succeed(self._exit))
                return None

            def observer(ex: Exit[Any, Any]) -> None:
                resume(_Succeed(ex))

            self._observers.append(observer)
            return _Sync(lambda: self._remove_observer(observer))

        return _Callback(register)

    def join(self) -> Effect[A_co, E_co, Never]:
        """Wait for the fiber and take on its result: its value, or its
        failure."""
        return self.await_exit().flat_map(_FromExit)

    def interrupt(self) -> Effect[None, Never, Never]:
        """Interrupt the fiber and wait until it has finished cleaning up.
        Read the outcome with ``await_exit``."""
        return _WithFiber(lambda me: self._interrupt_from(me, me.id))

    def interrupt_as(self, by: int | None) -> Effect[None, Never, Never]:
        """``interrupt``, attributed to the fiber with id ``by``."""
        return _WithFiber(lambda me: self._interrupt_from(me, by))

    def _interrupt_from(self, me: Fiber[Any, Any], by: int | None) -> Effect[None, Never, Never]:
        self.interrupt_as_unsafe(by, me._interruptor_annotations())
        return self.await_exit().as_void()

    def run_in(self, scope: CloseableScope) -> Fiber[A_co, E_co]:
        """Tie the fiber to ``scope``: closing it interrupts the fiber, and
        the fiber leaves the scope when it exits. Registering again moves
        the fiber's finalizer to the end, so it runs first. A fiber in an
        already closed scope is interrupted. Call on the scheduler thread."""
        if self._exit is not None:
            return self
        if scope._closed is not None:
            self.interrupt_as_unsafe(self.id)
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

        From a fiber on the same scheduler it takes effect at once (as
        Effect's ``interruptUnsafe``); elsewhere it goes through the
        scheduler. The interruption carries ``annotations`` (the
        interrupting fiber's ``InterruptorStackTrace``) and the frame this
        fiber is in (``StackTrace``)."""
        if current_run_scheduler() is self._run_scheduler:
            self._deliver_interrupt(by, annotations)
        else:
            self._scheduler.schedule(lambda: self._deliver_interrupt(by, annotations))

    def add_observer_unsafe(
        self, observer: Callable[[Exit[A_co, E_co]], None]
    ) -> Callable[[], None]:
        """Call ``observer`` with the exit once the fiber is done (at once if
        it already is). Returns a function that removes the observer. Must
        be called on the scheduler thread."""
        if self._exit is not None:
            observer(self._exit)
            return _no_op
        self._observers.append(observer)
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
            or view.given is not context
            or view.run_scheduler is not self._run_scheduler
        ):
            view = _last_view[0] = _RunView.of(context, self._run_scheduler)
        self._ctx = view.context
        self._scheduler: Scheduler = view.scheduler
        self._ops_budget: float = view.ops_budget
        self._tracer_hook: ContextHook | None = view.tracer_hook
        self._runtime_metrics: FiberRuntimeMetricsService | None = view.runtime_metrics
        self._stack_frame: StackFrame | None = view.stack_frame

    def _interruptor_annotations(self) -> Context | None:
        """What an interruption this fiber sends records about it."""
        frame = self._stack_frame
        return None if frame is None else Context.make(InterruptorStackTrace, frame)

    def _start(self, effect: Effect[Any, Any, Any]) -> None:
        self._scheduler.schedule(lambda: self._drive(effect))

    def _push(self, frame: Frame) -> None:
        self._stack.append(frame)

    def _interrupted_and_interruptible(self) -> bool:
        return self._interrupt is not None and self._interruptible

    def _run(self, start: Step) -> None:
        if self._exit is not None:
            return  # finished early by an interrupt; a stale start or resume
        self._phase = "running"
        try:
            self._loop(start)
        finally:
            self._phase = "idle"

    def _loop(self, start: Step) -> None:
        cur: Step = start
        ops = 0
        while True:
            if self._interrupt is not None and self._interruptible:
                cur = self._with_interrupt(cur, self._interrupt)

            if isinstance(cur, Effect):
                ops += 1
                if ops > self._ops_budget:
                    self._pause(cur)
                    return
                try:
                    hook = self._tracer_hook
                    cur = cur._step(self) if hook is None else _run_hooked(hook, cur, self)
                except Exception as exc:
                    cur = Failure(Cause((Die(exc),)))
            elif isinstance(cur, Success | Failure):
                if not self._stack:
                    if self._stack_frame is not None and isinstance(cur, Failure):
                        cur = self._in_frame(cur, self._stack_frame)
                    nxt = self._finish(cur)
                    if nxt is None:
                        return
                    cur = nxt
                    continue
                # A continuation counts as a step, but as in Effect a fiber
                # may yield before one only every ``_INLINE_STEPS`` steps: a
                # long chain of ``map``s still yields, while a primitive's
                # result normally reaches its continuation in the same step.
                ops += 1
                if ops % _INLINE_STEPS == 0 and ops > self._ops_budget:
                    self._pause(cur)
                    return
                cur = self._continue(self._stack.pop(), cur)
            elif cur is SUSPEND:
                return  # a resume callback will call _run again
            else:  # untyped user code handed back something that is not an effect
                cur = exit_die(TypeError(f"not a valid effect: {cur!r}"))

    def _pause(self, cur: Step) -> None:
        """The step budget is spent: let other fibers run, then go on with
        ``cur``."""
        self._scheduler.schedule(lambda: self._drive(cur))

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
        except Exception as exc:
            return exit_die(exc)

    @staticmethod
    def _in_frame(failure: Failure[Any], frame: StackFrame) -> Failure[Any]:
        """Effect's failure annotation: reasons without a ``StackTrace`` get
        the frame the fiber fails in."""
        annotated = failure.cause.annotate(Context.make(StackTrace, frame))
        return failure if annotated is failure.cause else Failure(annotated)

    @staticmethod
    def _with_interrupt(cur: Step, cause: Cause[Never]) -> Step:
        if isinstance(cur, Failure):
            with_interrupts = cur.cause.add_interrupts(cause)
            return cur if with_interrupts is cur.cause else Failure(with_interrupts)
        return Failure(cause)

    def _finish(self, ex: Exit[Any, Any]) -> Step | None:
        """The stack is empty. Interrupt children first; then complete."""
        if self._children:
            children = list(self._children)
            self._interruptible = False
            self._push(_ReturnExit(ex))
            return interrupt_all(children, self.id, self._interruptor_annotations())
        self._exit = ex
        if self._runtime_metrics is not None:
            self._runtime_metrics.record_fiber_end(self._ctx, ex)
        if self._parent is not None:
            self._parent._children.pop(self, None)
        observers, self._observers = self._observers, []
        for observer in observers:
            observer(ex)
        return None

    def _remove_observer(self, observer: Callable[[Exit[Any, Any]], None]) -> None:
        if self._exit is None and observer in self._observers:
            self._observers.remove(observer)

    def _fork(
        self,
        effect: Effect[Any, Any, Any],
        *,
        daemon: bool,
        start_immediately: bool = False,
        uninterruptible: Uninterruptible = False,
    ) -> Fiber[Any, Any]:
        """A fiber running ``effect``, a child of this one unless ``daemon``.
        With ``start_immediately`` it runs now, up to its first wait or
        yield, before this fiber goes on; otherwise it is scheduled."""
        interruptible = self._interruptible if uninterruptible == "inherit" else not uninterruptible
        child: Fiber[Any, Any] = Fiber(
            self._run_scheduler, self._ctx, None if daemon else self, interruptible=interruptible
        )
        if not daemon:
            self._children[child] = None
        if start_immediately:
            child._drive_first(effect)
        else:
            child._start(effect)
        return child

    def _after_started(self, then: Step) -> Step:
        """Go on with ``then`` once the fibers this run started immediately
        have run (up to their first wait or yield)."""
        drain = _thread.drain
        if drain is None or not drain.first:
            return then
        drain.push_first((self, then))
        return SUSPEND

    def _yield_now(self) -> Step:
        self._scheduler.schedule(lambda: self._drive(Success(None)))
        return SUSPEND

    def _suspend(self, register: Register[Any, Any, Any]) -> Step:
        wait = _Wait(self)
        try:
            canceler = register(wait.resume)
        except BaseException:
            wait.claim()
            raise
        wait.registering = False
        if wait.sync_result is not None:
            return wait.sync_result
        wait.canceler = canceler
        self._waiting = wait
        if self._interrupted_and_interruptible():
            return self._cancel_wait(wait)
        return SUSPEND

    def _resume(self, wait: _Wait, effect: Effect[Any, Any, Any]) -> None:
        """Run a claimed resume. In Effect a resume runs the fiber at once,
        so an interrupt that arrived while this one was queued lands only
        once the resumed run has finished, parked or yielded."""
        if self._waiting is wait:
            self._waiting = None
            self._drive(effect)
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
            self._unwind(step)
            return
        if wait is not None and wait.done:
            self._interrupts_after_resume.append((by, annotations))
            return
        interrupt = self._record_interrupt(by, annotations)
        if self._interruptible and self._phase == "pending":
            self._unwind(Failure(interrupt))
        # Otherwise the loop raises it at its next interruptible step: the
        # fiber is running, uninterruptible, or queued to run.

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

    def _drive(self, step: Step) -> None:
        """Run this fiber with ``step`` now, or, while another fiber of the
        run is running on this thread, right after it. Fibers never run
        nested inside one another, so a chain of children started
        immediately cannot overflow the stack."""
        outer = _thread.drain
        if outer is not None and outer.run_scheduler is self._run_scheduler:
            outer.push((self, step))
        else:
            self._drain((self, step), unwinding=False)

    def _unwind(self, step: Step) -> None:
        """Run an interrupted fiber now, inside the run that interrupted
        it (Effect's synchronous ``interruptUnsafe``). A cascade (each
        fiber interrupting its children as it finishes) runs one fiber
        after another rather than nested, so a deep tree of fibers cannot
        overflow the stack."""
        outer = _thread.drain
        if outer is not None and outer.run_scheduler is self._run_scheduler and outer.unwinding:
            outer.push((self, step))
        else:
            self._drain((self, step), unwinding=True)

    def _drain(self, start: _Run, *, unwinding: bool) -> None:
        outer = _thread.drain
        _thread.drain = drain = _Drain(self._run_scheduler, unwinding=unwinding)
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
                    break
                fiber, nxt = queue.popleft()
        finally:
            _thread.drain = outer
            for fiber, nxt in drain.queue or ():  # only left over if a run raised
                fiber._scheduler.schedule(lambda f=fiber, n=nxt: f._drive(n))

    def _drive_first(self, step: Step) -> None:
        """Run this fiber before anything else queued: right after the
        current run, or now if no fiber of the run is running."""
        drain = _thread.drain
        if drain is not None and drain.run_scheduler is self._run_scheduler:
            drain.push_first((self, step))
        else:
            self._drive(step)

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
        if wait.canceler is None:
            return Failure(self._interrupt)
        # Run the canceler uninterruptibly; restoring interruptibility
        # afterwards makes the loop raise the interrupt.
        self._push(_RestoreInterruptible(True))
        self._interruptible = False
        return wait.canceler


def _no_op() -> None:
    pass


def _run_hooked(hook: ContextHook, cur: Effect[Any, Any, Any], fiber: Fiber[Any, Any]) -> Step:
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
    tracer_hook: ContextHook | None
    runtime_metrics: FiberRuntimeMetricsService | None
    stack_frame: StackFrame | None

    @staticmethod
    def of(given: Context, run_scheduler: Scheduler) -> _RunView:
        context = given
        if context.lookup(_RunScheduler)[1] is not run_scheduler:
            context = _into_run(context, run_scheduler)
        if context.lookup(PreventSchedulerYield)[1]:
            budget = math.inf
        else:
            budget = max(1, context.lookup(MaxOpsBeforeYield)[1])
        scheduler = context.lookup(CurrentScheduler)[1]
        hook = context.lookup(CurrentTracer)[1].context
        runtime_metrics = context.lookup(FiberRuntimeMetrics)[1]
        frame = context.lookup(CurrentStackFrame)[1]
        return _RunView(
            given, run_scheduler, context, scheduler, budget, hook, runtime_metrics, frame
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
