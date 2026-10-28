"""Ports of Effect's ``encoding/Sse.test.ts``.

Each test's docstring is the Effect test title. ``Sse.Event`` is the
``sse.Event`` dataclass (no ``_tag``), ``encoder.write`` is ``sse.write``,
and the parser's callback appends to a list. The ``Sse.Event`` schema is
``sse.EventSchema``, which decodes and encodes ``Event`` values (Effect's
decodes the tagged object the parser writes); ``Sse.EventEncoded.fields``
spread into a struct is ``S.Struct(sse.EventFields, data=...)``.
"""

from typing import NotRequired, TypedDict

import pytest

from pyfect import schema as S
from pyfect import stream, testing
from pyfect.encoding import sse
from pyfect.encoding.sse import AnyEvent, Event


def _parser(
    max_event_size: int = sse.DEFAULT_MAX_EVENT_SIZE,
) -> tuple[sse.Parser, list[AnyEvent]]:
    events: list[AnyEvent] = []
    return sse.make_parser(events.append, max_event_size=max_event_size), events


def test_parses_mixed_crlf_and_lf_line_endings():
    """parses mixed CRLF and LF line endings"""
    parser, events = _parser()
    parser.feed("data: first\r\ndata: second\n\n")
    assert events == [Event(data="first\nsecond")]


def test_treats_crlf_split_across_chunks_as_one_line_ending():
    """treats CRLF split across chunks as one line ending"""
    parser, events = _parser()
    parser.feed("data: fir")
    parser.feed("st\r")
    parser.feed("\ndata: second\n\n")
    assert events == [Event(data="first\nsecond")]


def test_retains_the_last_event_id_for_later_events():
    """retains the last event ID for later events"""
    parser, events = _parser()
    parser.feed("id: 1\ndata: first\n\ndata: second\n\n")
    assert events == [Event(id="1", data="first"), Event(id="1", data="second")]


def test_roundtrips_an_sse_event_with_empty_data():
    """roundtrips an SSE event with empty data"""
    event = Event(data="")
    parser, events = _parser()
    parser.feed(sse.write(event))
    assert events == [event]


def test_roundtrips_cr_crlf_and_lf_data_lines_preserving_a_trailing_empty_line():
    """roundtrips CR, CRLF and LF data lines, preserving a trailing empty line"""
    parser, events = _parser()
    parser.feed(sse.write(Event(data="10%\r50%\r\ndone\n")))
    assert events == [Event(data="10%\n50%\ndone\n")]


def test_strips_a_utf8_bom_from_the_start_of_an_sse_stream():
    """strips a UTF-8 BOM from the start of an SSE stream"""
    parser, events = _parser()
    parser.feed("﻿data: ok\n\n")
    assert events == [Event(data="ok")]


def test_uses_message_for_an_empty_sse_event_type():
    """uses message for an empty SSE event type"""
    parser, events = _parser()
    parser.feed("event:\ndata: ok\n\n")
    assert len(events) == 1
    assert isinstance(events[0], Event) and events[0].event == "message"


def test_parses_a_long_line_split_across_many_chunks():
    """parses a long line split across many chunks"""
    parser, events = _parser()
    value = "x" * 10_000
    text = f"event: big\ndata: {value}\n\n"
    for i in range(0, len(text), 7):
        parser.feed(text[i : i + 7])
    assert events == [Event(event="big", data=value)]


def test_discards_the_rest_of_the_chunk_when_reset_from_on_parse():
    """discards the rest of the chunk when reset from onParse"""
    seen: list[str] = []

    def on_parse(event: AnyEvent) -> None:
        if isinstance(event, Event):
            seen.append(event.data)
            if event.data == "a":
                parser.reset()

    parser = sse.make_parser(on_parse)
    parser.feed("data: a\n\ndata: b\n\n")
    parser.feed("data: fresh\n\n")
    assert seen == ["a", "fresh"]


def test_discards_the_current_event_and_remaining_chunk_when_on_parse_throws():
    """discards the current event and remaining chunk when onParse throws"""
    events: list[AnyEvent] = []

    def on_parse(event: AnyEvent) -> None:
        if isinstance(event, Event) and event.data == "a":
            raise RuntimeError("onParse failed")
        events.append(event)

    parser = sse.make_parser(on_parse)
    with pytest.raises(RuntimeError, match="onParse failed"):
        parser.feed("event: custom\ndata: a\n\ndata: b\n\n")
    parser.feed("data: c\n\n")
    assert events == [Event(data="c")]


