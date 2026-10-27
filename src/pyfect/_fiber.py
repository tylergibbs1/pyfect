"""The fiber runtime.

A fiber runs one effect. It keeps an explicit stack of continuation frames
(so deep chains never hit Python's recursion limit) and runs on a
``Scheduler``. It never blocks: when it has to wait, it registers a resume
callback and parks (``SUSPEND``); the callback reschedules it.

Interruption follows Effect's rules:

- Interrupting a fiber records an ``Interrupt`` at once when the caller is
  on the fiber's scheduler thread (otherwise via the scheduler). If the
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
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import itertools
import threading
from collections import deque
from collections.abc import Callable
from typing import Any, Generic, Literal, Never, TypeVar

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
from pyfect.cause import Cause, Die
from pyfect.cause import interrupt as interrupt_cause
from pyfect.context import Context
from pyfect.exit import Exit, Failure, Success
from pyfect.exit import die as exit_die
from pyfect.scheduler import Scheduler

A_co = TypeVar("A_co", covariant=True)
E_co = TypeVar("E_co", covariant=True, default=Never)

# How many steps a fiber takes before giving other fibers a turn.
MAX_OPS_BEFORE_YIELD = 2048

_fiber_ids = itertools.count(1)
_resume_lock = threading.Lock()


class _ThreadState(threading.local):
    """The scheduler whose fiber is running on this thread, if any, and the
    interrupted fibers waiting to unwind (while one is already unwinding)."""

    scheduler: Scheduler | None = None
    unwinds: deque[tuple[Fiber[Any, Any], Step]] | None = None


_thread = _ThreadState()

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
        "_children",
        "_context",
        "_exit",
        "_interrupt",
        "_interruptible",
        "_interrupts_after_resume",
        "_observers",
        "_parent",
        "_phase",
        "_scheduler",
        "_stack",
        "_waiting",
        "id",
    )

    def __init__(
        self, scheduler: Scheduler, context: Context, parent: Fiber[Any, Any] | None
    ) -> None:
        self.id = next(_fiber_ids)
        self._scheduler = scheduler
        self._context = context
        self._parent = parent
        self._stack: list[Frame] = []
        self._interruptible = True
        self._interrupt: Cause[Never] | None = None
        # Interrupts that arrived while a resume was queued (see _resume).
        self._interrupts_after_resume: list[int | None] = []
        self._children: set[Fiber[Any, Any]] = set()
        self._observers: list[Callable[[Exit[Any, Any]], None]] = []
        self._exit: Exit[Any, Any] | None = None
        self._waiting: _Wait | None = None
        self._phase: _Phase = "pending"

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

        def body(me: Fiber[Any, Any]) -> Effect[None, Never, Never]:
            self.unsafe_interrupt_as(me.id)
            return self.await_exit().as_void()

        return _WithFiber(body)

    def unsafe_poll(self) -> Exit[A_co, E_co] | None:
        """The exit if the fiber is done. Only meaningful on the fiber's
        scheduler thread."""
        return self._exit

    def unsafe_interrupt_as(self, by: int | None) -> None:
        """Ask the fiber to stop. Safe from any thread; does not wait.

        From a fiber on the same scheduler it takes effect at once (as
        Effect's ``interruptUnsafe``); elsewhere it goes through the
        scheduler."""
        if _thread.scheduler is self._scheduler:
            self._deliver_interrupt(by)
        else:
            self._scheduler.schedule(lambda: self._deliver_interrupt(by))

    def unsafe_add_observer(self, observer: Callable[[Exit[A_co, E_co]], None]) -> None:
        """Call ``observer`` with the exit once the fiber is done (at once if
        it already is). Must be called on the scheduler thread."""
        if self._exit is not None:
            observer(self._exit)
        else:
            self._observers.append(observer)

    # --- runtime internals --------------------------------------------------

    def _start(self, effect: Effect[Any, Any, Any]) -> None:
        self._scheduler.schedule(lambda: self._run(effect))

    def _push(self, frame: Frame) -> None:
        self._stack.append(frame)

    def _interrupted_and_interruptible(self) -> bool:
        return self._interrupt is not None and self._interruptible

    def _run(self, start: Step) -> None:
        if self._exit is not None:
            return  # finished early by an interrupt; a stale start or resume
        outer = _thread.scheduler
        _thread.scheduler = self._scheduler
        self._phase = "running"
        try:
            self._loop(start)
        finally:
            self._phase = "idle"
            _thread.scheduler = outer

    def _loop(self, start: Step) -> None:
        cur: Step = start
        ops = 0
        while True:
            if self._interrupt is not None and self._interruptible:
                cur = self._with_interrupt(cur, self._interrupt)

            if isinstance(cur, Effect):
                ops += 1
                if ops > MAX_OPS_BEFORE_YIELD:
                    self._scheduler.schedule(lambda paused=cur: self._run(paused))
                    return
                try:
                    cur = cur._step(self)
                except Exception as exc:
                    cur = Failure(Cause((Die(exc),)))
            elif isinstance(cur, Success | Failure):
                if not self._stack:
                    nxt = self._finish(cur)
                    if nxt is None:
                        return
                    cur = nxt
                    continue
                cur = self._continue(self._stack.pop(), cur)
            elif cur is SUSPEND:
                return  # a resume callback will call _run again
            else:  # untyped user code handed back something that is not an effect
                cur = exit_die(TypeError(f"not a valid effect: {cur!r}"))

    def _continue(self, frame: Frame, ex: Exit[Any, Any]) -> Step:
        try:
            if isinstance(ex, Success):
                return frame._on_success(ex.value, self)
            return frame._on_failure(ex.cause, self)
        except Exception as exc:
            return exit_die(exc)

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
            return interrupt_all(children, self.id)
        self._exit = ex
        if self._parent is not None:
            self._parent._children.discard(self)
        observers, self._observers = self._observers, []
        for observer in observers:
            observer(ex)
        return None

    def _remove_observer(self, observer: Callable[[Exit[Any, Any]], None]) -> None:
        if observer in self._observers:
            self._observers.remove(observer)

    def _fork(self, effect: Effect[Any, Any, Any], *, daemon: bool) -> Fiber[Any, Any]:
        child: Fiber[Any, Any] = Fiber(self._scheduler, self._context, None if daemon else self)
        if not daemon:
            self._children.add(child)
        child._start(effect)
        return child

    def _yield_now(self) -> Step:
        self._scheduler.schedule(lambda: self._run(Success(None)))
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
            self._run(effect)
        deferred, self._interrupts_after_resume = self._interrupts_after_resume, []
        for by in deferred:
            self._deliver_interrupt(by)

    def _deliver_interrupt(self, by: int | None) -> None:
        if self._exit is not None:
            return
        wait = self._waiting
        if wait is not None and self._interruptible and self._phase != "running":
            if not wait.claim():
                self._interrupts_after_resume.append(by)
                return
            self._record_interrupt(by)
            step = self._abandon_wait(wait)
            self._unwind(step)
            return
        if wait is not None and wait.done:
            self._interrupts_after_resume.append(by)
            return
        interrupt = self._record_interrupt(by)
        if self._interruptible and self._phase == "pending":
            self._unwind(Failure(interrupt))
        # Otherwise the loop raises it at its next interruptible step: the
        # fiber is running, uninterruptible, or queued to run.

    def _record_interrupt(self, by: int | None) -> Cause[Never]:
        cause = interrupt_cause(by)
        if self._interrupt is not None:
            cause = self._interrupt.add_interrupts(cause)
        self._interrupt = cause
        return cause

    def _unwind(self, step: Step) -> None:
        """Run an interrupted fiber now. A cascade (each fiber interrupting
        its children as it finishes) runs one fiber after another rather
        than nested, so a deep tree of fibers cannot overflow the stack."""
        queued = _thread.unwinds
        if queued is not None:
            queued.append((self, step))
            return
        queued = _thread.unwinds = deque[tuple[Fiber[Any, Any], Step]]([(self, step)])
        try:
            while queued:
                fiber, nxt = queued.popleft()
                fiber._run(nxt)
        finally:
            _thread.unwinds = None
            for fiber, nxt in queued:  # only left over if a run raised
                fiber._scheduler.schedule(lambda f=fiber, n=nxt: f._run(n))

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


def interrupt_all(fibers: list[Fiber[Any, Any]], by: int | None) -> Effect[None, Never, Never]:
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
            f.unsafe_interrupt_as(by)
        for f in fibers:
            f.unsafe_add_observer(observer)

    return _Callback(register)
