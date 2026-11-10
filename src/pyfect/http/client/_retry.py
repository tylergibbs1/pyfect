"""Retrying transient failures (Effect's ``HttpClient.retryTransient``)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pyfect.duration import Duration, to_millis
from pyfect.effect import Effect
from pyfect.errors import TimeoutException
from pyfect.http.client._service import RetryOn
from pyfect.http.error import HttpClientError, StatusCodeError, TransportError
from pyfect.http.headers import parse_retry_after, retry_after_delay
from pyfect.http.response import HttpClientResponse
from pyfect.persistence._seconds import millis
from pyfect.persistence.rate_limiter._store import clamp_adaptive_millis
from pyfect.result import Ok
from pyfect.schedule import Continue, Schedule, forever, from_step, to_step
from pyfect.schedule._model import Decision, StepFn

_TRANSIENT_STATUSES = frozenset((408, 429, 500, 502, 503, 504))


def is_transient_response(response: HttpClientResponse) -> bool:
    return response.status in _TRANSIENT_STATUSES


def is_transient_error(error: object) -> bool:
    """A timeout, a transport failure, or a transient status."""
    if isinstance(error, TimeoutException):
        return True
    if not isinstance(error, HttpClientError):
        return False
    reason = error.reason
    return isinstance(reason, TransportError) or (
        isinstance(reason, StatusCodeError) and is_transient_response(reason.response)
    )


def retry_after_of(input: object, now_millis: float) -> Duration | None:
    """The ``Retry-After`` delay of a response (or of the response of an
    ``HttpClientError``), at least a millisecond."""
    response = input.response if isinstance(input, HttpClientError) else input
    if not isinstance(response, HttpClientResponse):
        return None
    return retry_after_from_header(response.headers.get("retry-after"), now_millis)


def retry_after_from_header(header: str | None, now_millis: float) -> Duration | None:
    """The delay a ``Retry-After`` value asks for, from a millisecond to an
    hour (Effect leaves it unbounded, so one response could park a request
    for good); ``None`` for a missing or invalid one (RFC 9110 treats it as
    absent)."""
    if header is None:
        return None
    match parse_retry_after(header):
        case Ok(value):
            return millis(clamp_adaptive_millis(to_millis(retry_after_delay(value, now_millis))))
        case _:
            return None


def with_retry_after[O, E, R](schedule: Schedule[O, Any, E, R]) -> Schedule[O, Any, E, R]:
    """``schedule``, waiting at least each input's ``Retry-After``."""

    def wrap(step: StepFn[O, Any, E, R]) -> StepFn[O, Any, E, R]:
        def run(now: float, input: Any) -> Effect[Decision[O], E, R]:
            retry_after = retry_after_of(input, now * 1000)
            if retry_after is None:
                return step(now, input)
            return step(now, input).map(
                lambda decision: (
                    Continue(decision.output, max(decision.delay, retry_after))
                    if isinstance(decision, Continue)
                    else decision
                )
            )

        return run

    return from_step(to_step(schedule).map(wrap))


def retry_transient(
    schedule: Schedule[Any, Any, Any, Any] | None,
    *,
    retry_on: RetryOn,
    while_: Callable[[Any], bool] | None,
    times: int | None,
) -> Callable[[Effect[HttpClientResponse, Any, Any]], Effect[HttpClientResponse, Any, Any]]:
    policy = with_retry_after(forever if schedule is None else schedule)
    extra = while_

    def retry_while(error: object) -> bool:
        return is_transient_error(error) or (extra is not None and extra(error))

    def apply(
        sending: Effect[HttpClientResponse, Any, Any],
    ) -> Effect[HttpClientResponse, Any, Any]:
        if retry_on != "errors-only":
            sending = sending.repeat(schedule=policy, times=times, while_=is_transient_response)
        if retry_on != "response-only":
            sending = sending.retry(schedule=policy, times=times, while_=retry_while)
        return sending

    return apply


__all__ = [
    "is_transient_error",
    "is_transient_response",
    "retry_after_from_header",
    "retry_after_of",
    "with_retry_after",
]
