"""Ports of Effect's ``http/HttpTraceContext.test.ts``.

Each test's docstring is the Effect test title. ``from_headers`` gives
``None`` when no span is found.
"""

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.http import headers as h
from pyfect.http import trace_context
from pyfect.tracer import ExternalSpan

TRACE_ID = "80f198ee56343ba864fe8b2a57d3eff7"
SPAN_ID = "e457b5a2e4d86bd1"


def _span(headers: dict[str, str]) -> ExternalSpan:
    span = trace_context.from_headers(h.from_input(headers))
    assert span is not None
    return span


def _assert_sampled(headers: dict[str, str], sampled: bool) -> None:
    span = _span(headers)
    assert (span.trace_id, span.span_id, span.sampled) == (TRACE_ID, SPAN_ID, sampled)


def test_b3_debug() -> None:
    """accepts single-header B3 debug sampling"""
    _assert_sampled({"b3": f"{TRACE_ID}-{SPAN_ID}-d"}, sampled=True)


def test_legacy_sampled_true() -> None:
    """accepts legacy X-B3-Sampled: true"""
    _assert_sampled(
        {"X-B3-TraceId": TRACE_ID, "X-B3-SpanId": SPAN_ID, "X-B3-Sampled": "true"}, sampled=True
    )


def test_flags_debug_override() -> None:
    """lets X-B3-Flags debug override X-B3-Sampled: 0"""
    _assert_sampled(
        {"X-B3-TraceId": TRACE_ID, "X-B3-SpanId": SPAN_ID, "X-B3-Sampled": "0", "X-B3-Flags": "1"},
        sampled=True,
    )


@pytest.mark.parametrize(
    "headers",
    [
        {"b3": f"{TRACE_ID[16:]}-{SPAN_ID}-1"},
        {"X-B3-TraceId": TRACE_ID[16:], "X-B3-SpanId": SPAN_ID},
    ],
)
def test_64_bit_trace_id(headers: dict[str, str]) -> None:
    """accepts a 64-bit B3 trace-id: %j"""
    span = _span(headers)
    assert (span.trace_id, span.span_id) == (TRACE_ID[16:], SPAN_ID)


@pytest.mark.parametrize(
    "headers",
    [
        {"b3": f"<script>-{SPAN_ID}-1"},
        {"b3": f"{TRACE_ID}-{SPAN_ID[:-1]}g-1"},
        {"b3": f"{TRACE_ID[:-1]}-{SPAN_ID}-1"},
        {"b3": f"{TRACE_ID}-{SPAN_ID[:-1]}-1"},
        {"X-B3-TraceId": "<script>", "X-B3-SpanId": SPAN_ID},
        {"X-B3-TraceId": TRACE_ID, "X-B3-SpanId": f"{SPAN_ID[:-1]}g"},
        {"X-B3-TraceId": TRACE_ID[:-1], "X-B3-SpanId": SPAN_ID},
        {"X-B3-TraceId": TRACE_ID, "X-B3-SpanId": SPAN_ID[:-1]},
        {"b3": f"{TRACE_ID.upper()}-{SPAN_ID}-1"},
        {"b3": f"{TRACE_ID}-{SPAN_ID.upper()}-1"},
        {"X-B3-TraceId": TRACE_ID.upper(), "X-B3-SpanId": SPAN_ID},
        {"X-B3-TraceId": TRACE_ID, "X-B3-SpanId": SPAN_ID.upper()},
    ],
)
def test_rejects_invalid_b3(headers: dict[str, str]) -> None:
    """rejects invalid B3 identifiers: %j"""
    assert trace_context.from_headers(h.from_input(headers)) is None


@pytest.mark.parametrize(
    "traceparent",
    [f"00-{TRACE_ID.upper()}-{SPAN_ID}-01", f"00-{TRACE_ID}-{SPAN_ID.upper()}-01"],
)
def test_rejects_uppercase_w3c_identifiers(traceparent: str) -> None:
    """rejects uppercase W3C identifiers: %s"""
    assert trace_context.from_headers(h.from_input({"traceparent": traceparent})) is None


def test_reads_the_sampled_bit_from_w3c_trace_flags() -> None:
    """reads the sampled bit from W3C trace flags"""
    _assert_sampled({"traceparent": f"00-{TRACE_ID}-{SPAN_ID}-02"}, sampled=False)
    _assert_sampled({"traceparent": f"00-{TRACE_ID}-{SPAN_ID}-ff"}, sampled=True)


@pytest.mark.parametrize("flags", ["1", "001", "0g", "FF"])
def test_rejects_malformed_w3c_trace_flags(flags: str) -> None:
    """rejects malformed W3C trace flags: %j"""
    headers = h.from_input({"traceparent": f"00-{TRACE_ID}-{SPAN_ID}-{flags}"})
    assert trace_context.from_headers(headers) is None


def test_rejects_zero_trace_id() -> None:
    """rejects an all-zero W3C trace-id"""
    headers = h.from_input({"traceparent": f"00-{'0' * 32}-{SPAN_ID}-01"})
    assert trace_context.from_headers(headers) is None


def test_rejects_zero_parent_id() -> None:
    """rejects an all-zero W3C parent-id"""
    headers = h.from_input({"traceparent": f"00-{TRACE_ID}-{'0' * 16}-01"})
    assert trace_context.from_headers(headers) is None


@testing.effect
def test_pads_64_bit_trace_id():
    """pads a 64-bit trace-id in traceparent and keeps it in b3"""
    span = yield from fx.make_span(
        "test", parent=ExternalSpan(trace_id="463ac35c9f6413ad", span_id=SPAN_ID)
    )
    headers = trace_context.to_headers(span)
    assert headers["traceparent"] == f"00-0000000000000000463ac35c9f6413ad-{span.span_id}-01"
    assert headers["b3"] == f"463ac35c9f6413ad-{span.span_id}-1-{SPAN_ID}"
    assert span.trace_id == "463ac35c9f6413ad"
