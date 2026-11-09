"""Ports of the ``withRateLimiter`` and ``withCircuitBreaker`` blocks of
Effect's ``http/HttpClient.test.ts`` (the rest is in ``test_http_client.py``).

Each test's docstring is the Effect test title; the classifier table's
rows are the parameters of its test. ``HttpClient.withRateLimiter(opts)``
is the method ``client.with_rate_limiter(**opts)`` and
``withCircuitBreaker`` is ``with_circuit_breaker``; a backend counts its
attempts in a list instead of a ``Ref``. ``Effect.forkChild`` without
``startImmediately`` is ``fork()``; ``RateLimiterTestLayer`` and
``CircuitBreaker.layerStoreMemory()`` are provided by ``_run``.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from datetime import UTC, datetime
from typing import Any

import pytest

import pyfect as fx
from pyfect import clock, layer, testing
from pyfect.cause import Fail, from_reasons
from pyfect.duration import ZERO, Seconds, to_millis
from pyfect.errors import TimeoutException
from pyfect.exit import Exit, Failure, die
from pyfect.exit import fail as exit_fail
from pyfect.exit import succeed as exit_succeed
from pyfect.http import client as c
from pyfect.http import headers as h
from pyfect.http import request as req
from pyfect.http import response as res
from pyfect.http.error import EncodeError, HttpClientError, StatusCodeError, TransportError
from pyfect.persistence import circuit_breaker as cb
from pyfect.persistence import rate_limiter as rl

type Respond = Callable[[int, req.HttpClientRequest], res.HttpClientResponse]
type Body = Callable[[], Generator[fx.Effect[Any, Any, Any], Any]]

_URL = "http://test/"


def _run(body: Body, layer: fx.Layer[Any, Any, Any] = rl.layer_store_memory) -> None:
    testing.run_test(fx.scoped(fx.gen(body)).pipe(fx.provide(layer)))


def _limited(body: Body) -> None:
    """``Effect.provide(RateLimiterTestLayer)``: a ``RateLimiter`` on the
    memory store."""
    _run(body, rl.layer.pipe(layer.provide(rl.layer_store_memory)))


def _client(
    respond: Respond, before: fx.Effect[object] | None = None
) -> tuple[list[int], c.HttpClientService[HttpClientError]]:
    """A backend answering attempt ``n`` (from 1) with ``respond(n, request)``."""
    attempts = [0]

    def send(request: req.HttpClientRequest, *_: object) -> fx.Effect[res.HttpClientResponse]:
        def answer() -> res.HttpClientResponse:
            attempts[0] += 1
            return respond(attempts[0], request)

        return fx.sync(answer)

    return attempts, c.make(send)


def _first(status: int, headers: dict[str, str], then: int = 200) -> Respond:
    """The first attempt gets ``status`` and ``headers``, later ones ``then``."""
    return lambda attempt, request: (
        res.make(request, status=status, headers=headers)
        if attempt == 1
        else res.make(request, status=then)
    )


def _ok() -> Respond:
    return lambda _attempt, request: res.make(request, status=200)


# --- withRateLimiter ------------------------------------------------------------------


def test_delays_requests_above_the_configured_limit() -> None:
    """delays requests above the configured limit"""

    def body():
        limiter = yield from rl.RateLimiter()
        attempts, base = _client(_ok())
        client = base.with_rate_limiter(limiter=limiter, key="test", limit=1, window="1 minute")
        fiber = yield from client.get(_URL).and_then(client.get(_URL)).fork()
        yield from testing.adjust("59 seconds")
        assert attempts[0] == 1
        yield from testing.adjust("1 second")
        yield from fiber.join()
        assert attempts[0] == 2

    _limited(body)


@pytest.mark.parametrize(
    ("headers", "names"),
    [
        pytest.param({"x-ratelimit-limit": "1", "x-ratelimit-reset": "60"}, None, id="default"),
        pytest.param(
            {"x-vendor-limit": "1", "x-vendor-reset": "60"},
            c.RateLimitHeaders(limit="X-Vendor-Limit", reset="X-Vendor-Reset"),
            id="custom",
        ),
    ],
)
def test_updates_limits_from_response_headers(
    headers: dict[str, str], names: c.RateLimitHeaders | None
) -> None:
    """updates limits from response headers by default / updates limits from custom response
    headers"""

    def body():
        limiter = yield from rl.RateLimiter()
        attempts, base = _client(_first(200, headers))
        client = base.with_rate_limiter(
            limiter=limiter, key="test", limit=10, window="1 minute", response_headers=names
        )
        fiber = yield from client.get(_URL).and_then(client.get(_URL)).fork(start_immediately=True)
        yield from testing.adjust("5 seconds")
        assert attempts[0] == 1
        yield from testing.adjust("1 minute")
        yield from fiber.join()
        assert attempts[0] == 2

    _limited(body)


@pytest.mark.parametrize(
    ("headers", "names"),
    [
        pytest.param(
            {"x-ratelimit-remaining": "0", "x-ratelimit-reset-after": "60"}, None, id="default"
        ),
        pytest.param(
            {"x-vendor-remaining": "0", "x-vendor-reset-after": "60"},
            c.RateLimitHeaders(remaining="X-Vendor-Remaining", reset_after="X-Vendor-Reset-After"),
            id="custom",
        ),
    ],
)
def test_inspects_remaining_headers(
    headers: dict[str, str], names: c.RateLimitHeaders | None
) -> None:
    """inspects remaining headers to infer updated limits / inspects custom remaining and
    reset-after headers"""

    def body():
        limiter = yield from rl.RateLimiter()
        attempts, base = _client(_first(200, headers))
        client = base.with_rate_limiter(
            limiter=limiter, key="test", limit=10, window="1 minute", response_headers=names
        )
        fiber = yield from client.get(_URL).and_then(client.get(_URL)).fork(start_immediately=True)
        assert attempts[0] == 1
        yield from testing.adjust("59 seconds")
        assert attempts[0] == 1
        yield from testing.adjust("1 second")
        yield from fiber.join()
        assert attempts[0] == 2

    _limited(body)


def test_tracks_remaining_headers_when_the_limit_header_is_also_present() -> None:
    """tracks remaining headers when the limit header is also present"""

    def body():
        limiter = yield from rl.RateLimiter()
        attempts, base = _client(
            _first(
                200,
                {
                    "ratelimit-limit": "800",
                    "ratelimit-remaining": "1",
                    "ratelimit-reset-after": "60",
                },
            )
        )
        client = base.with_rate_limiter(
            limiter=limiter, key="reported-remaining", limit=800, window="1 minute"
        )
        yield from client.get(_URL)
        yield from client.get(_URL)
        fiber = yield from client.get(_URL).fork(start_immediately=True)
        yield from testing.adjust("59 seconds")
        assert attempts[0] == 2
        yield from testing.adjust("1 second")
        yield from fiber.join()
        assert attempts[0] == 3

    _limited(body)


def test_retries_a_429_at_the_reported_reset_when_remaining_is_exhausted() -> None:
    """retries a 429 at the reported reset when remaining is exhausted"""

    def body():
        limiter = yield from rl.RateLimiter()
        attempts, base = _client(
            _first(
                429,
                {
                    "ratelimit-limit": "800",
                    "ratelimit-remaining": "0",
                    "ratelimit-reset-after": "60",
                },
            )
        )
        client = base.with_rate_limiter(
            limiter=limiter,
            key="reported-429",
            limit=800,
            window="1 minute",
            times=1,
            disable_adaptive_learning=True,
        )
        fiber = yield from client.get(_URL).fork(start_immediately=True)
        yield from testing.adjust("59 seconds")
        assert attempts[0] == 1
        yield from testing.adjust("1 second")
        response = yield from fiber.join()
        assert response.status == 200
        assert attempts[0] == 2

    _limited(body)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param(
            {"ratelimit-remaining": "5", "ratelimit-reset-after": "60"},
            {"ratelimit-remaining": "0", "ratelimit-reset-after": "60"},
            id="ignores stale remaining headers from out-of-order responses",
        ),
        pytest.param(
            {"ratelimit-remaining": "1", "ratelimit-reset-after": "60"},
            {},
            id="counts requests sent after the reporting request against its remaining",
        ),
    ],
)
def test_remaining_counts_with_requests_in_flight(
    first: dict[str, str], second: dict[str, str]
) -> None:
    """ignores stale remaining headers from out-of-order responses / counts requests sent after
    the reporting request against its remaining"""

    def body():
        limiter = yield from rl.RateLimiter()
        release_first = yield from fx.Deferred[None].make()
        attempts = [0]

        def send(request: req.HttpClientRequest, *_: object) -> fx.Effect[res.HttpClientResponse]:
            attempts[0] += 1
            attempt = attempts[0]
            if attempt == 1:
                return release_first.wait().as_(res.make(request, status=200, headers=first))
            return fx.succeed(res.make(request, status=200, headers=second if attempt == 2 else {}))

        client = c.make(send).with_rate_limiter(
            limiter=limiter, key="in-flight", limit=800, window="1 minute"
        )
        fiber_1 = yield from client.get(_URL).fork(start_immediately=True)
        yield from client.get(_URL)
        yield from release_first.succeed(None)
        yield from fiber_1.join()

        fiber = yield from client.get(_URL).fork(start_immediately=True)
        yield from testing.adjust("59 seconds")
        assert attempts[0] == 2
        yield from testing.adjust("1 second")
        yield from fiber.join()
        assert attempts[0] == 3

    _limited(body)


def test_paces_requests_started_while_remaining_is_exhausted_with_the_limiter_after_reset() -> None:
    """paces requests started while remaining is exhausted with the limiter after reset"""

    def body():
        limiter = yield from rl.RateLimiter()
        attempts, base = _client(
            _first(
                200,
                {"ratelimit-limit": "2", "ratelimit-remaining": "0", "ratelimit-reset-after": "60"},
            )
        )
        client = base.with_rate_limiter(
            limiter=limiter,
            key="exhausted-pacing",
            limit=2,
            window="1 minute",
            disable_adaptive_learning=True,
        )
        yield from client.get(_URL)
        fibers = yield from fx.for_each(
            range(3), lambda _: client.get(_URL).fork(start_immediately=True)
        )
        yield from testing.adjust("1 minute")
        assert attempts[0] == 3
        yield from testing.adjust("1 minute")
        yield from fx.Fiber.join_all(fibers)
        assert attempts[0] == 4

    _limited(body)


@pytest.mark.parametrize(
    ("names", "inspect"),
    [
        pytest.param(
            c.RateLimitHeaders(limit="X-Vendor-Limit"),
            True,
            id="uses custom header overrides without falling back to built-in names",
        ),
        pytest.param(None, False, id="can disable response header inspection"),
    ],
)
def test_limit_headers_not_read(names: c.RateLimitHeaders | None, inspect: bool) -> None:
    """uses custom header overrides without falling back to built-in names / can disable
    response header inspection"""

    def body():
        limiter = yield from rl.RateLimiter()
        attempts, base = _client(
            lambda _attempt, request: res.make(
                request,
                status=200,
                headers={"x-ratelimit-limit": "1", "x-ratelimit-reset": "60"},
            )
        )
        client = base.with_rate_limiter(
            limiter=limiter,
            key="test",
            limit=10,
            window="1 minute",
            response_headers=names,
            disable_response_inspection=not inspect,
        )
        yield from client.get(_URL)
        yield from client.get(_URL)
        assert attempts[0] == 2

    _limited(body)


@pytest.mark.parametrize(
    "filter_ok",
    [
        pytest.param(False, id="retries 429 responses through the limiter"),
        pytest.param(True, id="retries HttpClientError 429 failures through the limiter"),
    ],
)
def test_retries_429_through_the_limiter(filter_ok: bool) -> None:
    """retries 429 responses through the limiter / retries HttpClientError 429 failures through
    the limiter"""

    def body():
        limiter = yield from rl.RateLimiter()
        attempts, base = _client(_first(429, {}))
        client = (base.filter_status_ok() if filter_ok else base).with_rate_limiter(
            limiter=limiter,
            key="test",
            limit=1,
            window="1 minute",
            disable_response_inspection=True,
        )
        fiber = yield from client.get(_URL).fork()
        yield from testing.adjust("59 seconds")
        assert attempts[0] == 1
        yield from testing.adjust("1 second")
        response = yield from fiber.join()
        assert response.status == 200
        assert attempts[0] == 2

    _limited(body)


def test_bounds_automatic_429_response_retries() -> None:
    """bounds automatic 429 response retries"""

    def body():
        limiter = yield from rl.RateLimiter()
        attempts, base = _client(lambda _attempt, request: res.make(request, status=429))
        client = base.with_rate_limiter(
            limiter=limiter,
            key="bounded-response",
            limit=100,
            window="1 minute",
            times=2,
            disable_response_inspection=True,
        )
        response = yield from client.get(_URL)
        assert response.status == 429
        assert attempts[0] == 3

    _limited(body)


def test_bounds_automatic_http_client_error_429_retries() -> None:
    """bounds automatic HttpClientError 429 retries"""

    def body():
        limiter = yield from rl.RateLimiter()
        attempts, base = _client(lambda _attempt, request: res.make(request, status=429))
        client = base.filter_status_ok().with_rate_limiter(
            limiter=limiter,
            key="bounded-error",
            limit=100,
            window="1 minute",
            times=2,
            disable_response_inspection=True,
        )
        error = yield from client.get(_URL).flip()
        assert isinstance(error, HttpClientError)
        assert isinstance(error.reason, StatusCodeError)
        assert error.reason.response.status == 429
        assert attempts[0] == 3

    _limited(body)


def test_waits_until_a_retry_after_http_date() -> None:
    """waits until a Retry-After HTTP date"""

    def body():
        now = yield from clock.current_time_millis()
        retry_at = h.format_http_date(datetime.fromtimestamp(now / 1000 + 30, UTC))
        limiter = yield from rl.RateLimiter()
        attempts, base = _client(
            lambda attempt, request: res.make(
                request, status=429 if attempt == 1 else 200, headers={"retry-after": retry_at}
            )
        )
        client = base.with_rate_limiter(
            limiter=limiter,
            key="http-date-retry-after",
            limit=100,
            window="1 minute",
            times=1,
            disable_adaptive_learning=True,
        )
        fiber = yield from client.get(_URL).fork()
        yield from testing.adjust("29 seconds")
        assert attempts[0] == 1
        yield from testing.adjust("1 second")
        response = yield from fiber.join()
        assert response.status == 200
        assert attempts[0] == 2

    _limited(body)


def test_uses_a_custom_retry_after_header() -> None:
    """uses a custom Retry-After header"""

    def body():
        limiter = yield from rl.RateLimiter()
        attempts, base = _client(_first(429, {"x-vendor-retry-after": "10"}))
        client = base.with_rate_limiter(
            limiter=limiter,
            key="custom-retry-after",
            limit=100,
            window="1 minute",
            times=1,
            response_headers=c.RateLimitHeaders(retry_after="X-Vendor-Retry-After"),
            disable_adaptive_learning=True,
        )
        fiber = yield from client.get(_URL).fork(start_immediately=True)
        assert attempts[0] == 1
        yield from testing.adjust("9 seconds")
        assert attempts[0] == 1
        yield from testing.adjust("1 second")
        response = yield from fiber.join()
        assert response.status == 200
        assert attempts[0] == 2

    _limited(body)


def test_applies_adaptive_cooldown_to_requests_delayed_by_the_configured_limiter() -> None:
    """applies adaptive cooldown to requests delayed by the configured limiter"""

    def body():
        limiter = yield from rl.RateLimiter()
        statuses: list[int] = []
        previous: list[float] = []

        def send(request: req.HttpClientRequest, *_: object) -> fx.Effect[res.HttpClientResponse]:
            def answer(now: float) -> res.HttpClientResponse:
                status = 429 if previous and now - previous[-1] < 2_000 else 200
                previous.append(now)
                statuses.append(status)
                headers = {"retry-after": "2"} if status == 429 else {}
                return res.make(request, status=status, headers=headers)

            return clock.current_time_millis().map(answer)

        client = c.make(send).with_rate_limiter(
            limiter=limiter, key="adaptive-delayed", limit=1, window="1 second"
        )
        fiber = yield from fx.all(
            *(client.get(f"http://test/{n}") for n in range(1, 6)), concurrency="unbounded"
        ).fork(start_immediately=True)
        assert len(statuses) == 1
        yield from testing.adjust("1 second")
        assert len(statuses) == 2
        yield from testing.adjust("1 second")
        assert len(statuses) == 2
        yield from testing.adjust("1 second")
        assert statuses == [200, 429, 200, 429]
        yield from testing.adjust("6 seconds")
        yield from fiber.join()
        assert statuses.count(429) == 2

    _limited(body)


@pytest.mark.parametrize(
    "filter_ok",
    [
        pytest.param(False, id="coordinates Retry-After cooldown across clients sharing a store"),
        pytest.param(True, id="applies Retry-After feedback from HttpClientError failures"),
    ],
)
def test_retry_after_cooldown_shared_through_the_store(filter_ok: bool) -> None:
    """coordinates Retry-After cooldown across clients sharing a memory store / applies
    Retry-After feedback from HttpClientError response failures"""

    def body():
        limiter_a = yield from rl.make
        limiter_b = yield from rl.make
        attempts_a, base_a = _client(_first(429, {"retry-after": "10"}))
        attempts_b, base_b = _client(_ok())
        key = "failure" if filter_ok else "shared"
        client_a = (base_a.filter_status_ok() if filter_ok else base_a).with_rate_limiter(
            limiter=limiter_a, key=key, limit=100, window="1 minute"
        )
        client_b = base_b.with_rate_limiter(
            limiter=limiter_b, key=key, limit=100, window="1 minute"
        )
        fiber_a = yield from client_a.get("http://test/a").fork(start_immediately=True)
        assert attempts_a[0] == 1
        fiber_b = yield from client_b.get("http://test/b").fork(start_immediately=True)
        yield from testing.adjust("9 seconds")
        assert attempts_b[0] == 0
        yield from testing.adjust("1 second")
        yield from fiber_a.join()
        yield from fiber_b.join()
        assert attempts_a[0] == 2
        assert attempts_b[0] == 1

    _run(body)


def test_applies_retry_after_feedback_when_automatic_retries_are_disabled() -> None:
    """applies Retry-After feedback when automatic retries are disabled"""

    def body():
        limiter_a = yield from rl.make
        limiter_b = yield from rl.make
        _, base_a = _client(
            lambda _attempt, request: res.make(request, status=429, headers={"retry-after": "10"})
        )
        attempts_b, base_b = _client(_ok())
        client_a = base_a.with_rate_limiter(
            limiter=limiter_a, key="terminal-feedback", limit=100, window="1 minute", times=0
        )
        client_b = base_b.with_rate_limiter(
            limiter=limiter_b, key="terminal-feedback", limit=100, window="1 minute"
        )
        response = yield from client_a.get("http://test/a")
        assert response.status == 429
        fiber_b = yield from client_b.get("http://test/b").fork(start_immediately=True)
        yield from testing.adjust("9 seconds")
        assert attempts_b[0] == 0
        yield from testing.adjust("1 second")
        yield from fiber_b.join()
        assert attempts_b[0] == 1

    _run(body)


def test_learns_adaptive_pacing_from_retry_after_feedback() -> None:
    """learns adaptive pacing from Retry-After feedback"""

    def body():
        limiter = yield from rl.make
        attempts, base = _client(
            lambda attempt, request: (
                res.make(request, status=429, headers={"retry-after": "10"})
                if attempt in {1, 4}
                else res.make(request, status=200)
            )
        )
        client = base.with_rate_limiter(
            limiter=limiter, key="learned", limit=100, window="1 minute"
        )

        first = yield from client.get(_URL).fork(start_immediately=True)
        assert attempts[0] == 1
        yield from testing.adjust("10 seconds")
        yield from first.join()
        assert attempts[0] == 2

        yield from client.get(_URL)
        assert attempts[0] == 3

        learning = yield from client.get(_URL).fork(start_immediately=True)
        assert attempts[0] == 4
        yield from testing.adjust("10 seconds")
        yield from learning.join()
        assert attempts[0] == 5

        paced = yield from client.get(_URL).and_then(client.get(_URL)).fork(start_immediately=True)
        assert attempts[0] == 6
        yield from testing.adjust("9 seconds")
        assert attempts[0] == 6
        yield from testing.adjust("1 second")
        yield from paced.join()
        assert attempts[0] == 7

    _run(body)


def test_does_not_send_adaptive_feedback_when_response_inspection_is_disabled() -> None:
    """does not send adaptive feedback when response inspection is disabled"""

    def body():
        disabled_limiter = yield from rl.make
        enabled_limiter = yield from rl.make
        disabled_attempts, disabled_base = _client(_first(429, {"retry-after": "10"}))
        enabled_attempts, enabled_base = _client(_ok())
        disabled = disabled_base.with_rate_limiter(
            limiter=disabled_limiter,
            key="disabled",
            limit=100,
            window="1 minute",
            disable_response_inspection=True,
        )
        enabled = enabled_base.with_rate_limiter(
            limiter=enabled_limiter, key="disabled", limit=100, window="1 minute"
        )
        response = yield from disabled.get("http://test/disabled")
        assert response.status == 200
        assert disabled_attempts[0] == 2
        fiber = yield from enabled.get("http://test/enabled").fork(start_immediately=True)
        assert enabled_attempts[0] == 1
        yield from fiber.join()

    _run(body)


def test_can_disable_adaptive_learning_without_disabling_response_inspection() -> None:
    """can disable adaptive learning without disabling response inspection"""

    def body():
        disabled_limiter = yield from rl.make
        enabled_limiter = yield from rl.make
        disabled_attempts, disabled_base = _client(_first(429, {"retry-after": "10"}))
        enabled_attempts, enabled_base = _client(_ok())
        disabled_client = disabled_base.with_rate_limiter(
            limiter=disabled_limiter,
            key="adaptive-disabled",
            limit=100,
            window="1 minute",
            disable_adaptive_learning=True,
        )
        enabled_client = enabled_base.with_rate_limiter(
            limiter=enabled_limiter, key="adaptive-disabled", limit=100, window="1 minute"
        )
        disabled = yield from disabled_client.get("http://test/disabled").fork(
            start_immediately=True
        )
        assert disabled_attempts[0] == 1
        enabled = yield from enabled_client.get("http://test/enabled").fork(start_immediately=True)
        assert enabled_attempts[0] == 1
        yield from enabled.join()
        yield from testing.adjust("9 seconds")
        assert disabled_attempts[0] == 1
        yield from testing.adjust("1 second")
        yield from disabled.join()
        assert disabled_attempts[0] == 2

    _run(body)


def test_keeps_adaptive_retry_after_state_isolated_by_resolved_key() -> None:
    """keeps adaptive Retry-After state isolated by resolved key"""

    def body():
        limiter = yield from rl.make
        attempts_a, base_a = _client(_first(429, {"retry-after": "10"}))
        attempts_b, base_b = _client(_ok())
        client_a = base_a.with_rate_limiter(limiter=limiter, key="a", limit=100, window="1 minute")
        client_b = base_b.with_rate_limiter(limiter=limiter, key="b", limit=100, window="1 minute")
        fiber_a = yield from client_a.get("http://test/a").fork(start_immediately=True)
        assert attempts_a[0] == 1
        fiber_b = yield from client_b.get("http://test/b").fork(start_immediately=True)
        assert attempts_b[0] == 1
        yield from fiber_b.join()
        yield from testing.adjust("10 seconds")
        yield from fiber_a.join()
        assert attempts_a[0] == 2

    _run(body)


def test_prefers_explicit_rate_limit_reset_headers_over_adaptive_retry_after_feedback() -> None:
    """prefers explicit RateLimit reset headers over adaptive Retry-After feedback"""

    def body():
        limiter = yield from rl.make
        attempts, base = _client(
            _first(
                429,
                {"retry-after": "60", "x-ratelimit-limit": "1", "x-ratelimit-reset-after": "1"},
            )
        )
        client = base.with_rate_limiter(
            limiter=limiter, key="explicit", limit=100, window="1 minute"
        )
        retry = yield from client.get(_URL).fork(start_immediately=True)
        assert attempts[0] == 1
        yield from testing.adjust("999 millis")
        assert attempts[0] == 1
        yield from testing.adjust("1 millis")
        yield from retry.join()
        assert attempts[0] == 2

        following = yield from client.get(_URL).fork(start_immediately=True)
        yield from testing.adjust("999 millis")
        assert attempts[0] == 2
        yield from testing.adjust("1 millis")
        yield from following.join()
        assert attempts[0] == 3

    _run(body)


# --- withCircuitBreaker ---------------------------------------------------------------

_REQUEST = req.get("http://test/")


def _response(status: int, headers: dict[str, str] | None = None) -> res.HttpClientResponse:
    return res.make(_REQUEST, status=status, headers=headers or {})


def _status_error(status: int, headers: dict[str, str] | None = None) -> HttpClientError:
    return HttpClientError(
        reason=StatusCodeError(request=_REQUEST, response=_response(status, headers))
    )


_TRANSPORT_ERROR = HttpClientError(reason=TransportError(request=_REQUEST))
_ENCODE_ERROR = HttpClientError(reason=EncodeError(request=_REQUEST))


def _failures(*errors: object) -> Exit[res.HttpClientResponse, object]:
    return Failure(from_reasons(Fail(error) for error in errors))


def _http_date(now_millis: float) -> str:
    return h.format_http_date(datetime.fromtimestamp((now_millis + 30_000) / 1000, UTC))


_CLASSIFIER_CASES: list[
    tuple[str, Callable[[float], Exit[res.HttpClientResponse, object]], str, float | None]
] = [
    (
        "a returned 503 with Retry-After seconds",
        lambda _: exit_succeed(_response(503, {"retry-after": "5"})),
        "Failure",
        5_000,
    ),
    (
        "a wrapped 503 with a Retry-After HTTP date",
        lambda now: exit_fail(_status_error(503, {"retry-after": _http_date(now)})),
        "Failure",
        30_000,
    ),
    ("a TransportError", lambda _: exit_fail(_TRANSPORT_ERROR), "Failure", None),
    ("a TimeoutError", lambda _: exit_fail(TimeoutException(Seconds(1))), "Failure", None),
    ("a wrapped 404", lambda _: exit_fail(_status_error(404)), "Success", None),
    (
        "a returned 429",
        lambda _: exit_succeed(_response(429, {"retry-after": "5"})),
        "Ignored",
        None,
    ),
    ("an EncodeError", lambda _: exit_fail(_ENCODE_ERROR), "Ignored", None),
    ("a defect", lambda _: die(RuntimeError("caller bug")), "Ignored", None),
    (
        "an unknown typed error",
        lambda _: exit_fail(
            rl.RateLimiterError(reason=rl.RateLimitStoreError(message="store unavailable"))
        ),
        "Ignored",
        None,
    ),
    (
        "a success beside an ignored error",
        lambda _: _failures(_ENCODE_ERROR, _status_error(404)),
        "Success",
        None,
    ),
    (
        "failures beside a success and an ignored error",
        lambda _: _failures(
            _status_error(404),
            _status_error(503, {"retry-after": "5"}),
            _status_error(429, {"retry-after": "60"}),
            _status_error(502, {"retry-after": "10"}),
        ),
        "Failure",
        10_000,
    ),
]


@pytest.mark.parametrize(
    ("exit", "outcome", "retry_after_millis"),
    [pytest.param(*case[1:], id=case[0]) for case in _CLASSIFIER_CASES],
)
@testing.effect
def test_circuit_breaker_classifier(
    exit: Callable[[float], Exit[res.HttpClientResponse, object]],
    outcome: str,
    retry_after_millis: float | None,
):
    """circuitBreakerClassifier classifies $name as $outcome"""
    now = yield from clock.current_time_millis()
    classified = yield from c.circuit_breaker_classifier(exit(now))
    retry_after = classified.retry_after if isinstance(classified, cb.FailureOutcome) else None
    assert (classified.kind, None if retry_after is None else to_millis(retry_after)) == (
        outcome,
        retry_after_millis,
    )


def _unreachable(*_: object) -> fx.Effect[res.HttpClientResponse]:
    return fx.die(RuntimeError("unreachable"))


@testing.effect
def test_retry_transient_never_retries_a_circuit_breaker_error():
    """retryTransient never retries a CircuitBreakerError"""
    reasons: list[cb.CircuitBreakerErrorReason] = [
        cb.CircuitOpen(key="test", retry_after=ZERO),
        cb.CircuitHalfOpen(key="test"),
        cb.CircuitBreakerStoreError(message="store unavailable", cause=_TRANSPORT_ERROR),
    ]
    for reason in reasons:
        attempts = [0]

        def rejected(
            _sending: object,
            _request: object,
            reason: cb.CircuitBreakerErrorReason = reason,
            attempts: list[int] = attempts,
        ) -> fx.Effect[res.HttpClientResponse, cb.CircuitBreakerError]:
            def count() -> None:
                attempts[0] += 1

            return fx.sync(count).and_then(fx.fail(cb.CircuitBreakerError(reason=reason)))

        client = c.make(_unreachable).transform(rejected).retry_transient(times=2)
        error = yield from client.get(_URL).flip()
        assert isinstance(error, cb.CircuitBreakerError)
        assert attempts[0] == 1


def test_keys_circuits_by_request_origin_by_default() -> None:
    """keys circuits by request origin by default"""

    def body():
        hosts: list[str] = []

        def send(
            request: req.HttpClientRequest, url: Any, *_: object
        ) -> fx.Effect[res.HttpClientResponse]:
            def answer() -> res.HttpClientResponse:
                hosts.append(url.netloc)
                status = 503 if url.hostname == "down.test" else 200
                return res.make(request, status=status)

            return fx.sync(answer)

        breaker = yield from cb.make(trip_policy=cb.consecutive(1), open_duration="1 minute")
        client = c.make(send).with_circuit_breaker(breaker=breaker)
        assert (yield from client.get("http://down.test:8080/a")).status == 503
        error = yield from client.get("http://down.test:8080/b?q=1").flip()
        assert isinstance(error, cb.CircuitBreakerError)
        assert isinstance(error.reason, cb.CircuitOpen)
        assert error.reason.key == "http://down.test:8080"
        assert (yield from client.get("http://up.test/")).status == 200
        assert hosts == ["down.test:8080", "up.test"]

    _run(body, cb.layer_store_memory())
