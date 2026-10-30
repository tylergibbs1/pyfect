"""Rate limiting requests (Effect's ``HttpClient.withRateLimiter``).

Budgets and reset times are in epoch milliseconds, as Effect keeps them,
so header arithmetic matches it; windows and delays are ``Seconds``.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypedDict

from pyfect.clock import ClockService, clock_with, sleep
from pyfect.duration import Duration, Seconds, to_millis
from pyfect.effect import Effect, fail, succeed
from pyfect.http.client._retry import retry_after_from_header
from pyfect.http.error import HttpClientError, StatusCodeError
from pyfect.http.headers import Headers
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.persistence._seconds import millis
from pyfect.persistence.rate_limiter._store import clamp_adaptive_millis

if TYPE_CHECKING:
    from pyfect.persistence.rate_limiter import (
        AdaptiveConsumeResult,
        Algorithm,
        RateLimiterService,
    )

_MIN_MILLIS = 1.0
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


class RateLimitHeaders(TypedDict, total=False):
    """Header names read instead of the built-in ones (any case). A name
    given replaces the built-in names for that value; one left out keeps
    them."""

    limit: str
    """The most requests in a window (default ``ratelimit-limit``,
    ``x-ratelimit-limit``)."""
    remaining: str
    """The requests left in the window (default ``ratelimit-remaining``,
    ``x-ratelimit-remaining``)."""
    reset: str
    """When the window resets: seconds from now, or an epoch time in
    seconds or milliseconds (default ``ratelimit-reset``,
    ``x-ratelimit-reset``)."""
    reset_after: str
    """Seconds until the window resets (default ``ratelimit-reset-after``,
    ``x-ratelimit-reset-after``)."""
    retry_after: str
    """The delay before retrying a ``429`` (default ``retry-after``)."""


@dataclass(frozen=True, slots=True)
class _HeaderNames:
    limit: tuple[str, ...]
    remaining: tuple[str, ...]
    reset: tuple[str, ...]
    reset_after: tuple[str, ...]
    retry_after: tuple[str, ...]


def _names(given: str | None, *defaults: str) -> tuple[str, ...]:
    return defaults if given is None else (given.lower(),)


def _header_names(overrides: RateLimitHeaders) -> _HeaderNames:
    return _HeaderNames(
        limit=_names(overrides.get("limit"), "ratelimit-limit", "x-ratelimit-limit"),
        remaining=_names(
            overrides.get("remaining"), "ratelimit-remaining", "x-ratelimit-remaining"
        ),
        reset=_names(overrides.get("reset"), "ratelimit-reset", "x-ratelimit-reset"),
        reset_after=_names(
            overrides.get("reset_after"), "ratelimit-reset-after", "x-ratelimit-reset-after"
        ),
        retry_after=_names(overrides.get("retry_after"), "retry-after"),
    )


@dataclass(frozen=True, slots=True)
class _Limits:
    limit: float
    window: Seconds
    initial: bool


@dataclass(slots=True)
class _Budget:
    sent: float = 0
    """Tokens admitted for the key."""
    observed: float = 0
    """The ``sent`` total of the request whose remaining count was applied."""
    remaining: float = 0
    """The remaining count reported for the ``observed`` request."""
    reset_at: float = 0
    """When the server's budget resets, in epoch milliseconds."""


def _header(headers: Headers, names: tuple[str, ...]) -> str | None:
    for name in names:
        value = headers.get(name)
        if value is not None:
            return value
    return None


def _number(value: str | None) -> float | None:
    if value is None:
        return None
    match = _NUMBER.search(value)
    if match is None:
        return None
    parsed = float(match[0])
    return parsed if math.isfinite(parsed) else None


def _now_millis(clock: ClockService) -> int:
    return clock.unsafe_now_nanos() // 1_000_000


def _reset_after(value: str | None) -> Seconds | None:
    numeric = _number(value)
    if numeric is None or numeric <= 0:
        return None
    return Seconds(max(numeric, 0.001))


def _reset(now: float, value: str | None) -> Seconds | None:
    numeric = _number(value)
    if numeric is None or numeric <= 0:
        return None
    if numeric > 1_000_000_000_000:
        return millis(max(numeric - now, _MIN_MILLIS))
    if numeric > 1_000_000_000:
        return millis(max(numeric * 1000 - now, _MIN_MILLIS))
    return Seconds(max(numeric, 0.001))


