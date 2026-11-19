"""Running pure functions in subinterpreters (Python 3.14's
``concurrent.interpreters``), each with its own GIL.

Effect has nothing like it: JavaScript has no interpreters to spread work
over (a Web Worker is closer to a ``ProcessWorker``). On the GIL build,
Python code in ``fx.blocking`` takes turns with every other thread; in a
subinterpreter it runs on its own core, without the start-up and memory of a
process.

Provide the pool with ``layer(size)`` and call a function with ``call``::

    total = yield from interpreter_pool.call(checksum, data)

    program.pipe(fx.provide(interpreter_pool.layer(size=4)))

The function, its arguments and its result cross into another interpreter:
they must be picklable (the function by reference, so a module-level
function of an importable module, or one that reads no globals), and the
function sees none of the caller's state. Each subinterpreter starts with
the program's ``sys.path`` and imports the function's module, and what that
imports, the first time it runs something from it.

A raised exception comes back as a defect (``call``) or a failure
(``try_call``): the exception itself when it pickles, else the
``concurrent.interpreters.ExecutionFailed`` that summarises it. Python
cannot stop a call that has started, so interrupting the fiber abandons it,
as ``fx.blocking`` does: a call still queued is withdrawn, a running one
goes on until it returns. Releasing the layer waits for every interpreter
to close, an abandoned call's once that call returns, so no interpreter
outlives its pool.

``concurrent.interpreters`` is new in Python 3.14: on 3.13 building the
layer dies with ``InterpretersUnavailableError``.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import importlib
import os
import sys
import threading
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any, Never, Protocol, cast, overload

from pyfect import layer as layer_
from pyfect._core import Effect, _Succeed
from pyfect._os_wait import os_wait
from pyfect.context import Tag
from pyfect.effect import _failure_of, _unknown_error_in, die, sync
from pyfect.errors import UnknownError
from pyfect.exit import Exit
from pyfect.layer import Layer
from pyfect.scope import acquire_release

_VOID: Effect[None] = _Succeed(None)


class InterpretersUnavailableError(RuntimeError):
    """This Python has no ``concurrent.interpreters`` (it is new in 3.14)."""


class InterpreterPoolClosedError(RuntimeError):
    """A call reached a pool whose layer has been released."""


class InterpreterStartError(RuntimeError):
    """No worker could start a subinterpreter to run a call; the cause says
    why."""


class _Queue(Protocol):
    def get(self) -> object: ...


class _Interpreter(Protocol):
    def call(self, callable: Callable[..., object], /, *args: object) -> object: ...

    def close(self) -> None: ...


class _Interpreters(Protocol):
    ExecutionFailed: type[Exception]

    def create(self) -> _Interpreter: ...

    def create_queue(self) -> _Queue: ...


def _load() -> _Interpreters:
    try:
        module = importlib.import_module("concurrent.interpreters")
    except ModuleNotFoundError:
        raise InterpretersUnavailableError(
            "interpreter_pool needs concurrent.interpreters, new in Python 3.14"
        ) from None
    return cast("_Interpreters", module)


def _do_call(results: Any, fn: Any, args: Any) -> Any:
    # Runs in the subinterpreter, which receives it as a function without
    # globals (no import of this module there): only builtins and arguments.
    try:
        return fn(*args)
    except BaseException as exc:
        try:
            results.put(exc)
        except Exception:
            results.put(None)
        raise


def _set_path(path: list[str]) -> None:
    # Runs in the subinterpreter, as ``_do_call`` does: its ``sys.path`` starts
    # from the interpreter's configuration, without what the program added.
    import sys

    sys.path[:] = path


type _Work = tuple[Callable[..., object], tuple[object, ...], Future[object]]


class _Workers:
    """Daemon threads, each with an interpreter of its own, started as work
    arrives up to ``size``; idle ones wait for more until the pool closes."""

    def __init__(self, interpreters: _Interpreters, size: int) -> None:
        self._interpreters = interpreters
        self._size = size
        self._lock = threading.Condition()
        self._work: deque[_Work] = deque()
        self._idle = 0
        self._threads = 0
        self._closed = False
        self._on_quiet: list[Callable[[], None]] = []

    def submit(self, fn: Callable[..., object], args: tuple[object, ...]) -> Future[object]:
        future: Future[object] = Future()
        with self._lock:
            if self._closed:
                future.set_exception(InterpreterPoolClosedError("the interpreter pool is closed"))
                return future
            self._work.append((fn, args, future))
            start = len(self._work) > self._idle and self._threads < self._size
            if start:
                self._threads += 1
            else:
                self._lock.notify()
        if start:
            name = f"pyfect-interpreter-{id(future):x}"
            threading.Thread(target=self._worker, name=name, daemon=True).start()
        return future

    def withdraw(self, future: Future[object]) -> None:
        """Take ``future``'s call off the queue, if no worker has taken it."""
        with self._lock:
            for index, (_, _, queued) in enumerate(self._work):
                if queued is future:
                    del self._work[index]
                    break
        future.cancel()

    def close(self, on_quiet: Callable[[], None]) -> None:
        """Fail queued calls and let every worker close its interpreter once
        its current call returns, an abandoned one included; ``on_quiet`` runs
        once every worker has closed its interpreter."""
        with self._lock:
            self._closed = True
            work, self._work = self._work, deque()
            quiet = self._threads == 0
            if not quiet:
                self._on_quiet.append(on_quiet)
            self._lock.notify_all()
        for _, _, future in work:
            future.set_exception(InterpreterPoolClosedError("the interpreter pool closed"))
        if quiet:
            on_quiet()

    def _next(self) -> _Work | None:
        with self._lock:
            while not self._work and not self._closed:
                self._idle += 1
                self._lock.wait()
                self._idle -= 1
            if self._closed:
                return None
            return self._work.popleft()

    def _worker(self) -> None:
        interpreters = self._interpreters
        try:
            interpreter = interpreters.create()
        except BaseException as exc:
            self._exit(exc)
            return
        try:
            interpreter.call(_set_path, list(sys.path))
            results = interpreters.create_queue()
            while (item := self._next()) is not None:
                fn, args, future = item
                if future.set_running_or_notify_cancel():
                    _run(interpreters, interpreter, results, (fn, args, future))
        except BaseException as exc:
            interpreter.close()
            self._exit(exc)
            return
        interpreter.close()
        self._exit(None)

    def _exit(self, failed: BaseException | None) -> None:
        """A worker is done. One that could not start an interpreter fails
        the queued calls when no other worker is left to run them."""
        with self._lock:
            self._threads -= 1
            stranded: deque[_Work] = deque()
            if failed is not None and self._threads == 0:
                stranded, self._work = self._work, deque()
            quiet = self._threads == 0
            on_quiet, self._on_quiet = (self._on_quiet, []) if quiet else ([], self._on_quiet)
        if failed is not None:
            for _, _, future in stranded:
                if future.set_running_or_notify_cancel():
                    error = InterpreterStartError("could not start a subinterpreter")
                    error.__cause__ = failed
                    future.set_exception(error)
        for f in on_quiet:
            f()


