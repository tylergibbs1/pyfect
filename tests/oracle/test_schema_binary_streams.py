"""Effect's ``encoding/SchemaBinary.test.ts``: connection dictionary, fingerprint
mode parser, and channels.

Adapted: ``Effect.promise`` transformations are ``fx.sleep(0)``-yielding effects,
as Python's async story runs through the fiber scheduler the same way. ``duplex``
"data-last call shape" is keyword-only here; the title passes ``socket`` as the
pipe argument through ``.pipe``.
"""
# pyright: reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownArgumentType=false

from __future__ import annotations

from typing import Any

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import stream as Stream
from pyfect.encoding import schema_binary as B
from pyfect.schema import getter as G
from pyfect.schema import issue as Issue
from pyfect.schema import transformation as T

from ._schema_binary import encode, encode_fp, message_of, nested_array_frame, schema_error, struct

# --- connection dictionary --------------------------------------------------------------

Message = struct(tag=S.String, traceId=S.String, body=S.String, n=S.Number)


def _message(index: int) -> dict[str, Any]:
    return {
        "tag": ("Search", "Get", "Delete")[index % 3],
        "traceId": "0123456789abcdef0123456789abcdef",
        "body": f"body {index}",
        "n": index,
    }


def test_round_trips_a_stream_and_shrinks_repeated_strings() -> None:
    """round-trips a stream and shrinks repeated strings"""
    for fingerprint in (False, True):
        encoder = B.encoder(Message, dictionary=True, fingerprint=fingerprint)
        parser = B.parser(Message, dictionary=True, fingerprint=fingerprint)
        plain = B.encoder(Message, fingerprint=fingerprint)
        values = [_message(i) for i in range(30)]
        decoded: list[object] = []
        sizes: list[int] = []
        for value in values:
            frame = encoder.encode(value)
            sizes.append(len(frame))
            decoded.extend(parser.feed_sync(frame))
        assert decoded == values
        assert sizes[0] == len(plain.encode(values[0]))
        assert sizes[-1] < len(plain.encode(values[-1])) * 0.6


def test_round_trips_arrays_of_strings_across_frames() -> None:
    """round-trips arrays of strings across frames"""
    schema = S.Array(S.String)
    values = [("a", "b"), ("a", "c"), ("a", "a")]
    encoder = B.encoder(schema, dictionary=True)
    parser = B.parser(schema, dictionary=True)
    assert [v for value in values for v in parser.feed_sync(encoder.encode(value))] == values
    message = struct(name=S.String, tags=S.Array(S.String))
    messages = [
        {"name": "shared", "tags": ("a", "b")},
        {"name": "other", "tags": ("shared", "c")},
        {"name": "shared", "tags": ("a", "a")},
    ]
    write = B.encoder(message, dictionary=True)
    read = B.parser(message, dictionary=True)
    assert [v for value in messages for v in read.feed_sync(write.encode(value))] == messages


def test_round_trips_arrays_of_strings_inside_row_runs_across_frames() -> None:
    """round-trips arrays of strings inside row runs across frames"""
    rows = S.Array(struct(id=S.Number, tags=S.Array(S.String)))
    values = [
        ({"id": 1, "tags": ("x",)},),
        ({"id": 2, "tags": ("x",)},),
        ({"id": 3, "tags": ("x",)},),
    ]
    encoder = B.encoder(rows, dictionary=True)
    parser = B.parser(rows, dictionary=True)
    assert [v for value in values for v in parser.feed_sync(encoder.encode(value))] == values


def test_round_trips_batched_frames_and_fragmented_feeds() -> None:
    """round-trips batched frames and fragmented feeds"""
    encoder = B.encoder(Message, dictionary=True)
    parser = B.parser(Message, dictionary=True)
    values = [_message(i) for i in range(12)]
    assert parser.feed_sync(encoder.encode_many(values)) == values
    fragmented = B.encoder(Message, dictionary=True)
    fragmented_parser = B.parser(Message, dictionary=True)
    decoded: list[object] = []
    for value in values:
        frame = fragmented.encode(value)
        decoded.extend(fragmented_parser.feed_sync(frame[:1]))
        decoded.extend(fragmented_parser.feed_sync(frame[1:]))
    assert decoded == values


