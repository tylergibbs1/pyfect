"""``RateLimiter``: limits how often a key may be used."""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from typing import Any, Final, Literal, Never, Protocol, overload

from pyfect import _js as js
from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.clock import sleep as clock_sleep
from pyfect.context import Tag
from pyfect.duration import Duration, from_input_unsafe, infinity, to_millis, zero
from pyfect.duration import Input as DurationInput
from pyfect.effect import fail, gen, succeed
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.persistence._seconds import divide_millis, millis
from pyfect.persistence.rate_limiter._errors import RateLimiterError, RateLimitExceeded
from pyfect.persistence.rate_limiter._store import (
    AdaptiveConsumeResult,
    RateLimiterStore,
    RateLimiterStoreService,
)

type Algorithm = Literal["fixed-window", "token-bucket"]
"""``"fixed-window"``: ``limit`` tokens per ``window``, each token
reserving ``window / limit`` of it. ``"token-bucket"``: a bucket of
``limit`` tokens refilled one every ``window / limit``."""

type OnExceeded = Literal["delay", "fail"]
"""Over the limit, ``"fail"`` with ``RateLimitExceeded`` (charging
nothing), or reserve the tokens and give the ``delay`` to wait first."""


@dataclass(frozen=True, slots=True)
class ConsumeResult:
    """What a consume charged: wait ``delay`` before going on; ``remaining``
    tokens are left of ``limit`` (below zero for queued reservations), and
    the key is back to full after ``reset_after``. A whole ``remaining`` is
    an ``int`` whatever the store computed it with, as Effect's stores all
    give the same JavaScript number."""

    delay: Duration
    limit: float
    remaining: float
    reset_after: Duration

    def __post_init__(self) -> None:
        if isinstance(self.remaining, float) and self.remaining.is_integer():
            object.__setattr__(self, "remaining", int(self.remaining))


_FOREVER: Final = infinity


def _exceeded(key: str, retry_after: Duration, limit: float) -> Effect[Never, RateLimiterError]:
    return fail(
        RateLimiterError(
            reason=RateLimitExceeded(key=key, retry_after=retry_after, limit=limit, remaining=0)
        )
    )


