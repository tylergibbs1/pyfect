"""Effect's ``forEach``, op for op, so fibers interleave as they do there.

One at a time it is a ``whileLoop`` over the items (``forEachSequential``).
Concurrently it is ``iterateConcurrentImpl``: items whose effect is already
an exit are taken as they are; the first that is not parks the caller,
which then forks one child per item (started at once, as interruptible as
the caller), at most ``limit`` alive. The first failure interrupts the rest
and later failures add their causes.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Iterable
from functools import partial
from typing import Any, Never, cast

from pyfect._cause_election import late_sibling_cause
from pyfect._core import Effect, _Callback, _FlatMap, _FromExit, _Succeed, _Suspend
from pyfect._fiber import Fiber, current_fiber
from pyfect._fiber_all import interrupt_all
from pyfect._primitives import _While, known_exit
from pyfect.cause import Cause, Interrupt
from pyfect.cause import die as die_cause
from pyfect.exit import Exit, Failure, Success

_VOID: Effect[None] = _Succeed(None)
_END = object()


def for_each_into[T, B, X, E, R](
    items: Iterable[T],
    f: Callable[[T], Effect[B, E, R]],
    limit: int,
    collect: Callable[[list[B]], X] | None,
) -> Effect[X, E, R]:
    """Run ``f`` on every item, up to ``limit`` at once, ending with
    ``collect(results)``, or with ``None`` and no results kept if
    ``collect`` is ``None`` (Effect's ``discard``). ``items`` is read each
    time the effect runs."""

    def start() -> Effect[Any, E, R]:
        if limit == 1:
            return _Suspend(lambda: _sequential(items, f, collect))
        todo = list(items)
        if not todo:
            return _VOID if collect is None else _Succeed(collect([]))
        out: list[Any] | None = None
        if collect is not None:
            out = [None] * len(todo)
        eff = _Concurrent(todo, f, limit, out).go()
        if collect is None:
            return _VOID if eff is None else _FlatMap(eff, _to_void)
        collect_ = collect

        def result(_: object = None) -> Effect[X]:
            return _Succeed(collect_(cast("list[B]", out)))

        return result() if eff is None else _FlatMap(eff, result)

    return _Suspend(start)


def _to_void(_: object) -> Effect[None]:
    return _VOID


def _sequential[T, B, X, E, R](
    items: Iterable[T],
    f: Callable[[T], Effect[B, E, R]],
    collect: Callable[[list[B]], X] | None,
) -> Effect[Any, E, R]:
    out: list[B] = []
    it = iter(items)
    current: list[Any] = [next(it, _END)]

    def more() -> bool:
        return current[0] is not _END

    def body() -> Effect[B, E, R]:
        return f(current[0])

    def step(b: B) -> None:
        if collect is not None:
            out.append(b)
        current[0] = next(it, _END)

    loop = _While(more, body, step)
    if collect is None:
        return _FlatMap(loop, _to_void)
    return _FlatMap(loop, lambda _: _Succeed(collect(out)))


class _Batch:
    """One ``go`` call's children: whether it stopped at the limit."""

    __slots__ = ("paused",)

    def __init__(self) -> None:
        self.paused = False  # pragma: no mutate, falsy either way


class _Concurrent[T, B, E, R]:
    """One run of ``iterateConcurrentImpl``."""

    __slots__ = (
        "done",
        "f",
        "fibers",
        "index",
        "items",
        "limit",
        "out",
        "parent",
        "pending",
        "resume",
        "terminal",
    )

    def __init__(
        self,
        items: list[T],
        f: Callable[[T], Effect[B, E, R]],
        limit: int,
        out: list[Any] | None,
    ) -> None:
        self.items = items
        self.f = f
        self.limit = limit
        self.out = out
        self.index = 0
        self.done = False
        self.parent: Fiber[Any, Any] | None = None
        # The children alive; ``None`` until the caller has parked.
        self.fibers: dict[Fiber[Any, Any], None] | None = None
        self.resume: Callable[[Effect[Any, Any, Any]], None] | None = None
        self.terminal: Exit[None, Any] | None = None
        # The first item's effect, made before the caller parked.
        self.pending: Effect[B, E, R] | None = None

    def _step(self, i: int, ex: Exit[B, E]) -> Exit[None, E] | None:
        if isinstance(ex, Failure):
            return ex
        if self.out is not None:
            self.out[i] = ex.value
        return None

    def go(self) -> Effect[None, E, R] | None:
        """Take items until one fails, the limit is reached or none are
        left. An effect to continue with, or ``None``."""
        batch = _Batch()
        while self.terminal is None and self.index < len(self.items):
            i = self.index
            eff = self.pending if self.pending is not None else self.f(self.items[i])
            known = known_exit(eff)
            if known is not None:
                self.terminal = self._step(i, known)
                if self.terminal is not None:
                    break
                self.index += 1
                continue
            if self.parent is None:
                return _Callback(partial(self._register, eff))
            self.pending = None
            if self._fork(i, eff, batch):
                if batch.paused:
                    return None
                break
        return self._end()

    def _fork(self, i: int, eff: Effect[B, E, R], batch: _Batch) -> bool:
        """Fork item ``i``'s child; ``True`` to stop taking items."""
        parent = cast("Fiber[Any, Any]", self.parent)
        fibers = cast("dict[Fiber[Any, Any], None]", self.fibers)
        # Daemons, as in Effect; the caller waits for every child anyway.
        fiber = parent._fork(
            eff,
            daemon=True,  # pragma: no mutate
            start_immediately=True,
            uninterruptible="inherit",
        )
        ended = fiber._exit
        if ended is not None:
            self.terminal = self._step(i, ended)
            self.index += 1
            return False
        fibers[fiber] = None
        fiber.add_observer_unsafe(partial(self._on_exit, fiber, i, batch))
        self.index += 1
        if len(fibers) < self.limit:
            return False
        batch.paused = True
        return True

    def _end(self) -> Effect[None, E, R] | None:
        self.done = True
        terminal, fibers = self.terminal, self.fibers
        if terminal is not None:
            if fibers:
                parent = cast("Fiber[Any, Any]", self.parent)
                annotations = parent._interruptor_annotations()
                for child in list(fibers):
                    child.interrupt_as_unsafe(parent.id, annotations)
                return None
            if self.resume is not None or isinstance(terminal, Failure):
                return _FromExit(terminal)
        elif self.resume is not None:
            if fibers is None:
                return _VOID
            if not fibers:
                self.resume(_VOID)
        return None

    def _on_exit(self, fiber: Fiber[Any, Any], at: int, batch: _Batch, ex: Exit[Any, Any]) -> None:
        resume = cast("Callable[[Effect[Any, Any, Any]], None]", self.resume)
        del cast("dict[Fiber[Any, Any], None]", self.fibers)[fiber]
        try:
            if self.terminal is not None:
                self._add_late(ex)
            else:
                result = self._step(at, ex)
                if result is not None:
                    self.terminal = result
                    self.go()
            if batch.paused:
                eff = self.go()
                if eff is not None:
                    resume(eff)
            elif self.done and not self.fibers:
                resume(_VOID if self.terminal is None else _FromExit(self.terminal))
        except KeyboardInterrupt:
            raise
        except BaseException as exc:
            resume(self._fail_defect(exc))

    def _add_late(self, ex: Exit[Any, Any]) -> None:
        """A child's failure after the first: its interrupts only report
        how it was stopped, so they are dropped."""
        if not isinstance(ex, Failure):
            return
        reasons = tuple(r for r in ex.cause.reasons if not isinstance(r, Interrupt))
        if not reasons:
            return
        late: Cause[Any] = Cause(reasons)
        terminal = self.terminal
        self.terminal = Failure(
            late_sibling_cause(terminal.cause, late) if isinstance(terminal, Failure) else late
        )

    def _fail_defect(self, exc: BaseException) -> Effect[None, E, R]:
        defect: Exit[None, Any] = Failure(die_cause(exc))
        self.terminal = defect
        self.done = True
        if self.fibers:
            stop = interrupt_all(list(self.fibers)).uninterruptible()
            return _FlatMap(stop, lambda _: _FromExit(self.terminal or defect))
        return _FromExit(defect)

    def _register(
        self, eff: Effect[B, E, R], cb: Callable[[Effect[Any, Any, Any]], None]
    ) -> Effect[None, Never, R] | None:
        self.parent = current_fiber()
        self.fibers = {}
        self.pending = eff
        self.resume = cb
        try:
            result = self.go()
        except KeyboardInterrupt:
            raise
        except BaseException as exc:
            cb(self._fail_defect(exc))
            return None
        if result is not None:
            cb(result)
            return None
        # Effect's canceler fails with the first failure, if there was one.
        return cast("Effect[None, Never, R]", _Suspend(self._cancel))  # pragma: no mutate, a cast

    def _cancel(self) -> Effect[None, E, R]:
        if self.terminal is None:
            self.terminal = Success(None)
        stop = _VOID if self.fibers is None else interrupt_all(list(self.fibers))
        return _FlatMap(stop, self._after_cancel)

    def _after_cancel(self, _: object) -> Effect[None, E, R]:
        terminal = self.terminal
        return _FromExit(terminal) if isinstance(terminal, Failure) else _VOID


__all__ = ["for_each_into"]