class _Inspector:
    """Reads the rate limit headers of responses."""

    __slots__ = ("_names",)

    def __init__(self, names: _HeaderNames) -> None:
        self._names = names

    def remaining(self, headers: Headers) -> float | None:
        value = _number(_header(headers, self._names.remaining))
        return value if value is not None and value >= 0 else None

    def window(self, now: float, headers: Headers) -> Seconds | None:
        after = _reset_after(_header(headers, self._names.reset_after))
        return _clamp(
            after if after is not None else _reset(now, _header(headers, self._names.reset))
        )

    def limits(self, current: _Limits, now: float, headers: Headers, tokens: float) -> _Limits:
        limit = self._limit(current, headers, tokens)
        limit = current.limit if limit is None else limit
        window = self.window(now, headers)
        window = current.window if window is None else window
        if limit == current.limit and window == current.window:
            return current
        return _Limits(limit, window, initial=False)

    def _limit(self, current: _Limits, headers: Headers, tokens: float) -> float | None:
        value = _number(_header(headers, self._names.limit))
        if value is not None and value > 0:
            return value
        remaining = self.remaining(headers)
        if remaining is None:
            return None
        return remaining + tokens if current.initial else max(remaining + tokens, current.limit)

    def retry_after(self, now: float, headers: Headers) -> Seconds | None:
        return retry_after_from_header(_header(headers, self._names.retry_after), now)


def _clamp(hint: Seconds | None) -> Seconds | None:
    """A peer's reset hint, at most an hour, as ``Retry-After`` and the
    adaptive limiter's own are (Effect leaves it unbounded)."""
    return None if hint is None else millis(clamp_adaptive_millis(to_millis(hint)))


def _too_many_requests(error: object) -> HttpClientResponse | None:
    if (
        isinstance(error, HttpClientError)
        and isinstance(error.reason, StatusCodeError)
        and error.reason.response.status == 429
    ):
        return error.reason.response
    return None


type Send = Effect[HttpClientResponse, Any, Any]


@dataclass(frozen=True, slots=True, kw_only=True)
class RateLimitOptions:
    limiter: RateLimiterService
    window: Duration
    limit: float
    key: str | Callable[[HttpClientRequest], str]
    algorithm: Algorithm
    tokens: float | Callable[[HttpClientRequest], float]
    times: int | None
    response_headers: RateLimitHeaders
    disable_response_inspection: bool
    disable_adaptive_learning: bool


class _Limited:
    """The per-key limits and budgets of one rate limited client."""

    __slots__ = ("_budgets", "_initial", "_limits", "inspector", "options")

    def __init__(self, options: RateLimitOptions) -> None:
        self.options = options
        self.inspector = (
            None
            if options.disable_response_inspection
            else _Inspector(_header_names(options.response_headers))
        )
        window = millis(max(to_millis(options.window), _MIN_MILLIS))
        self._initial = _Limits(options.limit, window, initial=True)
        self._limits: dict[str, _Limits] = {}
        self._budgets: dict[str, _Budget] = {}

    def limits_of(self, key: str) -> _Limits:
        return self._limits.setdefault(key, self._initial)

    def budget_of(self, key: str) -> _Budget:
        return self._budgets.setdefault(key, _Budget())

    def observe(  # noqa: PLR0917
        self,
        inspector: _Inspector,
        now: float,
        key: str,
        headers: Headers,
        tokens: float,
        sent: float,
    ) -> None:
        current = self.limits_of(key)
        updated = inspector.limits(current, now, headers, tokens)
        if updated is not current:
            self._limits[key] = updated
        remaining = inspector.remaining(headers)
        budget = self.budget_of(key)
        # Responses to earlier requests carry stale counts.
        if remaining is None or sent <= budget.observed:
            return
        reset_after = inspector.window(now, headers)
        budget.observed = sent
        budget.remaining = remaining
        if reset_after is not None:
            budget.reset_at = now + to_millis(reset_after)

    def send(self, sending: Send, request: HttpClientRequest, retries: int) -> Send:
        return clock_with(lambda clock: self._admit(clock, sending, request, retries))

    def _admit(
        self, clock: ClockService, sending: Send, request: HttpClientRequest, retries: int
    ) -> Send:
        options = self.options
        key = options.key if isinstance(options.key, str) else options.key(request)
        tokens = max(options.tokens(request) if callable(options.tokens) else options.tokens, 1)
        budget = self.budget_of(key)
        now = _now_millis(clock)
        # Requests admitted after the observed one are not in its count.
        if budget.reset_at > now and budget.remaining - (budget.sent - budget.observed) < tokens:
            return sleep(millis(budget.reset_at - now)).flat_map(
                lambda _: self.send(sending, request, retries)
            )
        # Counted at admission, so requests already admitted are sent even
        # if a later response exhausts the budget.
        budget.sent += tokens
        attempt = _Attempt(self, clock, sending, request, key, tokens, budget.sent, retries)
        return attempt.run()


