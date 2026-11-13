"""Running a channel again: ``repeat``, ``forever``, ``retry``, and pacing
items with ``schedule``.

Each run of the repeated channel builds its pull in a child of the
channel's scope, closed with the run's exit before the next run starts,
so resources do not pile up over repetitions.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any

from pyfect._core import Effect, _FailCause, _Gen, _Locally, _Succeed, _Suspend
from pyfect.cause import Fail
from pyfect.cause import fail as fail_cause
from pyfect.channel._base import AnyChannel, AnyPull, end_with
from pyfect.channel._channel import Channel, from_transform, transform_pull
from pyfect.channel._constructors import suspend, unwrap_effect
from pyfect.channel._context import provide_service_effect
from pyfect.channel._lifecycle import on_first
from pyfect.exit import Exit, Failure
from pyfect.pull import catch_done, done_exit_from_cause
from pyfect.schedule import Schedule
from pyfect.schedule._drive import resolve_policy
from pyfect.schedule._model import (
    CurrentMetadata,
    Metadata,
    MetadataStep,
    to_step_with_metadata,
    to_step_with_sleep,
)
from pyfect.scope import CloseableScope, Scope

type Channel_ = Channel[Any, Any, Any, Any, Any, Any, Any]
type OnExit = Callable[[Exit[Any, Any], CloseableScope], Effect[Any, Any, Any]]
type Policy = Schedule[Any, Any, Any, Any] | Callable[[Any], Any]

_VOID: Effect[None] = _Succeed(None)


def repeat_loop(self: AnyChannel, on_exit: OnExit) -> Channel_:
    """Run ``self`` again each time ``on_exit(exit, scope)`` succeeds after
    a run; its failure (or end) is the channel's."""

    def transform(upstream: AnyPull, scope: CloseableScope) -> Effect[AnyPull]:
        current: AnyPull | None = None

        def make_pull() -> AnyPull:
            run_scope = scope.fork_unsafe()

            def recover(cause: Any) -> AnyPull:
                ex = done_exit_from_cause(cause)
                # As Effect's: ``on_exit`` and ``make_pull`` are called in
                # the continuations, not as effects of their own.
                return (
                    run_scope.close(ex)
                    .flat_map(lambda _: on_exit(ex, scope))
                    .flat_map(lambda _: make_pull())
                )

            def started(pull: AnyPull) -> AnyPull:
                nonlocal current
                current = pull.catch_cause(recover)
                return current

            return self._transform(upstream, run_scope).flat_map(started)

        return _Succeed(_Suspend(lambda: make_pull() if current is None else current))

    return from_transform(transform)


def _with_metadata(self: AnyChannel, read: Callable[[], Metadata[Any, Any]]) -> AnyChannel:
    return provide_service_effect(CurrentMetadata, _Suspend(lambda: _Succeed(read())))(self)


def repeat(self: AnyChannel, policy: Policy) -> Channel_:
    schedule = resolve_policy(policy, None, None, None, None)

    def start(step: MetadataStep[Any, Any, Any, Any]) -> AnyChannel:
        meta: Metadata[Any, Any] = CurrentMetadata.default()

        def stepped(ex: Exit[Any, Any], _: CloseableScope) -> Effect[Any, Any, Any]:
            if isinstance(ex, Failure):
                return _FailCause(ex.cause)

            def keep(next_meta: Metadata[Any, Any]) -> None:
                nonlocal meta
                meta = next_meta

            return catch_done(step(ex.value).map(keep), lambda _: end_with(ex.value))

        return repeat_loop(_with_metadata(self, lambda: meta), stepped)

    return unwrap_effect(to_step_with_metadata(schedule).map(start))


def forever(self: AnyChannel) -> Channel_:
    def again(ex: Exit[Any, Any], _: CloseableScope) -> Effect[None, Any, Any]:
        return _FailCause(ex.cause) if isinstance(ex, Failure) else _VOID

    return repeat_loop(self, again)


def retry(self: AnyChannel, policy: Policy) -> Channel_:
    schedule = resolve_policy(policy, None, None, None, None)

    def build() -> Channel_:
        step: MetadataStep[Any, Any, Any, Any] | None = None
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

            # Effect's ``Effect.gen`` making the step once, then stepping.
            def body() -> Generator[Effect[Any, Any, Any], Any]:
                nonlocal step, meta
                made: MetadataStep[Any, Any, Any, Any] = (
                    (yield to_step_with_metadata(schedule)) if step is None else step
                )
                step = made
                meta = yield made(error)

            failed = _FailCause(fail_cause(error))
            stepping = catch_done(_Gen(body), lambda _: failed)
            return _Locally(stepping, lambda ctx: ctx.add(Scope, scope))

        with_reset = on_first(_with_metadata(self, lambda: meta), reset)
        return repeat_loop(with_reset, stepped)

    return suspend(build)


def schedule(self: AnyChannel, policy: Schedule[Any, Any, Any, Any]) -> Channel_:
    # Effect's: the pull, tapped with the step (which sleeps); the step's
    # ``Done`` ends the channel with the schedule's output.
    def with_step(pull: AnyPull, step: Callable[[Any], Effect[Any, Any, Any]]) -> AnyPull:
        return pull.tap(step)

    return transform_pull(
        self,
        lambda pull, _: to_step_with_sleep(policy).map(lambda step: with_step(pull, step)),
    )