class RateLimiterService:
    """Limits how often each key may be used."""

    __slots__ = ("_store",)

    def __init__(self, store: RateLimiterStoreService) -> None:
        self._store = store

    def consume(
        self,
        *,
        key: str,
        limit: float,
        window: DurationInput,
        algorithm: Algorithm = "fixed-window",
        on_exceeded: OnExceeded = "fail",
        tokens: float = 1,
    ) -> Effect[ConsumeResult, RateLimiterError]:
        """Charge ``tokens`` (default 1) to ``key``, allowed ``limit`` per
        ``window`` (at least a millisecond) by ``algorithm``. Over the
        limit, ``on_exceeded`` says whether to fail or to reserve and
        report a delay. A ``"fail"`` request for more than ``limit`` fails
        at once, with the whole window to wait. A ``limit`` of zero or less
        admits no positive request: ``"fail"`` rejects it and ``"delay"``
        gives an infinite delay, without touching the store."""
        window_millis = max(to_millis(window), 1.0)
        exceeded = tokens > limit
        if on_exceeded == "fail" and exceeded:
            return _exceeded(key, millis(window_millis), limit)
        if limit <= 0:
            # A limit that never refills: answered without the store.
            wait = _FOREVER if exceeded else zero
            return succeed(ConsumeResult(wait, limit, limit - tokens, wait))
        refill = divide_millis(window_millis, limit)
        if algorithm == "fixed-window":
            return self._fixed_window(
                key=key,
                limit=limit,
                tokens=tokens,
                on_exceeded=on_exceeded,
                window_millis=window_millis,
                refill=refill,
            )
        return self._token_bucket(key, limit, tokens, on_exceeded, refill)

    def _fixed_window(
        self,
        *,
        key: str,
        limit: float,
        tokens: float,
        on_exceeded: OnExceeded,
        window_millis: float,
        refill: float,
    ) -> Effect[ConsumeResult, RateLimiterError]:
        def result(counted: tuple[float, float]) -> Effect[ConsumeResult, RateLimiterError]:
            count, ttl = counted
            if on_exceeded == "fail":
                remaining = limit - count
                if remaining < 0:
                    return _exceeded(key, millis(ttl), limit)
                return succeed(ConsumeResult(zero, limit, remaining, millis(ttl)))
            elapsed = count * refill - ttl
            window_number = js.floor(js.divide(count - 1, limit))
            wait = window_number * window_millis - elapsed
            delay = zero if wait <= 0 else millis(wait)
            return succeed(ConsumeResult(delay, limit, limit - count, millis(ttl)))

        return self._store.fixed_window(
            key=key,
            tokens=tokens,
            refill_rate_millis=refill,
            limit=limit if on_exceeded == "fail" else None,
        ).flat_map(result)

    def _token_bucket(
        self, key: str, limit: float, tokens: float, on_exceeded: OnExceeded, refill: float
    ) -> Effect[ConsumeResult, RateLimiterError]:
        def result(taken: tuple[float, float]) -> Effect[ConsumeResult, RateLimiterError]:
            remaining, elapsed = taken
            delay = millis(max(0, js.ceil(-remaining) * refill - elapsed))
            reset_after = millis(max(0, js.ceil(limit - remaining) * refill - elapsed))
            if on_exceeded == "fail" and remaining < 0:
                return _exceeded(key, delay, limit)
            return succeed(ConsumeResult(delay, limit, remaining, reset_after))

        return self._store.token_bucket(
            key=key,
            tokens=tokens,
            limit=limit,
            refill_rate_millis=refill,
            allow_overflow=on_exceeded == "delay",
        ).flat_map(result)

    def adaptive_consume(
        self, *, key: str, tokens: float, fallback_limit: float, fallback_window: DurationInput
    ) -> Effect[AdaptiveConsumeResult, RateLimiterError]:
        """Ask to send ``tokens`` to a server that limits ``key`` by
        ``429`` responses: no delay until one comes, then wait out its
        ``Retry-After``, learn how much the server accepts and pace to it.
        Report each response with ``adaptive_feedback`` and the ``epoch``
        given here."""
        return self._store.adaptive_consume(
            key=key,
            tokens=tokens,
            fallback_limit=fallback_limit,
            fallback_window=from_input_unsafe(fallback_window),
        )

    def adaptive_feedback(
        self,
        *,
        key: str,
        epoch: int,
        tokens: float,
        status: int,
        retry_after: DurationInput | None,
    ) -> Effect[None, RateLimiterError]:
        """Report the response to an ``adaptive_consume``: only a ``429``
        with a ``retry_after`` changes anything, and only for the epoch it
        was sent in."""
        return self._store.adaptive_feedback(
            key=key,
            epoch=epoch,
            tokens=tokens,
            status=status,
            retry_after=None if retry_after is None else from_input_unsafe(retry_after),
        )


class RateLimiter(Tag[RateLimiterService], key="~effect/persistence/RateLimiter"):
    """Limits how often each key may be used."""


def _build() -> Generator[Effect[Any, Never, RateLimiterStore], Any, RateLimiterService]:
    store = yield from RateLimiterStore()
    return RateLimiterService(store)


make: Effect[RateLimiterService, Never, RateLimiterStore] = gen(_build)
"""A ``RateLimiter`` on the ``RateLimiterStore``."""

layer: Layer[RateLimiter, Never, RateLimiterStore] = layer_effect(RateLimiter, make)
"""Provides ``RateLimiter`` on the ``RateLimiterStore``."""


