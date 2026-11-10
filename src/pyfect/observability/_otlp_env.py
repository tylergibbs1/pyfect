"""The OpenTelemetry environment variables the OTLP exporters and proxy
read (Effect's ``observability/internal/otlpEnv``)."""

from __future__ import annotations

from typing import Literal

from pyfect import config
from pyfect import schema as S
from pyfect._js import trim
from pyfect._url import Url
from pyfect.duration import Duration
from pyfect.duration import millis as millis_duration
from pyfect.effect import Effect, gen
from pyfect.http import url as _url
from pyfect.observability.otlp_exporter import Compression
from pyfect.option import Some

type Signal = Literal["LOGS", "METRICS", "TRACES"]


def _headers_record(name: str) -> config.Config[dict[str, str]]:
    return config.dict_of(S.StringFromUriComponent, name)


def headers(signal: Signal) -> config.Config[dict[str, str] | None]:
    """``OTEL_EXPORTER_OTLP_<SIGNAL>_HEADERS``, else
    ``OTEL_EXPORTER_OTLP_HEADERS``: ``key=value`` pairs with
    percent-encoded values; ``None`` when neither is set."""
    signal_headers = _headers_record(f"OTEL_EXPORTER_OTLP_{signal}_HEADERS")
    base: config.Config[dict[str, str] | None] = _headers_record("OTEL_EXPORTER_OTLP_HEADERS")
    return signal_headers.or_else(lambda _: base).with_default(None)


def _signal_path(url: Url, signal: Signal) -> Url:
    slash = "" if url.pathname.endswith("/") else "/"
    return _url.set_pathname(url, f"{url.pathname}{slash}v1/{signal.lower()}")


def endpoint(signal: Signal) -> config.Config[Url | None]:
    """``OTEL_EXPORTER_OTLP_<SIGNAL>_ENDPOINT`` as it is, else
    ``OTEL_EXPORTER_OTLP_ENDPOINT`` with ``/v1/<signal>`` appended to its
    path; ``None`` when neither is set."""
    base: config.Config[Url | None] = config.url("OTEL_EXPORTER_OTLP_ENDPOINT").map(
        lambda url: _signal_path(url, signal)
    )
    return (
        config.url(f"OTEL_EXPORTER_OTLP_{signal}_ENDPOINT")
        .or_else(lambda _: base)
        .with_default(None)
    )


def exporters(signal: Signal) -> config.Config[list[str]]:
    """``OTEL_<SIGNAL>_EXPORTER``: comma-separated names, lower-cased and
    trimmed, empty ones dropped; empty when unset."""
    names = config.list_of(S.String, f"OTEL_{signal}_EXPORTER").map(
        lambda values: [name for value in values if (name := trim(value.lower())) != ""]
    )
    empty: list[str] = []
    return names.with_default(empty)


def compression(signal: Signal) -> Effect[Compression, config.ConfigError]:
    """``OTEL_EXPORTER_OTLP_<SIGNAL>_COMPRESSION``, else
    ``OTEL_EXPORTER_OTLP_COMPRESSION``, else ``"none"``; anything but
    ``gzip`` or ``none`` fails."""
    base: config.Config[Compression] = config.literal(
        "gzip", "none", name="OTEL_EXPORTER_OTLP_COMPRESSION"
    )
    own: config.Config[Compression] = config.literal(
        "gzip", "none", name=f"OTEL_EXPORTER_OTLP_{signal}_COMPRESSION"
    )

    @gen
    def read():
        base_value = yield from base.option()
        own_value = yield from own.option()
        for value in (own_value, base_value):
            if isinstance(value, Some):
                return value.value
        none: Compression = "none"
        return none

    return read


def millis(name: str) -> Effect[Duration | None, config.ConfigError]:
    """An integer number of milliseconds at ``name``; ``None`` when unset."""
    return (
        config.integer(name)
        .option()
        .map(lambda value: millis_duration(value.value) if isinstance(value, Some) else None)
    )


def first_of[A](*values: A | None) -> A | None:
    """The first value that is not ``None`` (``Option.firstSomeOf``)."""
    for value in values:
        if value is not None:
            return value
    return None
