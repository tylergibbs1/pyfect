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
from typing import TYPE_CHECKING, Any

from pyfect._core import Effect, _FailCause, _MatchCause, _Succeed, _Suspend
from pyfect.cause import Cause, Fail, _as_exception
from pyfect.cause import die as die_cause
from pyfect.channel._base import AnyChannel, AnyPull, is_done
from pyfect.channel._channel import Channel, from_transform, transform_pull
from pyfect.channel._constructors import empty, fail, from_effect_drain
from pyfect.channel._constructors import fail_cause as fail_cause_channel
from pyfect.exit import Failure
from pyfect.pull import is_done_cause
from pyfect.scope import CloseableScope

if TYPE_CHECKING:
    from pyfect.logger import Severity

type Channel_ = Channel[Any, Any, Any, Any, Any, Any, Any]
type Handler = Callable[[Any], AnyChannel]


def catch_cause(self: AnyChannel, f: Callable[[Cause[Any]], AnyChannel]) -> Channel_:
    def transform(upstream: AnyPull, scope: CloseableScope) -> Effect[AnyPull]:
        forked = scope._fork_now()

        def with_pull(pull: AnyPull) -> AnyPull:
            current: AnyPull

            def switch(pull: AnyPull) -> AnyPull:
                nonlocal current
                current = pull
                return pull

            def recover(cause: Cause[Any]) -> AnyPull:
                nonlocal forked
                if is_done_cause(cause):
                    return _FailCause(cause)
                failed, forked = forked, scope._fork_now()
                return (
                    failed.close(Failure(cause))
                    .and_then(f(cause)._transform(upstream, forked))
                    .flat_map(switch)
                )

            current = _MatchCause(pull, recover, None)
            return _Suspend(lambda: current)

        return self._transform(upstream, forked).map(with_pull)

    return from_transform(transform)


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


def catch_defect(self: AnyChannel, f: Callable[[BaseException], AnyChannel]) -> Channel_:
    def handle(cause: Cause[Any]) -> AnyChannel:
        defect = cause.find_defect()
        return fail_cause_channel(cause) if defect is None else f(defect)

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
    return catch_all(self, lambda error: fail_cause_channel(die_cause(_as_exception(error))))


def _logging(self: AnyChannel, log: bool | Severity, *, fails_only: bool) -> AnyChannel:
    if log is False:
        return self
    from pyfect.logger import log_with_level

    level = None if log is True else log

    def write(cause: Cause[Any]) -> Effect[None]:
        if fails_only and not cause.has_fails:
            return _Succeed(None)
        return log_with_level(level, cause)

    return tap_cause(self, write)


def ignore(self: AnyChannel, log: bool | Severity) -> Channel_:
    return catch_all(_logging(self, log, fails_only=True), lambda _: empty)


def ignore_cause(self: AnyChannel, log: bool | Severity) -> Channel_:
    return catch_cause(_logging(self, log, fails_only=False), lambda _: empty)
