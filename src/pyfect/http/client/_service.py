"""The client value and its combinators (Effect's ``HttpClient.With``)."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal, Never, Unpack, final, overload

from pyfect._tags import Tags
from pyfect.context import Tag
from pyfect.effect import Effect, fail, succeed
from pyfect.http import request as _request
from pyfect.http import response as _response
from pyfect.http.cookies import Cookie
from pyfect.http.error import HttpClientError
from pyfect.http.request import HttpClientRequest, RequestOptions, UrlInput
from pyfect.http.response import HttpClientResponse

if TYPE_CHECKING:
    from pyfect.duration import Input as DurationInput
    from pyfect.http.client._rate_limit import RateLimitHeaders
    from pyfect.persistence.circuit_breaker import (
        CircuitBreakerError,
        CircuitBreakerService,
        Classifier,
    )
    from pyfect.persistence.rate_limiter import Algorithm, RateLimiterError, RateLimiterService
    from pyfect.ref import Ref
    from pyfect.schedule import Schedule
    from pyfect.scope import Scope

type Preprocess[E, R] = Callable[[HttpClientRequest], Effect[HttpClientRequest, E, R]]
type Postprocess[E, R] = Callable[
    [Effect[HttpClientRequest, E, R]], Effect[HttpClientResponse, E, R]
]

type RetryOn = Literal["errors-only", "response-only", "errors-and-responses"]


@final
class HttpClientService[E, R = Never]:
    """A client failing with ``E`` and needing ``R``: ``preprocess`` turns
    a request into the request to send, ``postprocess`` sends it.

    The combinators are methods, but for ``catch_tag`` (which removes
    some types from the errors) and ``transform_response``: functions
    used with ``.pipe``."""

    __slots__ = ("_postprocess", "_preprocess")

    def __init__(
        self,
        postprocess: Callable[
            [Effect[HttpClientRequest, Any, Any]], Effect[HttpClientResponse, E, R]
        ],
        preprocess: Callable[[HttpClientRequest], Effect[HttpClientRequest, Any, Any]],
    ) -> None:
        self._postprocess = postprocess
        self._preprocess = preprocess

    def __repr__(self) -> str:
        return "HttpClient()"

    @property
    def preprocess(self) -> Callable[[HttpClientRequest], Effect[HttpClientRequest, Any, Any]]:
        """The function turning each request into the request to send
        (adding headers, a base URL and so on); ``execute`` runs it before
        ``postprocess``."""
        return self._preprocess

    @property
    def postprocess(
        self,
    ) -> Callable[[Effect[HttpClientRequest, Any, Any]], Effect[HttpClientResponse, E, R]]:
        """The function sending the preprocessed request (an effect
        producing it) and giving the response, failing with ``E``."""
        return self._postprocess

    def pipe[B](self, f: Callable[[HttpClientService[E, R]], B], /) -> B:
        """``f(self)``: applies a curried combinator such as
        ``catch_tag`` or ``transform_response``."""
        return f(self)

    def execute(self, request: HttpClientRequest) -> Effect[HttpClientResponse, E, R]:
        """Sends ``request`` through ``preprocess`` and ``postprocess``
        and succeeds with the response, whatever its status (filter it with
        ``filter_status_ok``). Fails with ``E`` (``HttpClientError`` for the
        ``HttpClient`` service) when the request cannot be built or sent."""
        return self._postprocess(self._preprocess(request))

    def get(
        self, url: UrlInput, **options: Unpack[RequestOptions]
    ) -> Effect[HttpClientResponse, E, R]:
        """``execute`` of a ``GET`` request to ``url``, built with
        ``options`` (headers, URL params, body, ...)."""
        return self.execute(_request.get(url, **options))

    def post(
        self, url: UrlInput, **options: Unpack[RequestOptions]
    ) -> Effect[HttpClientResponse, E, R]:
        """``execute`` of a ``POST`` request to ``url``, built with
        ``options`` (headers, URL params, body, ...)."""
        return self.execute(_request.post(url, **options))

    def put(
        self, url: UrlInput, **options: Unpack[RequestOptions]
    ) -> Effect[HttpClientResponse, E, R]:
        """``execute`` of a ``PUT`` request to ``url``, built with
        ``options`` (headers, URL params, body, ...)."""
        return self.execute(_request.put(url, **options))

    def patch(
        self, url: UrlInput, **options: Unpack[RequestOptions]
    ) -> Effect[HttpClientResponse, E, R]:
        """``execute`` of a ``PATCH`` request to ``url``, built with
        ``options`` (headers, URL params, body, ...)."""
        return self.execute(_request.patch(url, **options))

    def delete(
        self, url: UrlInput, **options: Unpack[RequestOptions]
    ) -> Effect[HttpClientResponse, E, R]:
        """``execute`` of a ``DELETE`` request to ``url``, built with
        ``options`` (headers, URL params, body, ...)."""
        return self.execute(_request.delete(url, **options))

    def head(
        self, url: UrlInput, **options: Unpack[RequestOptions]
    ) -> Effect[HttpClientResponse, E, R]:
        """``execute`` of a ``HEAD`` request to ``url``, built with
        ``options`` (headers, URL params, body, ...)."""
        return self.execute(_request.head(url, **options))

    def options(
        self, url: UrlInput, **options: Unpack[RequestOptions]
    ) -> Effect[HttpClientResponse, E, R]:
        """``execute`` of a ``OPTIONS`` request to ``url``, built with
        ``options`` (headers, URL params, body, ...)."""
        return self.execute(_request.options(url, **options))

    def query(
        self, url: UrlInput, **options: Unpack[RequestOptions]
    ) -> Effect[HttpClientResponse, E, R]:
        """``execute`` of a ``QUERY`` request to ``url``, built with
        ``options`` (headers, URL params, body, ...)."""
        return self.execute(_request.query(url, **options))

    def transform[E1 = Never, R1 = Never](
        self,
        f: Callable[
            [Effect[HttpClientResponse, E, R], HttpClientRequest],
            Effect[HttpClientResponse, E1, R1],
        ],
    ) -> HttpClientService[E | E1, R | R1]:
        """Wrap sending each request: ``f(sending, request)``."""
        post = self._postprocess
        return HttpClientService(
            lambda requests: requests.flat_map(lambda request: f(post(succeed(request)), request)),
            self._preprocess,
        )

    def _on_response[E1, R1](
        self, f: Callable[[Effect[HttpClientResponse, E, R]], Effect[HttpClientResponse, E1, R1]]
    ) -> HttpClientService[E1, R1]:
        post = self._postprocess
        return HttpClientService(lambda requests: f(post(requests)), self._preprocess)

    def filter_or_else[E2 = Never, R2 = Never](
        self,
        predicate: Callable[[HttpClientResponse], bool],
        or_else: Callable[[HttpClientResponse], Effect[HttpClientResponse, E2, R2]],
    ) -> HttpClientService[E | E2, R | R2]:
        """This client, replacing each response that fails
        ``predicate`` with the effect ``or_else(response)``."""
        return self._on_response(lambda eff: eff.filter_or_else(predicate, or_else))

    def filter_or_fail[E2](
        self,
        predicate: Callable[[HttpClientResponse], bool],
        or_fail_with: Callable[[HttpClientResponse], E2],
    ) -> HttpClientService[E | E2, R]:
        """This client, failing with ``or_fail_with(response)`` for each
        response that fails ``predicate``."""
        return self._on_response(lambda eff: eff.filter_or_fail(predicate, or_fail_with))

    def filter_status(self, f: Callable[[int], bool]) -> HttpClientService[E | HttpClientError, R]:
        """Fail with a ``StatusCodeError`` unless ``f(status)``."""
        check = _response.filter_status(f)
        return self._on_response(lambda eff: eff.flat_map(check))

    def filter_status_ok(self) -> HttpClientService[E | HttpClientError, R]:
        """Fail with a ``StatusCodeError`` unless the status is 2xx."""
        return self._on_response(lambda eff: eff.flat_map(_response.filter_status_ok))

    def map_request(
        self, f: Callable[[HttpClientRequest], HttpClientRequest]
    ) -> HttpClientService[E, R]:
        """Change each request after the client's own preprocessing."""
        pre = self._preprocess
        return HttpClientService(self._postprocess, lambda request: pre(request).map(f))

    def map_request_effect[E2 = Never, R2 = Never](
        self, f: Callable[[HttpClientRequest], Effect[HttpClientRequest, E2, R2]]
    ) -> HttpClientService[E | E2, R | R2]:
        """Change each request with the effect ``f`` after the client's
        own preprocessing; ``f``'s failure fails the request."""
        pre = self._preprocess
        post: Any = self._postprocess
        return HttpClientService(post, lambda request: pre(request).flat_map(f))

    def map_request_input(
        self, f: Callable[[HttpClientRequest], HttpClientRequest]
    ) -> HttpClientService[E, R]:
        """Change each request before the client's own preprocessing."""
        pre = self._preprocess
        return HttpClientService(self._postprocess, lambda request: pre(f(request)))

    def map_request_input_effect[E2 = Never, R2 = Never](
        self, f: Callable[[HttpClientRequest], Effect[HttpClientRequest, E2, R2]]
    ) -> HttpClientService[E | E2, R | R2]:
        """Change each request with the effect ``f`` before the
        client's own preprocessing; ``f``'s failure fails the request."""
        pre = self._preprocess
        post: Any = self._postprocess
        return HttpClientService(post, lambda request: f(request).flat_map(pre))

    def tap_request[E2 = Never, R2 = Never](
        self, f: Callable[[HttpClientRequest], Effect[object, E2, R2]]
    ) -> HttpClientService[E | E2, R | R2]:
        """Run ``f`` on each preprocessed request before it is sent,
        keeping the request; ``f``'s failure fails the request."""
        pre = self._preprocess
        post: Any = self._postprocess
        return HttpClientService(post, lambda request: pre(request).tap(f))

    def tap[E2 = Never, R2 = Never](
        self, f: Callable[[HttpClientResponse], Effect[object, E2, R2]]
    ) -> HttpClientService[E | E2, R | R2]:
        """Run ``f`` on each response, keeping the response; ``f``'s
        failure fails the request."""
        return self._on_response(lambda eff: eff.tap(f))

    def tap_error[E2 = Never, R2 = Never](
        self, f: Callable[[E], Effect[object, E2, R2]]
    ) -> HttpClientService[E | E2, R | R2]:
        """Run ``f`` on each typed failure, keeping the failure;
        ``f``'s own failure replaces it."""
        return self._on_response(lambda eff: eff.tap_error(f))

    def catch_all[E2 = Never, R2 = Never](
        self, f: Callable[[E], Effect[HttpClientResponse, E2, R2]]
    ) -> HttpClientService[E2, R | R2]:
        """Recover from every typed failure with ``f``."""
        return self._on_response(lambda eff: eff.catch_all(f))

    @overload
    def retry[EE = Never, RR = Never](
        self, policy: Schedule[object, E, EE, RR], /
    ) -> HttpClientService[E | EE, R | RR]: ...
    @overload
    def retry[EE = Never, RR = Never](
        self,
        /,
        *,
        schedule: Schedule[object, E, EE, RR] | None = None,
        times: int | None = None,
        while_: Callable[[E], bool | Effect[bool, EE, RR]] | None = None,
        until: Callable[[E], bool | Effect[bool, EE, RR]] | None = None,
    ) -> HttpClientService[E | EE, R | RR]: ...
    def retry(
        self,
        policy: Schedule[Any, Any, Any, Any] | None = None,
        /,
        *,
        schedule: Schedule[Any, Any, Any, Any] | None = None,
        times: int | None = None,
        while_: Callable[[Any], Any] | None = None,
        until: Callable[[Any], Any] | None = None,
    ) -> HttpClientService[Any, Any]:
        """Retry sending on typed failure (``Effect.retry``)."""
        if policy is not None:
            return self._on_response(lambda eff: eff.retry(policy))
        return self._on_response(
            lambda eff: eff.retry(schedule=schedule, times=times, while_=while_, until=until)
        )

    @overload
    def retry_transient[ES = Never, RS = Never](
        self, schedule: Schedule[object, Any, ES, RS], /
    ) -> HttpClientService[E | ES, R | RS]: ...
    @overload
    def retry_transient[ES = Never, RS = Never](
        self,
        /,
        *,
        retry_on: RetryOn = "errors-and-responses",
        while_: Callable[[E | ES], bool] | None = None,
        schedule: Schedule[object, Any, ES, RS] | None = None,
        times: int | None = None,
    ) -> HttpClientService[E | ES, R | RS]: ...
    def retry_transient(
        self,
        policy: Schedule[Any, Any, Any, Any] | None = None,
        /,
        *,
        retry_on: RetryOn = "errors-and-responses",
        while_: Callable[[Any], bool] | None = None,
        schedule: Schedule[Any, Any, Any, Any] | None = None,
        times: int | None = None,
    ) -> HttpClientService[Any, Any]:
        """Retry transient failures (timeouts, transport errors, 408, 429,
        500, 502, 503 and 504 statuses) and repeat on transient responses, waiting at least
        each response's ``Retry-After``. ``retry_on`` limits it to errors
        or to responses; ``while_`` adds errors to retry."""
        from pyfect.http.client._retry import retry_transient

        return self._on_response(
            retry_transient(
                policy if policy is not None else schedule,
                retry_on="errors-and-responses" if policy is not None else retry_on,
                while_=None if policy is not None else while_,
                times=None if policy is not None else times,
            )
        )

    def timeout(self, duration: DurationInput) -> HttpClientService[E | HttpClientError, R]:
        """Fail a request that gets no response within ``duration`` with an
        ``HttpClientError`` whose reason is a ``TransportError`` caused by a
        ``TimeoutException`` (which ``retry_transient`` retries). The request
        is interrupted, so it is aborted unless ``with_scope`` holds it.
        Applied before ``retry_transient`` each attempt gets its own budget;
        after it, the budget bounds the whole retry loop."""
        from pyfect.http.client._timeout import timeout

        return self.transform(timeout(duration))

    def with_rate_limiter(
        self,
        *,
        limiter: RateLimiterService,
        window: DurationInput,
        limit: float,
        key: str | Callable[[HttpClientRequest], str],
        algorithm: Algorithm = "fixed-window",
        tokens: float | Callable[[HttpClientRequest], float] = 1,
        times: int | None = None,
        response_headers: RateLimitHeaders | None = None,
        disable_response_inspection: bool = False,
        disable_adaptive_learning: bool = False,
    ) -> HttpClientService[E | RateLimiterError, R]:
        """Send each request through ``limiter``: ``limit`` requests (each
        costing ``tokens``, at least 1) per ``window`` for each ``key``,
        waiting when over it. The rate limit headers of responses update the
        limit and window, and a reported remaining budget of zero holds
        requests until its reset. A ``429`` response (or ``HttpClientError``
        wrapping one) is retried through the limiter after its
        ``Retry-After``, ``times`` times at most (unbounded by default), and
        teaches the limiter's adaptive pacing for the key.
        ``disable_response_inspection`` ignores the headers (429s are still
        retried; ``times=0`` stops that); ``disable_adaptive_learning`` only
        stops the pacing."""
        from pyfect.http.client._rate_limit import RateLimitOptions, with_rate_limiter

        options = RateLimitOptions(
            limiter=limiter,
            window=window,
            limit=limit,
            key=key,
            algorithm=algorithm,
            tokens=tokens,
            times=times,
            response_headers={} if response_headers is None else response_headers,
            disable_response_inspection=disable_response_inspection,
            disable_adaptive_learning=disable_adaptive_learning,
        )
        return self.transform(with_rate_limiter(options))

    def with_circuit_breaker[R2 = Never](
        self,
        *,
        breaker: CircuitBreakerService,
        key: str | Callable[[HttpClientRequest], str] | None = None,
        classify: Classifier[HttpClientResponse, E, R2] | None = None,
    ) -> HttpClientService[E | CircuitBreakerError, R | R2]:
        """Send each request through ``breaker``'s circuit for ``key``
        (default the request's origin, or its raw URL when it has none),
        each outcome counted by ``classify`` (default
        ``circuit_breaker_classifier``). Apply it after ``with_rate_limiter``
        and ``retry_transient`` so the breaker sees their final outcome;
        ``retry_transient`` never retries a ``CircuitBreakerError``."""
        from pyfect.http.client._circuit_breaker import with_circuit_breaker

        return self.transform(with_circuit_breaker(breaker, key, classify))

    def with_cookies_ref(self, ref: Ref[tuple[Cookie, ...]]) -> HttpClientService[E, R]:
        """Keep the cookies each response sets in ``ref``
        (``cookies.merge_into_array`` for the response URL) and send each
        request the ones ``cookies.to_request_cookie_header`` selects for its
        final URL, after later changes such as ``prepend_url``; with
        ``follow_redirects`` applied after it, on every hop. Expiry reads the
        ``Clock``."""
        from pyfect.clock import current_time_millis
        from pyfect.http.client._make import carry_scope
        from pyfect.http.cookies import merge_into_array, to_request_cookie_header

        pre = self._preprocess
        post = self._postprocess

        def add_cookies(request: HttpClientRequest) -> Effect[HttpClientRequest]:
            def with_header(jar: tuple[Cookie, ...], now: float) -> Effect[HttpClientRequest]:
                header = to_request_cookie_header(jar, request.url, now)
                if header is None:
                    return succeed(request)
                with_cookies = request.set_header("cookie", header)
                return carry_scope(request, with_cookies).as_(with_cookies)

            return ref.get().zip_with(current_time_millis(), with_header).flatten()

        def store(
            requests: Effect[HttpClientRequest, Any, Any],
        ) -> Effect[HttpClientResponse, E, R]:
            return post(requests.flat_map(add_cookies)).tap(
                lambda response: current_time_millis().flat_map(
                    lambda now: ref.update(
                        lambda jar: merge_into_array(jar, response.url, response.cookies, now)
                    )
                )
            )

        return HttpClientService(store, pre)

    def with_scope(self) -> HttpClientService[E, R | Scope]:
        """Tie each request to the current ``Scope``: closing it aborts the
        request and its response body, which stay readable until then."""
        from pyfect.http.client._make import scoped

        return self.transform(scoped)

    def follow_redirects(self, max_redirects: int = 10) -> HttpClientService[E, R]:
        """Follow 3xx responses with a ``Location``, up to ``max_redirects``
        hops. 303 (and 301 / 302 after a ``POST``) switch to ``GET`` without
        a body; a hop to another origin drops the credentials headers."""
        from pyfect.http.client._redirects import follow_redirects

        return follow_redirects(self, max_redirects)