def _run(
    interpreters: _Interpreters, interpreter: _Interpreter, results: _Queue, work: _Work
) -> None:
    fn, args, future = work
    try:
        value = interpreter.call(_do_call, results, fn, args)
    except interpreters.ExecutionFailed as failed:
        original = results.get()
        if isinstance(original, BaseException):
            original.__cause__ = failed
            future.set_exception(original)
        else:
            future.set_exception(failed)
    except BaseException as exc:  # the call could not cross (NotShareableError, pickling)
        future.set_exception(exc)
    else:
        future.set_result(value)


class InterpreterPoolService:
    """Runs functions on a pool of subinterpreters; see the module."""

    __slots__ = ("_workers",)

    def __init__(self, workers: _Workers) -> None:
        self._workers = workers

    def call[*Ts, A](self, fn: Callable[[*Ts], A], *args: *Ts) -> Effect[A]:
        """``fn(*args)`` in a subinterpreter; a raised exception is a
        defect."""
        return self._call(fn, args, None)

    @overload
    def try_call[*Ts, A](self, fn: Callable[[*Ts], A], *args: *Ts) -> Effect[A, UnknownError]: ...
    @overload
    def try_call[*Ts, A, E](
        self, fn: Callable[[*Ts], A], *args: *Ts, catch: Callable[[Exception], E]
    ) -> Effect[A, E]: ...
    def try_call(
        self,
        fn: Callable[..., Any],
        *args: object,
        catch: Callable[[Exception], Any] | None = None,
    ) -> Effect[Any, Any]:
        """``call``, mapping a raised exception to a typed error with
        ``catch``, or to an ``UnknownError``. If ``catch`` raises, that is a
        defect."""
        return self._call(fn, args, _unknown_error_in("try_call") if catch is None else catch)

    def _call[A, E](
        self,
        fn: Callable[..., A],
        args: tuple[object, ...],
        catch: Callable[[Exception], E] | None,
    ) -> Effect[A, E]:
        workers = self._workers

        def register(resume: Callable[[Effect[A, E]], None]) -> Callable[[], None]:
            def done(future: Future[object]) -> None:
                if future.cancelled():
                    return
                exc = future.exception()
                if exc is None:
                    resume(_Succeed(cast("A", future.result())))
                elif isinstance(exc, (InterpreterPoolClosedError, InterpreterStartError)):
                    resume(die(exc))
                else:
                    resume(_failure_of(catch, exc))

            future = workers.submit(fn, args)
            future.add_done_callback(done)
            return lambda: workers.withdraw(future)

        return os_wait(register, waits_for="work")


