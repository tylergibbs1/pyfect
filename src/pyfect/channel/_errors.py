"""The work behind the failure-handling ``Channel`` methods.

``catch_cause`` is the one recovering channel: it releases the failed
channel's resources (its forked scope, closed with the failure) before
building the handler's channel on the same upstream. The typed
recoveries are ``catch_cause`` with a handler that finds the cause's
recoverable error, so a defect always wins.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

from pyfect._core import Effect, _FailCause, _MatchCause, _Succeed, _Suspend, _WithFiber
from pyfect.cause import Cause, Fail
from pyfect.cause import die as die_cause
from pyfect.channel._base import AnyChannel, AnyPull, is_done
from pyfect.channel._channel import Channel, from_transform, transform_pull
from pyfect.channel._constructors import empty, fail, from_effect_drain
from pyfect.channel._constructors import fail_cause as fail_cause_channel
from pyfect.exit import Failure
from pyfect.pull import is_done_cause
from pyfect.result import Err, Ok, Result
from pyfect.scope import CloseableScope

if TYPE_CHECKING:
    from pyfect._fiber import Fiber
    from pyfect.logger import Severity

type IgnoreLog = bool | Severity | Literal["Unhandled"]
"""``ignore``'s ``log``: ``"Unhandled"`` logs at the ``UnhandledLogLevel`` read when the
failure happens (nothing when it is ``None``)."""

type Channel_ = Channel[Any, Any, Any, Any, Any, Any, Any]
type Handler = Callable[[Any], AnyChannel]


def catch_cause(self: AnyChannel, f: Callable[[Cause[Any]], AnyChannel]) -> Channel_:
    def transform(upstream: AnyPull, scope: CloseableScope) -> Effect[AnyPull]:
        recovering = _Recovering(f, upstream, scope)
        return self._transform(upstream, recovering.forked).map(recovering.with_pull)

    return from_transform(transform)


class _Recovering:
    """One run of ``catch_cause``: ``current`` is the handler's pull once
    the channel has failed. It holds no pull built from its own methods."""

    __slots__ = ("current", "f", "forked", "scope", "upstream")

    def __init__(
        self, f: Callable[[Cause[Any]], AnyChannel], upstream: AnyPull, scope: CloseableScope
    ) -> None:
        self.f = f
        self.upstream = upstream
        self.scope = scope
        self.forked = scope.fork_unsafe()
        self.current: AnyPull | None = None

    def with_pull(self, pull: AnyPull) -> AnyPull:
        protected = _MatchCause(pull, self.recover, None)
        return _Suspend(lambda: protected if self.current is None else self.current)

    def recover(self, cause: Cause[Any]) -> AnyPull:
        if is_done_cause(cause):
            return _FailCause(cause)
        failed, self.forked = self.forked, self.scope.fork_unsafe()
        return (
            failed.close(Failure(cause))
            .and_then(self.f(cause)._transform(self.upstream, self.forked))
            .flat_map(self.switch)
        )

    def switch(self, pull: AnyPull) -> AnyPull:
        self.current = pull
        return pull


def catch_cause_if(
    self: AnyChannel,
    predicate: Callable[[Cause[Any]], bool],
    f: Callable[[Cause[Any]], AnyChannel],
) -> Channel_:
    return catch_cause(
        self, lambda cause: f(cause) if predicate(cause) else fail_cause_channel(cause)
    )


def _recovering(f: Handler) -> Callable[[Cause[Any]], AnyChannel]:
    def handle(cause: Cause[Any]) -> AnyChannel:
        found = cause.find_recoverable_error()
        return f(found.error) if isinstance(found, Fail) else fail_cause_channel(found)

    return handle


def catch_all(self: AnyChannel, f: Handler) -> Channel_:
    return catch_cause(self, _recovering(f))


def catch_if(
    self: AnyChannel, predicate: Callable[[Any], bool], f: Handler, or_else: Handler | None
) -> Channel_:
    def handle(error: Any) -> AnyChannel:
        if predicate(error):
            return f(error)
        return fail(error) if or_else is None else or_else(error)

    return catch_all(self, handle)


def catch_filter(
    self: AnyChannel,
    filter: Callable[[Any], Result[Any, Any]],
    f: Handler,
    or_else: Handler | None,
) -> Channel_:
    def handle(error: Any) -> AnyChannel:
        match filter(error):
            case Ok(value):
                return f(value)
            case Err(rest):
                return fail(rest) if or_else is None else or_else(rest)

    return catch_all(self, handle)


def catch_cause_filter(
    self: AnyChannel,
    filter: Callable[[Cause[Any]], Result[Any, Cause[Any]]],
    f: Callable[[Any, Cause[Any]], AnyChannel],
) -> Channel_:
    def handle(cause: Cause[Any]) -> AnyChannel:
        match filter(cause):
            case Ok(value):
                return f(value, cause)
            case Err(rest):
                return fail_cause_channel(rest)

    return catch_cause(self, handle)


def catch_defect(self: AnyChannel, f: Callable[[object], AnyChannel]) -> Channel_:
    def handle(cause: Cause[Any]) -> AnyChannel:
        defect = cause.find_defect()
        return f(defect.value) if isinstance(defect, Ok) else fail_cause_channel(cause)

    return catch_cause(self, handle)


def tap_cause(self: AnyChannel, f: Callable[[Cause[Any]], Effect[Any, Any, Any]]) -> Channel_:
    return catch_cause(self, lambda cause: from_effect_drain(f(cause).and_then(_FailCause(cause))))


def tap_error(self: AnyChannel, f: Callable[[Any], Effect[Any, Any, Any]]) -> Channel_:
    def tap(error: Any) -> Effect[None, Any, Any]:
        return _Succeed(None) if is_done(error) else f(error).as_void()

    return transform_pull(self, lambda pull, _: _Succeed(pull.tap_error(tap)))


def map_error(self: AnyChannel, f: Callable[[Any], Any]) -> Channel_:
    def mapped(error: Any) -> Any:
        return error if is_done(error) else f(error)

    return transform_pull(self, lambda pull, _: _Succeed(pull.map_error(mapped)))


def or_die(self: AnyChannel) -> Channel_:
    return catch_all(self, lambda error: fail_cause_channel(die_cause(error)))


def _logging(self: AnyChannel, log: IgnoreLog, *, fails_only: bool) -> AnyChannel:
    if log is False:
        return self
    from pyfect.logger import log_with_level

    def at(level: Severity | None, cause: Cause[Any]) -> Effect[None]:
        return log_with_level(level, cause)

    def at_unhandled(cause: Cause[Any]) -> Effect[None]:
        from pyfect.logger import UnhandledLogLevel

        def body(fiber: Fiber[Any, Any]) -> Effect[None]:
            level = fiber.get_ref(UnhandledLogLevel)
            return _Succeed(None) if level is None else at(level, cause)

        return _WithFiber(body)

    def write(cause: Cause[Any]) -> Effect[None]:
        if fails_only and not cause.has_fails:
            return _Succeed(None)
        if log == "Unhandled":
            return at_unhandled(cause)
        return at(None if log is True else log, cause)

    return tap_cause(self, write)


def ignore(self: AnyChannel, log: IgnoreLog) -> Channel_:
    return catch_all(_logging(self, log, fails_only=True), lambda _: empty)


def ignore_cause(self: AnyChannel, log: IgnoreLog) -> Channel_:
    return catch_cause(_logging(self, log, fails_only=False), lambda _: empty)