def make_with[E, R](
    postprocess: Callable[[Effect[HttpClientRequest, Any, Any]], Effect[HttpClientResponse, E, R]],
    preprocess: Callable[[HttpClientRequest], Effect[HttpClientRequest, Any, Any]],
) -> HttpClientService[E, R]:
    return HttpClientService(postprocess, preprocess)


class HttpClient(Tag[HttpClientService[HttpClientError, Never]]):
    """The HTTP client service."""


def transform_response[E, R, E1 = Never, R1 = Never](
    f: Callable[[Effect[HttpClientResponse, E, R]], Effect[HttpClientResponse, E1, R1]],
) -> Callable[[HttpClientService[E, R]], HttpClientService[E1, R1]]:
    """Replace sending with ``f(sending)``; ``f`` decides the error type.
    Use with ``.pipe``."""
    return lambda client: client._on_response(f)  # pyright: ignore[reportPrivateUsage]


def catch_tag[T, E2 = Never, R2 = Never](
    tag: Tags[T], f: Callable[[T], Effect[HttpClientResponse, E2, R2]]
) -> _CatchTag[T, E2, R2]:
    """Recover from the failures that are instances of ``tag`` and remove
    them from the client's errors. Use with ``.pipe``."""
    return _CatchTag(tag, f)