def test_keeps_the_reader_in_step_when_a_frame_fails_to_encode() -> None:
    """keeps the reader in step when a frame fails to encode"""
    encoder = B.encoder(Message, dictionary=True)
    parser = B.parser(Message, dictionary=True)
    first = _message(0)
    decoded = list(parser.feed_sync(encoder.encode(first)))
    bad = {**_message(1), "tag": "NeverSent", "n": "not a number"}
    assert "number" in message_of(lambda: encoder.encode(bad))
    batch = [_message(2), {**_message(3), "n": "not a number"}]
    assert "number" in message_of(lambda: encoder.encode_many(batch))
    following = _message(4)
    decoded.extend(parser.feed_sync(encoder.encode(following)))
    assert decoded == [first, following]


def test_reports_excess_properties_before_advancing_the_dictionary() -> None:
    """reports excess properties before advancing the dictionary"""
    encoder = B.encoder(Message, dictionary=True, on_excess_property="error")
    parser = B.parser(Message, dictionary=True)
    assert "extra" in message_of(lambda: encoder.encode({**_message(0), "extra": "NeverSent"}))
    batch = [_message(1), {**_message(2), "extra": "NeverSent"}]
    assert "extra" in message_of(lambda: encoder.encode_many(batch))
    following = _message(3)
    assert parser.feed_sync(encoder.encode(following)) == [following]


def test_costs_nothing_on_a_field_whose_strings_never_repeat() -> None:
    """costs nothing on a field whose strings never repeat"""
    unique = struct(s=S.String)
    encoder = B.encoder(unique, dictionary=True)
    parser = B.parser(unique, dictionary=True)
    plain = B.encoder(unique)
    values = [{"s": f"value-{i}"} for i in range(200)]
    decoded: list[object] = []
    dictionary_bytes = plain_bytes = 0
    for value in values:
        frame = encoder.encode(value)
        dictionary_bytes += len(frame)
        plain_bytes += len(plain.encode(value))
        decoded.extend(parser.feed_sync(frame))
    assert decoded == values
    assert dictionary_bytes == plain_bytes


def test_rejects_a_schema_the_binary_layer_does_not_validate_on_its_own() -> None:
    """rejects a schema the binary layer does not validate on its own"""
    checked = struct(s=S.String.check(S.is_min_length(2)))
    with pytest.raises(ValueError, match="dictionary"):
        B.encoder(checked, dictionary=True)
    with pytest.raises(ValueError, match="dictionary"):
        B.parser(checked, dictionary=True)


def test_rejects_a_reference_the_stream_never_sent() -> None:
    """rejects a reference the stream never sent"""
    encoder = B.encoder(Message, dictionary=True)
    parser = B.parser(Message, dictionary=True)
    for i in range(4):
        parser.feed_sync(encoder.encode(_message(i)))
    frame = encoder.encode(_message(4))
    tagged = bytes(0xFF if byte == 1 else byte for byte in frame)
    schema_error(lambda: parser.feed_sync(tagged))


def test_stays_off_by_default() -> None:
    """stays off by default"""
    assert B.encoder(Message).encode(_message(0)) == encode(Message, _message(0))


# --- fingerprint mode parser ------------------------------------------------------------

Person = struct(name=S.String, age=S.Number)
ada = {"name": "Ada", "age": 36}
grace = {"name": "Grace", "age": 45}


def test_parses_concatenated_frames_one_byte_at_a_time_and_mid_frame_splits() -> None:
    """parses concatenated frames, one byte at a time, and mid-frame splits"""
    frames = encode_fp(Person, ada) + encode_fp(Person, grace)
    assert B.parser(Person, fingerprint=True).feed_sync(frames) == [ada, grace]
    by_byte = B.parser(Person, fingerprint=True)
    out: list[object] = []
    for i in range(len(frames)):
        out.extend(by_byte.feed_sync(frames[i : i + 1]))
    by_byte.end_sync()
    assert out == [ada, grace]
    split = B.parser(Person, fingerprint=True)
    assert split.feed_sync(frames[:6]) == []
    assert split.feed_sync(frames[6:]) == [ada, grace]


def test_fails_closed_on_a_default_mode_frame_in_a_fingerprint_stream() -> None:
    """fails closed on a default-mode frame in a fingerprint stream"""
    parser = B.parser(Person, fingerprint=True)
    assert parser.feed_sync(encode_fp(Person, ada) + encode(Person, grace)) == [ada]
    assert "Expected version 2 envelope, flags 1" in message_of(lambda: parser.feed_sync(b""))
    assert "Expected parser is spent" in message_of(parser.end_sync)