def test_ignores_retry_values_that_are_not_ascii_digits():
    """ignores retry values that are not ASCII digits"""
    events: list[AnyEvent] = []
    for value in ["123x", "+123", "-123", "1.5"]:
        sse.make_parser(events.append).feed(f"retry: {value}\n")
    assert events == []


@testing.effect
def test_fails_when_an_unterminated_line_exceeds_max_event_size():
    """fails when an unterminated line exceeds maxEventSize"""
    events = stream.make("12345").pipe_through_channel(sse.decode(max_event_size=4))
    error = yield from events.run_collect().flip()
    assert isinstance(error, sse.SseError)
    assert isinstance(error.reason, sse.EventTooLarge)
    assert error.reason.max_event_size == 4


def test_counts_buffered_data_and_fragmented_pending_lines_toward_max_event_size_and_recovers():
    """counts buffered data and fragmented pending lines toward maxEventSize and recovers"""
    parser, events = _parser(max_event_size=10)
    assert parser.feed("data: a\n") is None
    assert parser.feed("data:") is None
    assert parser.feed(" bc") is None
    error = parser.feed("d")
    assert isinstance(error, sse.SseError)
    assert isinstance(error.reason, sse.EventTooLarge)
    assert error.reason.max_event_size == 10

    assert parser.feed("﻿data: x\n\n") is None
    assert events == [Event(data="x")]


@testing.effect
def test_fails_when_pending_data_exceeds_max_event_size():
    """fails when pending data exceeds maxEventSize"""
    events = stream.make("data: a\n", "data: b\n").pipe_through_channel(
        sse.decode(max_event_size=3)
    )
    error = yield from events.run_collect().flip()
    assert isinstance(error, sse.SseError)
    assert isinstance(error.reason, sse.EventTooLarge)
    assert error.reason.max_event_size == 3


@testing.effect
def test_parses_pending_state_just_under_max_event_size():
    """parses pending state just under maxEventSize"""
    texts = stream.make("data: a\ndata: b", "\n\n")
    events = yield from texts.pipe_through_channel(sse.decode(max_event_size=10)).run_collect()
    assert events == [Event(data="a\nb")]


@testing.effect
def test_parses_well_formed_events_split_across_chunks():
    """parses well-formed events split across chunks"""
    texts = stream.make("id: 1\nevent: up", "date\ndata: hel", "lo\n", "\n")
    events = yield from texts.pipe_through_channel(sse.decode()).run_collect()
    assert events == [Event(event="update", id="1", data="hello")]


def test_event_preserves_string_payloads():
    """Event preserves string payloads"""
    decode = S.decode_unknown_sync(sse.EventSchema)
    encode = S.encode_sync(sse.EventSchema)

    event = decode(Event(event="message", id=None, data='{"type":"ok"}'))

    assert event.data == '{"type":"ok"}'
    assert encode(event) == Event(event="message", id=None, data='{"type":"ok"}')


class _Payload(TypedDict):
    type: str


class _EventWithJsonPayload(TypedDict):
    event: str
    data: _Payload
    id: NotRequired[str]


def test_event_encoded_consumers_can_explicitly_decode_json_payloads():
    """EventEncoded consumers can explicitly decode json payloads"""
    event_with_json_payload = S.Struct(
        _EventWithJsonPayload, data=S.from_json_string(S.Struct(_Payload))
    )
    decode = S.decode_unknown_sync(event_with_json_payload)

    event = decode({"event": "message", "data": '{"type":"ok"}'})

    assert event["data"] == {"type": "ok"}


@testing.effect
def test_decode_data_schema_decodes_json_payload_from_sse_stream():
    """decodeDataSchema decodes json payload from SSE stream"""
    events = yield from (
        stream.make('event: message\ndata: {"type":"ok"}\n\n')
        .pipe_through_channel(sse.decode_data_schema(S.Struct(_Payload)))
        .run_collect()
    )

    assert events == [{"event": "message", "id": None, "data": {"type": "ok"}}]
