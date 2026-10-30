"""``channel_schema`` and the schema framers: chunks decoded and encoded with
a schema (Effect has no ``ChannelSchema.test.ts``; messages printed by
Effect under Node)."""

from typing import TypedDict

import pyfect as fx
from pyfect import channel, channel_schema, stream, testing
from pyfect import schema as S
from pyfect.encoding import ndjson, sse


@testing.effect
def test_decode_decodes_each_chunk():
    values = yield from (
        stream.from_arrays(("1", "2"), ("3",))
        .pipe_through_channel(channel_schema.decode(S.NumberFromString))
        .run_collect()
    )
    assert values == [1, 2, 3]


@testing.effect
def test_decode_fails_at_the_value_index_in_its_chunk():
    error = yield from (
        stream.from_arrays(("1", "a"))
        .pipe_through_channel(channel_schema.decode(S.FiniteFromString))
        .run_collect()
        .flip()
    )
    assert isinstance(error, S.SchemaError)
    assert str(error) == "Expected a finite number\n  at [1]"


@testing.effect
def test_decode_writes_the_chunks_before_a_failing_one():
    written: list[float] = []
    error = yield from (
        stream.from_arrays(("1",), (2,))
        .pipe_through_channel(channel_schema.decode_unknown(S.NumberFromString))
        .run_for_each(lambda n: fx.sync(lambda: written.append(n)))
        .flip()
    )
    assert written == [1]
    assert isinstance(error, S.SchemaError)


@testing.effect
def test_decode_takes_parse_options():
    class Pair(TypedDict):
        a: str
        b: str

    empty: object = {}
    error = yield from (
        stream.make(empty)
        .pipe_through_channel(channel_schema.decode_unknown(S.Struct(Pair), errors="all"))
        .run_collect()
        .flip()
    )
    assert str(error) == 'Missing key\n  at [0]["a"]\nMissing key\n  at [0]["b"]'


@testing.effect
def test_encode_encodes_each_chunk():
    texts = yield from (
        stream.make(1.5, 2.0)
        .pipe_through_channel(channel_schema.encode(S.NumberFromString))
        .run_collect()
    )
    assert texts == ["1.5", "2"]


type _Texts = fx.Channel[tuple[str, ...], S.SchemaError, None, tuple[str, ...], S.SchemaError, None]
type _Framed[T] = fx.Channel[
    tuple[T, ...],
    ndjson.NdjsonError | S.SchemaError,
    None,
    tuple[T, ...],
    ndjson.NdjsonError | S.SchemaError,
    None,
]


@testing.effect
def test_duplex_encodes_the_input_and_decodes_the_output():
    echo: _Texts = channel.identity()
    doubled = echo.map(lambda chunk: tuple(text + "0" for text in chunk))
    wrapped = channel_schema.duplex(
        doubled, input_schema=S.NumberFromString, output_schema=S.NumberFromString
    )
    values = yield from stream.make(1, 2).pipe_through_channel(wrapped).run_collect()
    assert values == [10, 20]


@testing.effect
def test_ndjson_duplex_schema_frames_and_decodes_the_replies():
    class Message(TypedDict):
        id: int

    echo: _Framed[bytes] = channel.identity()
    wrapped = ndjson.duplex_schema(
        echo, input_schema=S.Struct(Message), output_schema=S.Struct(Message)
    )
    replies = yield from stream.make(Message(id=1)).pipe_through_channel(wrapped).run_collect()
    assert replies == [{"id": 1}]
    text_echo: _Framed[str] = channel.identity()
    wrong: object = {"id": "1"}
    error = yield from (
        stream.make(wrong)
        .pipe_through_channel(
            ndjson.duplex_schema_string(
                text_echo, input_schema=S.Unknown, output_schema=S.Struct(Message)
            )
        )
        .run_collect()
        .flip()
    )
    assert str(error) == 'Expected number\n  at [0]["id"]'


@testing.effect
def test_ndjson_encode_schema_encodes_before_writing():
    class Stamp(TypedDict):
        n: float

    lines = yield from (
        stream.make({"n": 1.5})
        .pipe_through_channel(ndjson.encode_schema_string(S.Struct(Stamp, n=S.NumberFromString)))
        .run_string()
    )
    assert lines == '{"n":"1.5"}\n'


class _Named(TypedDict):
    event: str
    data: str


@testing.effect
def test_sse_decode_schema_decodes_the_event_fields():
    class WithId(TypedDict):
        event: str
        data: str
        id: str

    events = yield from (
        stream.make("event: ping\ndata: a\n\n")
        .pipe_through_channel(sse.decode_schema(S.Struct(_Named)))
        .run_collect()
    )
    assert events == [{"event": "ping", "data": "a"}]
    # An event before any ID has no ``id`` key.
    error = yield from (
        stream.make("data: a\n\n")
        .pipe_through_channel(sse.decode_schema(S.Struct(WithId)))
        .run_collect()
        .flip()
    )
    assert str(error) == 'Missing key\n  at [0]["id"]'


@testing.effect
def test_sse_encode_schema_writes_events_and_a_retry():
    class Data(TypedDict):
        data: str

    events = stream.make(_Named(event="message", data="a\nb")).concat(
        stream.fail(sse.Retry(1.5, None))
    )
    text = yield from events.pipe_through_channel(sse.encode_schema(S.Struct(_Named))).run_string()
    assert text == "data: a\ndata: b\n\nretry: 1500\n\n"
    # No ``event`` field is ``"message"``.
    text = yield from (
        stream.make(Data(data="x"))
        .pipe_through_channel_or_fail(sse.encode_schema(S.Struct(Data)))
        .run_string()
    )
    assert text == "data: x\n\n"


@testing.effect
def test_sse_encode_schema_fails_with_a_schema_error_for_a_line_break_in_the_name():
    error = yield from (
        stream.make(_Named(event="a\ndata: forged", data="x"))
        .pipe_through_channel_or_fail(sse.encode_schema(S.Struct(_Named)))
        .run_string()
        .flip()
    )
    assert isinstance(error, S.SchemaError)