class _Attempt:
    """One admitted request: sent through the limiter, then inspected."""

    __slots__ = (
        "_clock",
        "_current",
        "_key",
        "_limited",
        "_request",
        "_retries",
        "_sending",
        "_sent",
        "_tokens",
    )

    def __init__(  # noqa: PLR0917
        self,
        limited: _Limited,
        clock: ClockService,
        sending: Send,
        request: HttpClientRequest,
        key: str,
        tokens: float,
        sent: float,
        retries: int,
    ) -> None:
        self._limited = limited
        self._clock = clock
        self._sending = sending
        self._request = request
        self._key = key
        self._tokens = tokens
        self._sent = sent
        self._retries = retries
        self._current = limited.limits_of(key)

    @property
    def _can_retry(self) -> bool:
        times = self._limited.options.times
        return times is None or self._retries < times

    def run(self) -> Send:
        options = self._limited.options

        def admitted(delay: Seconds) -> Send:
            if delay == 0:
                return self._paced()
            return sleep(delay).flat_map(lambda _: self._paced())

        return options.limiter.consume(
            key=self._key,
            limit=self._current.limit,
            window=self._current.window,
            algorithm=options.algorithm,
            on_exceeded="delay",
            tokens=self._tokens,
        ).flat_map(lambda result: admitted(result.delay))

    def _paced(self) -> Send:
        options = self._limited.options
        if options.disable_adaptive_learning:
            return self._request_once(None)

        def paced(adaptive: AdaptiveConsumeResult) -> Send:
            if adaptive.delay != 0 and adaptive.phase == "cooldown":
                return sleep(adaptive.delay).flat_map(lambda _: self._paced())
            return self._request_once(adaptive)

        return options.limiter.adaptive_consume(
            key=self._key,
            tokens=self._tokens,
            fallback_limit=self._current.limit,
            fallback_window=self._current.window,
        ).flat_map(paced)

    def _retry(self, retry_after: Seconds | None) -> Send:
        again = self._limited.send(self._sending, self._request, self._retries + 1)
        return again if retry_after is None else sleep(retry_after).flat_map(lambda _: again)

    def _request_once(self, adaptive: AdaptiveConsumeResult | None) -> Send:
        def on_success(response: HttpClientResponse) -> Send:
            def after(retry_after: Seconds | None) -> Send:
                if response.status != 429 or not self._can_retry:
                    return succeed(response)
                return self._retry(retry_after)

            return self._inspect(response, adaptive).flat_map(after)

        def on_failure(error: object) -> Send:
            response = _too_many_requests(error)
            if response is None:
                return fail(error)
            return self._inspect(response, adaptive).flat_map(
                lambda retry_after: self._retry(retry_after) if self._can_retry else fail(error)
            )

        sent = self._sending.match_effect(on_failure=on_failure, on_success=on_success)
        if adaptive is None or adaptive.delay == 0:
            return sent
        return sleep(adaptive.delay).flat_map(lambda _: sent)

    def _inspect(
        self, response: HttpClientResponse, adaptive: AdaptiveConsumeResult | None
    ) -> Effect[Seconds | None, Any]:
        """Apply the response's headers; for a ``429``, the delay before
        retrying (a reported reset wins over ``Retry-After``), reported to
        the adaptive pacing too."""
        inspector = self._limited.inspector
        if inspector is None:
            return succeed(None)
        now = _now_millis(self._clock)
        headers = response.headers
        self._limited.observe(inspector, now, self._key, headers, self._tokens, self._sent)
        if response.status != 429:
            return succeed(None)
        retry_after = inspector.retry_after(now, headers)
        if retry_after is None:
            return succeed(None)
        window = inspector.window(now, headers)
        delay = retry_after if window is None else window
        if adaptive is None:
            return succeed(delay)
        return self._limited.options.limiter.adaptive_feedback(
            key=self._key, epoch=adaptive.epoch, tokens=self._tokens, status=429, retry_after=delay
        ).as_(delay)


def with_rate_limiter(
    options: RateLimitOptions,
) -> Callable[[Send, HttpClientRequest], Send]:
    """The ``transform`` function of ``HttpClientService.with_rate_limiter``."""
    limited = _Limited(options)
    return lambda sending, request: limited.send(sending, request, 0)


__all__ = ["RateLimitHeaders", "RateLimitOptions", "with_rate_limiter"]