class InterpreterPool(Tag[InterpreterPoolService]):
    """A pool of subinterpreters to run pure functions on."""


def layer(size: int | None = None) -> Layer[InterpreterPool]:
    """A pool of up to ``size`` subinterpreters (one per CPU by default),
    each started on first need; releasing the layer closes them, waiting
    for abandoned calls to return. Dies with
    ``InterpretersUnavailableError`` before Python 3.14."""
    if size is not None and size < 1:
        raise ValueError(f"an interpreter pool needs at least one interpreter, got {size}")
    count = size or os.cpu_count() or 1

    def make() -> InterpreterPoolService:
        return InterpreterPoolService(_Workers(_load(), count))

    def release(pool: InterpreterPoolService, _: Exit[Any, Any]) -> Effect[None]:
        def register(resume: Callable[[Effect[None]], None]) -> None:
            pool._workers.close(lambda: resume(_VOID))

        return os_wait(register, waits_for="work")

    return layer_.effect(InterpreterPool, acquire_release(sync(make), release))


def call[*Ts, A](fn: Callable[[*Ts], A], *args: *Ts) -> Effect[A, Never, InterpreterPool]:
    """``fn(*args)`` on the provided pool; a raised exception is a defect."""
    return InterpreterPool().flat_map(lambda pool: pool.call(fn, *args))


@overload
def try_call[*Ts, A](
    fn: Callable[[*Ts], A], *args: *Ts
) -> Effect[A, UnknownError, InterpreterPool]: ...
@overload
def try_call[*Ts, A, E](
    fn: Callable[[*Ts], A], *args: *Ts, catch: Callable[[Exception], E]
) -> Effect[A, E, InterpreterPool]: ...
def try_call(
    fn: Callable[..., Any], *args: object, catch: Callable[[Exception], Any] | None = None
) -> Effect[Any, Any, InterpreterPool]:
    """``call`` on the provided pool, mapping a raised exception to a typed
    error with ``catch``, or to an ``UnknownError``."""
    if catch is None:
        return InterpreterPool().flat_map(lambda pool: pool.try_call(fn, *args))
    return InterpreterPool().flat_map(lambda pool: pool.try_call(fn, *args, catch=catch))


__all__ = [
    "InterpreterPool",
    "InterpreterPoolClosedError",
    "InterpreterPoolService",
    "InterpreterStartError",
    "InterpretersUnavailableError",
    "UnknownError",
    "call",
    "layer",
    "try_call",
]