def test_honours_max_frame_size_and_reports_truncation_at_end() -> None:
    """honours maxFrameSize and reports truncation at end"""
    bounded = B.parser(Person, fingerprint=True, max_frame_size=4)
    frame = encode_fp(Person, ada)
    assert "Expected frame within maxFrameSize" in message_of(lambda: bounded.feed_sync(frame))
    truncated = B.parser(Person, fingerprint=True)
    assert truncated.feed_sync(frame[:-2]) == []
    assert "Expected complete value" in message_of(truncated.end_sync)


# --- channels ---------------------------------------------------------------------------


@fx.testing.effect
def test_encode_then_decode_round_trips_a_stream():
    """encode then decode round-trips a stream"""
    values = yield from (
        Stream.make(ada, grace)
        .pipe_through_channel(B.encode(Person))
        .pipe_through_channel(B.decode(Person))
        .run_collect()
    )
    assert values == [ada, grace]


@fx.testing.effect
def test_encode_batches_a_chunk_into_one_concatenated_byte_element():
    """encode batches a chunk into one concatenated byte element"""
    frames = yield from Stream.make(ada, grace).pipe_through_channel(B.encode(Person)).run_collect()
    assert frames == [encode(Person, ada) + encode(Person, grace)]


@fx.testing.effect
def test_encode_rejects_non_number_elements_in_uniform_number_arrays():
    """encode rejects non-number elements in uniform number arrays"""
    for value in ("x", None):
        error = yield from (
            Stream.make([1, value, 3])
            .pipe_through_channel(B.encode(S.Array(S.Number)))
            .run_collect()
            .flip()
        )
        assert isinstance(error, S.SchemaError)
        assert "Expected a number" in error.message
        assert "at [1]" in error.message


@fx.testing.effect
def test_encode_reports_excess_properties():
    """encode reports excess properties"""
    error = yield from (
        Stream.make({**ada, "extra": True})
        .pipe_through_channel(B.encode(Person, on_excess_property="error"))
        .run_collect()
        .flip()
    )
    assert isinstance(error, S.SchemaError)
    assert "extra" in error.message


@fx.testing.effect
def test_decodes_a_value_split_across_byte_chunks():
    """decodes a value split across byte chunks"""
    frame = encode(Person, ada)
    values = yield from (
        Stream.make(frame[:3], frame[3:]).pipe_through_channel(B.decode(Person)).run_collect()
    )
    assert values == [ada]


@fx.testing.effect
def test_decodes_concatenated_frames_in_one_chunk():
    """decodes concatenated frames in one chunk"""
    data = encode(Person, ada) + encode(Person, grace)
    values = yield from Stream.make(data).pipe_through_channel(B.decode(Person)).run_collect()
    assert values == [ada, grace]


@fx.testing.effect
def test_fails_deeply_nested_recursive_frames_in_the_error_channel():
    """fails deeply nested recursive frames in the error channel"""
    nested: Any = S.Array(S.suspend(lambda: nested))
    error = yield from (
        Stream.make(nested_array_frame(10_000))
        .pipe_through_channel(B.decode(nested))
        .run_collect()
        .flip()
    )
    assert isinstance(error, S.SchemaError)
    assert "nesting depth at most" in error.message


@fx.testing.effect
def test_fails_when_the_stream_ends_with_an_incomplete_frame():
    """fails when the stream ends with an incomplete frame"""
    frame = encode(Person, ada)
    error = yield from (
        Stream.make(frame[:-1]).pipe_through_channel(B.decode(Person)).run_collect().flip()
    )
    assert isinstance(error, S.SchemaError)
    assert "Expected complete value" in error.message


@fx.testing.effect
def test_emits_completed_values_before_reporting_a_later_failure():
    """emits completed values before reporting a later failure"""
    bad = bytearray(encode(Person, grace))
    bad[1] = 0x10
    seen: list[object] = []

    def note(value: object) -> Any:
        return fx.sync(lambda: seen.append(value))

    error = yield from (
        Stream.make(encode(Person, ada) + bytes(bad), encode(Person, grace))
        .pipe_through_channel(B.decode(Person))
        .tap(note)
        .run_drain()
        .flip()
    )
    assert seen == [ada]
    assert "version 2 envelope, flags 0" in error.message


@fx.testing.effect
def test_enforces_max_frame_size_on_decode_and_ignores_it_on_encode():
    """enforces maxFrameSize on decode and ignores it on encode"""
    values = yield from (
        Stream.make(ada)
        .pipe_through_channel(B.encode(Person))
        .pipe_through_channel(B.decode(Person))
        .run_collect()
    )
    assert values == [ada]
    error = yield from (
        Stream.make(encode(Person, ada))
        .pipe_through_channel(B.decode(Person, max_frame_size=2))
        .run_collect()
        .flip()
    )
    assert "Expected frame within maxFrameSize" in error.message


