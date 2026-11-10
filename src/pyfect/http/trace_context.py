"""Trace context headers (Effect's ``HttpTraceContext``): the W3C
``traceparent`` and Zipkin ``b3`` headers a client sends with its span, and
reading a parent span back from them."""

from __future__ import annotations

import re
from collections.abc import Callable

from pyfect.http.headers import Headers
from pyfect.tracer import ExternalSpan, Span

type FromHeaders = Callable[[Headers], ExternalSpan | None]


def to_headers(span: Span) -> Headers:
    """``b3`` and ``traceparent`` headers naming ``span``."""
    parent = "" if span.parent is None else f"-{span.parent.span_id}"
    b3_flag, w3c_flags = ("1", "01") if span.sampled else ("0", "00")
    trace_id = span.trace_id.rjust(32, "0")
    return Headers(
        {
            "b3": f"{span.trace_id}-{span.span_id}-{b3_flag}{parent}",
            "traceparent": f"00-{trace_id}-{span.span_id}-{w3c_flags}",
        }
    )


# Lowercase only, as W3C Trace Context and B3 write them.
_W3C_TRACE_ID = re.compile(r"[0-9a-f]{32}")
_W3C_SPAN_ID = re.compile(r"[0-9a-f]{16}")
_W3C_TRACE_FLAGS = re.compile(r"[0-9a-f]{2}")
_B3_TRACE_ID = re.compile(r"[0-9a-f]{16}|[0-9a-f]{32}")


def _b3_ids(trace_id: str, span_id: str) -> bool:
    return (
        _B3_TRACE_ID.fullmatch(trace_id) is not None and _W3C_SPAN_ID.fullmatch(span_id) is not None
    )


def w3c(headers: Headers) -> ExternalSpan | None:
    """The span of a version ``00`` ``traceparent`` header with lowercase
    identifiers and two-digit trace flags."""
    traceparent = headers.get("traceparent")
    if not traceparent:
        return None
    parts = traceparent.split("-")
    if len(parts) != 4:
        return None
    version, trace_id, span_id, flags = parts
    if (
        version != "00"
        or _W3C_TRACE_ID.fullmatch(trace_id) is None
        or _W3C_SPAN_ID.fullmatch(span_id) is None
        or _W3C_TRACE_FLAGS.fullmatch(flags) is None
        or trace_id == "0" * 32
        or span_id == "0" * 16
    ):
        return None
    return ExternalSpan(span_id=span_id, trace_id=trace_id, sampled=int(flags, 16) & 1 == 1)


def b3(headers: Headers) -> ExternalSpan | None:
    """The span of a single ``b3`` header."""
    value = headers.get("b3")
    if value is None:
        return None
    parts = value.split("-")
    if len(parts) < 2 or not _b3_ids(parts[0], parts[1]):
        return None
    sampled = parts[2] in ("1", "d") if len(parts) > 2 and parts[2] else True
    return ExternalSpan(span_id=parts[1], trace_id=parts[0], sampled=sampled)


def xb3(headers: Headers) -> ExternalSpan | None:
    """The span of the multi-header ``x-b3-*`` form."""
    trace_id = headers.get("x-b3-traceid")
    span_id = headers.get("x-b3-spanid")
    if not trace_id or not span_id or not _b3_ids(trace_id, span_id):
        return None
    flagged = headers.get("x-b3-sampled")
    sampled = headers.get("x-b3-flags") == "1" or (flagged in ("1", "true") if flagged else True)
    return ExternalSpan(span_id=span_id, trace_id=trace_id, sampled=sampled)


def from_headers(headers: Headers) -> ExternalSpan | None:
    """The span of ``traceparent``, else ``b3``, else ``x-b3-*``."""
    return w3c(headers) or b3(headers) or xb3(headers)


__all__ = ["FromHeaders", "b3", "from_headers", "to_headers", "w3c", "xb3"]
