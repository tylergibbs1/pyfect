"""Running a channel again: ``repeat``, ``forever``, ``retry``, and pacing
items with ``schedule``.

Each run of the repeated channel builds its pull in a child of the
channel's scope, closed with the run's exit before the next run starts,
so resources do not pile up over repetitions.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pyfect._core import Effect, _FailCause, _Locally, _MatchCause, _Succeed, _Suspend
from pyfect.cause import Fail
from pyfect.cause import fail as fail_cause
from pyfect.channel._base import AnyChannel, AnyPull, end_with
from pyfect.channel._channel import Channel, from_transform, transform_pull
from pyfect.channel._constructors import unwrap_effect
from pyfect.channel._context import provide_service_effect
from pyfect.channel._lifecycle import on_first
from pyfect.exit import Exit, Failure
from pyfect.pull import done_exit_from_cause
from pyfect.schedule import Schedule
from pyfect.schedule._drive import resolve_policy
from pyfect.schedule._model import CurrentMetadata, Metadata, Stop, to_step_with_metadata
from pyfect.scope import CloseableScope, Scope

type Channel_ = Channel[Any, Any, Any, Any, Any, Any, Any]
type OnExit = Callable[[Exit[Any, Any], CloseableScope], Effect[Any, Any, Any]]
type Policy = Schedule[Any, Any, Any, Any] | Callable[[Any], Any]

_VOID: Effect[None] = _Succeed(None)


def repeat_loop(self: AnyChannel, on_exit: OnExit) -> Channel_:
    """Run ``self`` again each time ``on_exit(exit, scope)`` succeeds after
    a run; its failure (or end) is the channel's."""

    def transform(upstream: AnyPull, scope: CloseableScope) -> Effect[AnyPull]:
        return _Succeed(_Suspend(_RepeatLoop(self, upstream, scope, on_exit).next_pull))

    return from_transform(transform)


class _RepeatLoop:
    """One run of ``repeat_loop``. It keeps the current run's pull bare and
    wraps it with its recovery (itself) on each pull: a stored wrapped pull
    would refer back here and keep the run alive after it ends."""

    __slots__ = ("channel", "current", "on_exit", "scope", "upstream")

    def __init__(
        self, channel: AnyChannel, upstream: AnyPull, scope: CloseableScope, on_exit: OnExit
    ) -> None:
        self.channel = channel
        self.upstream = upstream
        self.scope = scope
        self.on_exit = on_exit
        self.current: tuple[AnyPull, CloseableScope] | None = None

    def next_pull(self) -> AnyPull:
        current = self.current
        return self.make_pull() if current is None else _MatchCause(current[0], self, None)

    def make_pull(self) -> AnyPull:
        run_scope = self.scope.fork_unsafe()

        def started(pull: AnyPull) -> AnyPull:
            self.current = (pull, run_scope)
            return _MatchCause(pull, self, None)

        return self.channel._transform(self.upstream, run_scope).flat_map(started)

    def __call__(self, cause: Any) -> AnyPull:
        assert self.current is not None
        ex = done_exit_from_cause(cause)
        return (
            self.current[1]
            .close(ex)
            .and_then(self.on_exit(ex, self.scope))
            .and_then(_Suspend(self.make_pull))
        )


def _with_metadata(self: AnyChannel, read: Callable[[], Metadata[Any, Any]]) -> AnyChannel:
    return provide_service_effect(CurrentMetadata, _Suspend(lambda: _Succeed(read())))(self)


def repeat(self: AnyChannel, policy: Policy) -> Channel_:
    schedule = resolve_policy(policy, None, None, None, None)

    def start(step: Callable[[Any], Effect[Any, Any, Any]]) -> AnyChannel:
        meta: Metadata[Any, Any] = CurrentMetadata.default()

        def stepped(ex: Exit[Any, Any], _: CloseableScope) -> Effect[Any, Any, Any]:
            if isinstance(ex, Failure):
                return _FailCause(ex.cause)

            def keep(decision: Metadata[Any, Any] | Stop[Any]) -> Effect[None, Any, Any]:
                nonlocal meta
                if isinstance(decision, Stop):
                    return end_with(ex.value)
                meta = decision
                return _VOID

            return step(ex.value).flat_map(keep)

        return repeat_loop(_with_metadata(self, lambda: meta), stepped)

    return unwrap_effect(to_step_with_metadata(schedule).map(start))


def forever(self: AnyChannel) -> Channel_:
    def again(ex: Exit[Any, Any], _: CloseableScope) -> Effect[None, Any, Any]:
        return _FailCause(ex.cause) if isinstance(ex, Failure) else _VOID

    return repeat_loop(self, again)


def retry(self: AnyChannel, policy: Policy) -> Channel_:
    schedule = resolve_policy(policy, None, None, None, None)

    def build() -> AnyChannel:
        step: Callable[[Any], Effect[Any, Any, Any]] | None = None
        meta: Metadata[Any, Any] = CurrentMetadata.default()

        def reset(_: Any) -> Effect[None]:
            nonlocal step
            step = None
            return _VOID

        def stepped(ex: Exit[Any, Any], scope: CloseableScope) -> Effect[Any, Any, Any]:
            if not isinstance(ex, Failure):
                return end_with(ex.value)
            found = ex.cause.find_recoverable_error()
            if not isinstance(found, Fail):
                return _FailCause(found)
            error = found.error

            def keep(decision: Metadata[Any, Any] | Stop[Any]) -> Effect[None, Any, Any]:
                nonlocal meta
                if isinstance(decision, Stop):
                    return _FailCause(fail_cause(error))
                meta = decision
                return _VOID

            def with_step(made: Callable[[Any], Effect[Any, Any, Any]]) -> Effect[Any, Any, Any]:
                nonlocal step
                step = made
                return made(error).flat_map(keep)

            make = _Succeed(step) if step is not None else to_step_with_metadata(schedule)
            return _Locally(make.flat_map(with_step), lambda ctx: ctx.add(Scope, scope))

        with_reset = on_first(_with_metadata(self, lambda: meta), reset)
        return repeat_loop(with_reset, stepped)

    return from_transform(lambda upstream, scope: build()._transform(upstream, scope))


def schedule(self: AnyChannel, policy: Schedule[Any, Any, Any, Any]) -> Channel_:
    def with_step(pull: AnyPull, step: Callable[[Any], Effect[Any, Any, Any]]) -> AnyPull:
        def paced(item: Any) -> Effect[Any, Any, Any]:
            def decided(decision: Metadata[Any, Any] | Stop[Any]) -> Effect[Any, Any, Any]:
                return end_with(decision.output) if isinstance(decision, Stop) else _Succeed(item)

            return step(item).flat_map(decided)

        return pull.flat_map(paced)

    return transform_pull(
        self,
        lambda pull, _: to_step_with_metadata(policy).map(lambda step: with_step(pull, step)),
    )