Request = struct(id=S.Number)


def _serving(response: Any, answer: Any) -> Any:
    def answers(chunk: tuple[Any, ...]) -> tuple[Any, ...]:
        return tuple(answer(request) for request in chunk)

    return B.decode(Request).map(answers).pipe_to(B.encode(response))


@fx.testing.effect
def test_duplex_encodes_requests_and_decodes_responses_with_different_schemas():
    """duplex encodes requests and decodes responses with different schemas"""
    response = struct(id=S.Number, name=S.String)

    def answer(request: Any) -> Any:
        return {"id": request["id"], "name": f"user-{request['id']}"}

    socket = _serving(response, answer)
    values = yield from (
        Stream.make({"id": 1}, {"id": 2})
        .pipe_through_channel(B.duplex(socket, input_schema=Request, output_schema=response))
        .run_collect()
    )
    assert values == [{"id": 1, "name": "user-1"}, {"id": 2, "name": "user-2"}]


@fx.testing.effect
def test_duplex_supports_the_data_last_call_shape():
    """duplex supports the data-last call shape"""
    response = struct(ok=S.Boolean)

    def answer(_: Any) -> Any:
        return {"ok": True}

    socket = _serving(response, answer)

    def wired(channel: Any) -> Any:
        return B.duplex(channel, input_schema=Request, output_schema=response)

    values = (
        yield from Stream.make({"id": 1}).pipe_through_channel(socket.pipe(wired)).run_collect()
    )
    assert values == [{"ok": True}]


@fx.testing.effect
def test_round_trips_fingerprint_mode_through_the_channel_path():
    """round-trips fingerprint mode through the channel path"""
    frames = yield from (
        Stream.make(ada, grace)
        .pipe_through_channel(B.encode(Person, fingerprint=True))
        .run_collect()
    )
    assert frames == [encode_fp(Person, ada) + encode_fp(Person, grace)]
    values = yield from (
        Stream.from_iterable(frames)
        .pipe_through_channel(B.decode(Person, fingerprint=True))
        .run_collect()
    )
    assert values == [ada, grace]


def _later(value: str) -> Any:
    return fx.sleep(0).as_(value)


AsyncName = S.String.pipe(
    S.decode_to(
        S.String,
        T.Transformation(
            G.transform_effect(lambda value, _: _later(value.upper())),
            G.transform_effect(lambda value, _: _later(value.lower())),
        ),
    )
)
AsyncPerson = struct(name=AsyncName, age=S.Number)


@fx.testing.live
def test_supports_async_transformations_on_encode_and_decode():
    """supports async transformations on encode and decode"""
    frames = (
        yield from Stream.make(ada, grace).pipe_through_channel(B.encode(AsyncPerson)).run_collect()
    )
    assert frames == [
        encode(Person, {"name": "ada", "age": 36}) + encode(Person, {"name": "grace", "age": 45})
    ]
    values = yield from (
        Stream.from_iterable(frames).pipe_through_channel(B.decode(AsyncPerson)).run_collect()
    )
    assert values == [{"name": "ADA", "age": 36}, {"name": "GRACE", "age": 45}]


@fx.testing.live
def test_supports_async_transformations_across_a_duplex_channel():
    """supports async transformations across a duplex channel"""
    from pyfect import channel as Channel

    values = yield from (
        Stream.make(ada)
        .pipe_through_channel(
            B.duplex(Channel.identity(), input_schema=AsyncPerson, output_schema=AsyncPerson)
        )
        .run_collect()
    )
    assert values == [{"name": "ADA", "age": 36}]


def _not_bob(value: str, _: object) -> Any:
    if value == "bob":
        return fx.fail(Issue.InvalidValue({"expected": "not bob"}, None))
    return _later(value)


@fx.testing.live
def test_emits_values_decoded_before_an_async_transformation_failure():
    """emits values decoded before an async transformation failure"""
    wire = struct(name=S.String)
    reader = struct(
        name=S.String.pipe(
            S.decode_to(S.String, T.Transformation(G.transform_effect(_not_bob), G.passthrough()))
        )
    )
    data = encode(wire, {"name": "ada"}) + encode(wire, {"name": "bob"})
    seen: list[object] = []

    def note(value: object) -> Any:
        return fx.sync(lambda: seen.append(value))

    error = yield from (
        Stream.make(data).pipe_through_channel(B.decode(reader)).tap(note).run_drain().flip()
    )
    assert seen == [{"name": "ada"}]
    assert "not bob" in error.message
