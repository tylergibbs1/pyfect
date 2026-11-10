"""Timing out requests (Effect's ``HttpClient.timeout``)."""

from __future__ import annotations

from collections.abc import Callable

from pyfect.duration import Input as DurationInput
from pyfect.duration import from_input_unsafe
from pyfect.effect import Effect, fail
from pyfect.errors import TimeoutException
from pyfect.http.error import HttpClientError, TransportError
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse


def timeout[E, R](
    duration: DurationInput,
) -> Callable[
    [Effect[HttpClientResponse, E, R], HttpClientRequest],
    Effect[HttpClientResponse, E | HttpClientError, R],
]:
    seconds = from_input_unsafe(duration)
    description = f"timed out after {seconds.format()}"

    def apply(
        sending: Effect[HttpClientResponse, E, R], request: HttpClientRequest
    ) -> Effect[HttpClientResponse, E | HttpClientError, R]:
        return sending.timeout_or_else(
            seconds,
            or_else=lambda: fail(
                HttpClientError(TransportError(request, TimeoutException(seconds), description))
            ),
        )

    return apply
