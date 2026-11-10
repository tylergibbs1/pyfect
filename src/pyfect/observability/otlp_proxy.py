"""Proxying OTLP/HTTP exports from browsers through the app's own HTTP
server to a collector (Effect's ``OtlpProxy``).

``layer`` mounts ``POST /v1/traces``, ``/v1/logs`` and ``/v1/metrics`` on
the ``HttpRouter``, adds the configured headers on the server and forwards
the body unchanged:

- The upstream URL comes only from configuration; the request's path and
  query never reach it.
- Only ``application/json`` and ``application/x-protobuf`` bodies are
  accepted (415 otherwise); only ``content-type`` and ``content-encoding``
  are forwarded, then the configured headers, so a client cannot override
  them. Upstream requests ask for ``accept-encoding: identity``.
- Bodies are buffered up to ``max_body_size`` (413 beyond it).
- The upstream status and body come back with only ``content-type`` and
  ``retry-after``; a transport failure is 502 and a timeout 504. Nothing is
  retried or batched.

Anyone who can reach the routes sends telemetry with the configured
credentials: compose authentication, CORS and rate limiting around it."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final, Literal, Never

from pyfect import byte_size
from pyfect import layer as _layer
from pyfect._digits import parse_digits
from pyfect.byte_size import ByteSize
from pyfect.duration import Input as DurationInput
from pyfect.effect import Effect, gen, provide_service, succeed
from pyfect.errors import TimeoutException
from pyfect.http import headers as _headers
from pyfect.http import request as _request
from pyfect.http import server_response
from pyfect.http.client import (
    HttpClient,
    HttpClientError,
    HttpClientService,
    TracerDisabledWhen,
    transform_response,
)
from pyfect.http.incoming_message import MaxBodySize
from pyfect.http.response import HttpClientResponse
from pyfect.http.router import HttpRouter
from pyfect.http.server_request import HttpServerRequest
from pyfect.http.server_respondable import to_response
from pyfect.http.server_response import HttpServerResponse
from pyfect.layer import Layer
from pyfect.observability import _otlp_env as env

__all__ = ["Handler", "Signal", "layer", "layer_from_config", "make"]

type Signal = Literal["traces", "logs", "metrics"]
type Handler = Effect[HttpServerResponse, Never, HttpServerRequest]
"""A route handler forwarding one signal."""

_ALL_SIGNALS: Final[tuple[Signal, ...]] = ("traces", "logs", "metrics")
_CONTENT_TYPES: Final = frozenset({"application/json", "application/x-protobuf"})
_DEFAULT_MAX_BODY_SIZE: Final = byte_size.mebibytes(10)
_DEFAULT_TIMEOUT: Final = "10 seconds"
_ENV_SIGNALS: Final[Mapping[Signal, env.Signal]] = {
    "traces": "TRACES",
    "logs": "LOGS",
    "metrics": "METRICS",
}


def _supported(content_type: str | None) -> bool:
    return content_type is not None and (
        content_type in _CONTENT_TYPES
        or content_type.split(";")[0].strip().lower() in _CONTENT_TYPES
    )


def _content_length(text: str | None) -> int | None:
    return None if text is None else parse_digits(text)


def _to_server_response(response: HttpClientResponse, body: bytes) -> HttpServerResponse:
    headers: dict[str, str] = {}
    retry_after = response.headers.get("retry-after")
    if retry_after is not None:
        headers["retry-after"] = retry_after
    if not body:
        return server_response.empty(status=response.status, headers=headers)
    content_type = response.headers.get("content-type")
    if content_type is None:
        return server_response.bytes_(body, status=response.status, headers=headers)
    return server_response.bytes_(
        body, status=response.status, headers=headers, content_type=content_type
    )


def _make_handler(
    client: HttpClientService[HttpClientError, Never],
    url: str,
    headers: _headers.Input | None,
    max_body_size: byte_size.Input | None,
    timeout: DurationInput | None,
) -> Handler:
    # Skips the outbound span and trace headers in one step.
    upstream = client.pipe(transform_response(provide_service(TracerDisabledWhen, lambda _: True)))
    configured = _headers.from_input(headers)
    fixed_limit = None if max_body_size is None else byte_size.from_input_unsafe(max_body_size)
    limit_after = _DEFAULT_TIMEOUT if timeout is None else timeout

    @gen
    def handle():
        request = yield from HttpServerRequest()
        content_type = request.headers.get("content-type")
        if content_type is None or not _supported(content_type):
            return server_response.empty(status=415)
        limit: ByteSize
        if fixed_limit is not None:
            limit = fixed_limit
        else:
            ambient = yield from MaxBodySize()
            limit = _DEFAULT_MAX_BODY_SIZE if ambient is None else ambient
        # Reject an over-limit declared length before reading anything.
        declared = _content_length(request.headers.get("content-length"))
        if declared is not None and declared > limit:
            return server_response.empty(status=413)
        read = yield from (
            request.bytes_.pipe(provide_service(MaxBodySize, limit)).catch_all(to_response)
        )
        if isinstance(read, HttpServerResponse):
            return read
        outbound = _request.post(url).body_bytes(read, content_type)
        content_encoding = request.headers.get("content-encoding")
        if content_encoding is not None:
            outbound = outbound.set_header("content-encoding", content_encoding)
        # The response goes back without content-encoding, so ask for it
        # uncompressed; configured headers can still override this.
        outbound = outbound.set_header("accept-encoding", "identity").set_headers(configured)
        forwarded = upstream.execute(outbound).flat_map(
            lambda response: response.bytes_.map(lambda body: _to_server_response(response, body))
        )
        return (
            yield from forwarded.timeout(limit_after).catch_all(
                lambda error: succeed(
                    server_response.empty(
                        status=504 if isinstance(error, TimeoutException) else 502
                    )
                )
            )
        )

    return handle


def make(
    *,
    base_url: str,
    urls: Mapping[Signal, str] | None = None,
    headers: _headers.Input | None = None,
    max_body_size: byte_size.Input | None = None,
    timeout: DurationInput | None = None,
) -> Effect[dict[Signal, Handler], Never, HttpClient]:
    """One handler per signal, forwarding to ``urls[signal]`` or else
    ``/v1/<signal>`` below ``base_url``. ``max_body_size`` defaults to
    ``MaxBodySize``, then 10 MiB; ``timeout`` to 10 seconds."""
    base = _request.post(base_url)

    @gen
    def build():
        client = yield from HttpClient()
        handlers: dict[Signal, Handler] = {}
        for signal in _ALL_SIGNALS:
            explicit = None if urls is None else urls.get(signal)
            url = explicit if explicit is not None else base.append_url(f"/v1/{signal}").url
            handlers[signal] = _make_handler(client, url, headers, max_body_size, timeout)
        return handlers

    return build


def _add_routes(
    prefix: str | None, routes: Sequence[tuple[Signal, Handler]]
) -> Effect[None, Never, HttpRouter]:
    @gen
    def add():
        router = yield from HttpRouter()
        target = router if prefix is None else router.prefixed(prefix)
        for signal, handler in routes:
            yield from target.add("POST", f"/v1/{signal}", handler)

    return add


def layer(
    *,
    base_url: str,
    urls: Mapping[Signal, str] | None = None,
    headers: _headers.Input | None = None,
    max_body_size: byte_size.Input | None = None,
    timeout: DurationInput | None = None,
    prefix: str | None = None,
    signals: Sequence[Signal] | None = None,
) -> Layer[Never, Never, HttpRouter | HttpClient]:
    """Mounts ``POST <prefix>/v1/<signal>`` for each of ``signals`` (all
    three by default)."""

    @gen
    def mount():
        handlers = yield from make(
            base_url=base_url,
            urls=urls,
            headers=headers,
            max_body_size=max_body_size,
            timeout=timeout,
        )
        chosen = _ALL_SIGNALS if signals is None else signals
        yield from _add_routes(prefix, [(signal, handlers[signal]) for signal in chosen])

    return _layer.effect_discard(mount)


def layer_from_config(
    *,
    headers: _headers.Input | None = None,
    max_body_size: byte_size.Input | None = None,
    timeout: DurationInput | None = None,
    prefix: str | None = None,
    signals: Sequence[Signal] | None = None,
) -> Layer[Never, Never, HttpRouter | HttpClient]:
    """``layer`` with each signal's upstream from
    ``OTEL_EXPORTER_OTLP_<SIGNAL>_ENDPOINT`` (else ``/v1/<signal>`` below
    ``OTEL_EXPORTER_OTLP_ENDPOINT``) and headers from
    ``OTEL_EXPORTER_OTLP_(<SIGNAL>_)HEADERS`` unless ``headers`` is given.
    A signal without an endpoint gets no route; invalid configuration is a
    defect."""

    @gen
    def mount():
        client = yield from HttpClient()
        routes: list[tuple[Signal, Handler]] = []
        for signal in _ALL_SIGNALS if signals is None else signals:
            env_signal = _ENV_SIGNALS[signal]
            url = yield from env.endpoint(env_signal)
            if url is None:
                continue
            signal_headers = (
                headers if headers is not None else (yield from env.headers(env_signal))
            )
            routes.append(
                (signal, _make_handler(client, str(url), signal_headers, max_body_size, timeout))
            )
        yield from _add_routes(prefix, routes)

    return _layer.effect_discard(mount.or_die())