@final
class _CatchTag[T, E2, R2]:
    __slots__ = ("f", "tag")

    def __init__(
        self,
        tag: Tags[T],
        f: Callable[[T], Effect[HttpClientResponse, E2, R2]],
    ) -> None:
        self.tag = tag
        self.f = f

    @overload
    def __call__[R = Never](
        self, client: HttpClientService[T, R]
    ) -> HttpClientService[E2, R | R2]: ...
    @overload
    def __call__[R = Never, ER = Never](
        self, client: HttpClientService[T | ER, R]
    ) -> HttpClientService[ER | E2, R | R2]: ...
    def __call__(self, client: HttpClientService[Any, Any]) -> HttpClientService[Any, Any]:
        tag, f = self.tag, self.f

        def handle(error: Any) -> Effect[HttpClientResponse, Any, Any]:
            return f(error) if isinstance(error, tag) else fail(error)

        return client._on_response(lambda eff: eff.catch_all(handle))  # pyright: ignore[reportPrivateUsage]


def execute(request: HttpClientRequest) -> Effect[HttpClientResponse, HttpClientError, HttpClient]:
    """Send ``request`` with the ``HttpClient`` service."""
    return HttpClient().flat_map(lambda client: client.execute(request))


def get(
    url: UrlInput, **options: Unpack[RequestOptions]
) -> Effect[HttpClientResponse, HttpClientError, HttpClient]:
    return execute(_request.get(url, **options))


