"""Circuit breaking requests (Effect's ``HttpClient.withCircuitBreaker`` and
``circuitBreakerClassifier``)."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pyfect.cause import Fail
from pyfect.clock import now_nanos
from pyfect.effect import Effect
from pyfect.errors import TimeoutException
from pyfect.exit import Exit, Success
from pyfect.http import url as _url
from pyfect.http.client._retry import retry_after_of
from pyfect.http.error import HttpClientError, StatusCodeError, TransportError
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.persistence.circuit_breaker import (
    Outcome,
    OutcomeKind,
    failure,
    ignored,
    success,
)

if TYPE_CHECKING:
    from pyfect.duration import Seconds
    from pyfect.persistence.circuit_breaker import (
        CircuitBreakerService,
        Classifier,
        ClassifyContext,
    )

_FAILING_STATUSES = frozenset((408, 500, 502, 503, 504))


def _status_outcome(status: int) -> OutcomeKind:
    if status == 429:
        return "Ignored"
    return "Failure" if status in _FAILING_STATUSES else "Success"


def _error_outcome(error: object) -> OutcomeKind:
    if isinstance(error, TimeoutException):
        return "Failure"
    if not isinstance(error, HttpClientError):
        return "Ignored"
    reason = error.reason
    if isinstance(reason, TransportError):
        return "Failure"
    if isinstance(reason, StatusCodeError):
        return _status_outcome(reason.response.status)
    return "Ignored"


def _classify(exit: Exit[HttpClientResponse, object], now_millis: float) -> Outcome:
    if isinstance(exit, Success):
        kind = _status_outcome(exit.value.status)
        if kind == "Failure":
            return failure(retry_after=retry_after_of(exit.value, now_millis))
        return success if kind == "Success" else ignored
    failed = succeeded = False
    retry_after: Seconds | None = None
    for reason in exit.cause.reasons:
        if not isinstance(reason, Fail):
            continue
        kind = _error_outcome(reason.error)
        if kind == "Failure":
            failed = True
            hint = retry_after_of(reason.error, now_millis)
            if hint is not None:
                retry_after = hint if retry_after is None else max(retry_after, hint)
        elif kind == "Success":
            succeeded = True
    if failed:
        return failure(retry_after=retry_after)
    return success if succeeded else ignored


def circuit_breaker_classifier(
    exit: Exit[HttpClientResponse, object], context: ClassifyContext | None = None
) -> Effect[Outcome]:
    """The default ``with_circuit_breaker`` classifier, the same for the
    probe (``context``) as for any call. A failure: a
    timeout, a transport error, or a 408, 500, 502, 503 or 504 status
    (returned or wrapped in an ``HttpClientError``), with the response's
    ``Retry-After`` (the longest of several) as the hint. Ignored: a 429
    (left to ``with_rate_limiter``), other ``HttpClientError`` reasons,
    other errors and defects. Any other status is a success. Of several
    errors, a failing one wins over a successful one, which wins over the
    ignored ones."""
    return now_nanos().map(lambda nanos: _classify(exit, nanos // 1_000_000))


def request_origin(request: HttpClientRequest) -> str:
    """The request URL's origin, or the raw URL when it cannot be parsed."""
    url = request.to_url()
    return request.url if url is None else _url.origin(url)


type Send = Effect[HttpClientResponse, Any, Any]


def with_circuit_breaker(
    breaker: CircuitBreakerService,
    key: str | Callable[[HttpClientRequest], str] | None,
    classify: Classifier[HttpClientResponse, Any, Any] | None,
) -> Callable[[Send, HttpClientRequest], Send]:
    """The ``transform`` function of ``HttpClientService.with_circuit_breaker``."""
    resolve: Callable[[HttpClientRequest], str] = (
        request_origin if key is None else (lambda _: key) if isinstance(key, str) else key
    )
    classifier = circuit_breaker_classifier if classify is None else classify
    return lambda sending, request: breaker.execute(
        sending, key=resolve(request), classify=classifier
    )


__all__ = ["circuit_breaker_classifier", "request_origin", "with_circuit_breaker"]
