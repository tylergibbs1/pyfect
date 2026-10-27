"""Running a channel: the ``run_*`` methods, ``to_pull`` and
``to_pull_scoped``.

A run builds the channel's pull in a fresh scope, with an upstream that
ends at once, pulls in a ``PullLoop`` until ``Done``, and closes the scope
with the run's exit.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pyfect._context_effects import provide_context
from pyfect._core import Effect, _FailCause, _Succeed, _Suspend, _Sync, _WithFiber
from pyfect._fiber import Fiber
from pyfect.cause import fail
from pyfect.channel._channel import AnyPull, Channel
from pyfect.channel._loop import PullLoop
from pyfect.errors import Done
from pyfect.option import Option, Some
from pyfect.pull import catch_done
from pyfect.scope import CloseableScope, Scope
from pyfect.semaphore import Semaphore

type AnyChannel = Channel[Any, Any, Any, Any, Any, Any, Any]
type AnyEffect = Effect[Any, Any, Any]

ENDED: AnyPull = _FailCause(fail(Done()))
"""A pull that ends at once with ``Done()``: the upstream of a channel run
on its own."""

_VOID: Effect[None] = _Succeed(None)


def _ignore(_: object) -> None:
    return None


def _run_with(
    self: AnyChannel,
    consume: Callable[[AnyPull], AnyEffect],
    on_done: Callable[[Any], AnyEffect] = _Succeed,
) -> AnyEffect:
    def run() -> AnyEffect:
        scope = CloseableScope()
        consumed = self._transform(ENDED, scope).flat_map(consume)
        return catch_done(consumed, on_done).on_exit(scope.close)

    return _Suspend(run)


def run_collect(self: AnyChannel) -> Effect[list[Any], Any, Any]:
    def run() -> AnyEffect:
        items: list[Any] = []
        return _run_with(self, lambda pull: PullLoop(pull, items.append), lambda _: _Succeed(items))

    return _Suspend(run)


def run_drain(self: AnyChannel) -> AnyEffect:
    return _run_with(self, lambda pull: PullLoop(pull, _ignore))


def run_for_each(self: AnyChannel, f: Callable[[Any], AnyEffect]) -> AnyEffect:
    return _run_with(self, lambda pull: PullLoop(pull.flat_map(f), _ignore))


def run_for_each_while(self: AnyChannel, f: Callable[[Any], Effect[bool, Any, Any]]) -> AnyEffect:
    def go_on(more: bool) -> AnyEffect:
        return _VOID if more else ENDED

    return _run_with(
        self, lambda pull: PullLoop(pull.flat_map(f).flat_map(go_on), _ignore), lambda _: _VOID
    )


def run_fold(
    self: AnyChannel, initial: Callable[[], Any], f: Callable[[Any, Any], Any]
) -> AnyEffect:
    def run() -> AnyEffect:
        state = initial()

        def step(item: Any) -> None:
            nonlocal state
            state = f(state, item)

        return _run_with(self, lambda pull: PullLoop(pull, step), lambda _: _Sync(lambda: state))

    return _Suspend(run)


def run_fold_effect(
    self: AnyChannel, initial: Callable[[], Any], f: Callable[[Any, Any], AnyEffect]
) -> AnyEffect:
    def run() -> AnyEffect:
        state = initial()

        def step(item: Any) -> None:
            nonlocal state
            state = item

        return _run_with(
            self,
            lambda pull: PullLoop(pull.flat_map(lambda item: f(state, item)), step),
            lambda _: _Sync(lambda: state),
        )

    return _Suspend(run)


def run_head(self: AnyChannel) -> Effect[Option[Any], Any, Any]:
    def run() -> AnyEffect:
        head: Option[Any] = None

        def keep(item: Any) -> AnyEffect:
            nonlocal head
            head = Some(item)
            return ENDED

        return _run_with(self, lambda pull: pull.flat_map(keep), lambda _: _Sync(lambda: head))

    return _Suspend(run)


def run_last(self: AnyChannel) -> Effect[Option[Any], Any, Any]:
    def run() -> AnyEffect:
        last: Option[Any] = None

        def keep(item: Any) -> None:
            nonlocal last
            last = Some(item)

        return _run_with(self, lambda pull: PullLoop(pull, keep), lambda _: _Sync(lambda: last))

    return _Suspend(run)


def to_pull(self: AnyChannel) -> AnyEffect:
    def build(fiber: Fiber[Any, Any]) -> AnyEffect:
        context = fiber._context
        turns = Semaphore(1)
        return self._transform(ENDED, context.unsafe_get(Scope)).map(
            lambda pull: turns.with_permits(pull.pipe(provide_context(context)))
        )

    return _WithFiber(build)


def to_pull_scoped(self: AnyChannel, scope: CloseableScope) -> AnyEffect:
    return _Suspend(lambda: self._transform(ENDED, scope))