def post(
    url: UrlInput, **options: Unpack[RequestOptions]
) -> Effect[HttpClientResponse, HttpClientError, HttpClient]:
    return execute(_request.post(url, **options))


def put(
    url: UrlInput, **options: Unpack[RequestOptions]
) -> Effect[HttpClientResponse, HttpClientError, HttpClient]:
    return execute(_request.put(url, **options))


def patch(
    url: UrlInput, **options: Unpack[RequestOptions]
) -> Effect[HttpClientResponse, HttpClientError, HttpClient]:
    return execute(_request.patch(url, **options))


def delete(
    url: UrlInput, **options: Unpack[RequestOptions]
) -> Effect[HttpClientResponse, HttpClientError, HttpClient]:
    return execute(_request.delete(url, **options))


def head(
    url: UrlInput, **options: Unpack[RequestOptions]
) -> Effect[HttpClientResponse, HttpClientError, HttpClient]:
    return execute(_request.head(url, **options))


def options(
    url: UrlInput, **options: Unpack[RequestOptions]
) -> Effect[HttpClientResponse, HttpClientError, HttpClient]:
    return execute(_request.options(url, **options))


def query(
    url: UrlInput, **options: Unpack[RequestOptions]
) -> Effect[HttpClientResponse, HttpClientError, HttpClient]:
    return execute(_request.query(url, **options))