class Limit:
    """Runs an effect after the consume it was made with, waiting the
    consume's delay first; an exceeded ``"fail"`` consume fails instead."""

    __slots__ = ("_consume",)

    def __init__(self, consume: Effect[ConsumeResult, RateLimiterError]) -> None:
        self._consume = consume

    def __call__[A, E, R](self, effect: Effect[A, E, R]) -> Effect[A, E | RateLimiterError, R]:
        require_effect(effect, "effect")

        def run(result: ConsumeResult) -> Effect[A, E, R]:
            return effect if result.delay == 0 else effect.delay(result.delay)

        return self._consume.flat_map(run)


class WithRateLimiter:
    """``with_rate_limiter(key=, limit=, window=, ...)`` gives a function
    for ``.pipe`` that runs an effect under that consume (its options are
    ``RateLimiterService.consume``'s)."""

    __slots__ = ("_limiter",)

    def __init__(self, limiter: RateLimiterService) -> None:
        self._limiter = limiter

    def __call__(
        self,
        *,
        key: str,
        limit: float,
        window: DurationInput,
        algorithm: Algorithm = "fixed-window",
        on_exceeded: OnExceeded = "fail",
        tokens: float = 1,
    ) -> Limit:
        return Limit(
            self._limiter.consume(
                key=key,
                limit=limit,
                window=window,
                algorithm=algorithm,
                on_exceeded=on_exceeded,
                tokens=tokens,
            )
        )


def _with_limiter() -> Generator[Effect[Any, Never, RateLimiter], Any, WithRateLimiter]:
    limiter = yield from RateLimiter()
    return WithRateLimiter(limiter)


make_with_rate_limiter: Effect[WithRateLimiter, Never, RateLimiter] = gen(_with_limiter)
"""The ``RateLimiter``'s ``with_rate_limiter`` function::

    with_rate_limiter = yield from rate_limiter.make_with_rate_limiter
    yield from call_api.pipe(with_rate_limiter(key="api", limit=10, window="1 minute"))
"""


class Sleep(Protocol):
    """``sleep(limiter)``: consumes in ``"delay"`` mode and sleeps the
    delay."""

    def __call__(
        self,
        *,
        key: str,
        limit: float,
        window: DurationInput,
        algorithm: Algorithm = "fixed-window",
        tokens: float = 1,
    ) -> Effect[ConsumeResult, RateLimiterError]: ...


@overload
def sleep(limiter: RateLimiterService, /) -> Sleep: ...
@overload
def sleep(
    limiter: RateLimiterService,
    /,
    *,
    key: str,
    limit: float,
    window: DurationInput,
    algorithm: Algorithm = "fixed-window",
    tokens: float = 1,
) -> Effect[ConsumeResult, RateLimiterError]: ...
def sleep(
    limiter: RateLimiterService,
    /,
    *,
    key: str | None = None,
    limit: float = 0,
    window: DurationInput = "0 millis",
    algorithm: Algorithm = "fixed-window",
    tokens: float = 1,
) -> Sleep | Effect[ConsumeResult, RateLimiterError]:
    """Consume in ``"delay"`` mode and sleep the delay, so the call goes on
    once it is under the limit; without options, the function doing that
    for ``limiter``."""
    if key is None:

        def partial(
            *,
            key: str,
            limit: float,
            window: DurationInput,
            algorithm: Algorithm = "fixed-window",
            tokens: float = 1,
        ) -> Effect[ConsumeResult, RateLimiterError]:
            return sleep(
                limiter, key=key, limit=limit, window=window, algorithm=algorithm, tokens=tokens
            )

        return partial

    def wait(result: ConsumeResult) -> Effect[ConsumeResult]:
        return succeed(result) if result.delay == 0 else clock_sleep(result.delay).as_(result)

    return limiter.consume(
        key=key,
        limit=limit,
        window=window,
        algorithm=algorithm,
        on_exceeded="delay",
        tokens=tokens,
    ).flat_map(wait)
