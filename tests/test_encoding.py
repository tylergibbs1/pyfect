"""The framers (``pyfect.encoding``) and ``Stream``'s channel and text
methods, beyond the Effect test ports. Each expected result was printed
by Effect's source under Node first, unless the test says it is
pyfect's own."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import channel, stream, testing
from pyfect.duration import millis
from pyfect.encoding import Json, json_array, ndjson, sse
from pyfect.encoding.json_array import JsonArrayError


@dataclass
class Outcome:
    values: list[Any]
    chunks: list[int]
    error: object = None


def _run(s: fx.Stream[Any, Any]) -> fx.Effect[Outcome]:
    outcome = Outcome([], [])

    def each(chunk: tuple[Any, ...]) -> fx.Effect[None]:
        def record() -> None:
            outcome.chunks.append(len(chunk))
            outcome.values.extend(chunk)

        return fx.sync(record)

    def failed(error: object) -> fx.Effect[Outcome]:
        outcome.error = error
        return fx.succeed(outcome)

    return s.run_for_each_array(each).as_(outcome).catch_all(failed)


def _bytes(*texts: str) -> fx.Stream[bytes]:
    return stream.from_arrays(*[(text.encode(),) for text in texts])


def _texts(*texts: str) -> fx.Stream[str]:
    return stream.from_arrays(*[(text,) for text in texts])


def _unpack(error: object) -> tuple[str | None, bool]:
    assert isinstance(error, ndjson.NdjsonError) and error.kind == "Unpack"
    return error.reason, error.unterminated


# --- Stream text and channel methods ----------------------------------------------


@testing.effect
def test_decode_text_reads_another_encoding():
    """pyfect's own: the codec is Python's."""
    text = yield from stream.make("café".encode("latin-1")).decode_text("latin-1").run_string()
    assert text == "café"


@testing.effect
def test_encode_text_encodes_each_string_as_utf8():
    chunks = yield from stream.make("Hello", " ", "Wörld").encode_text().run_collect()
    assert chunks == [b"Hello", b" ", "Wörld".encode()]


def _recovering() -> fx.Channel[tuple[str, ...], Never, None, tuple[str, ...], str, None]:
    """Writes what it reads; on a failure, writes ``"recovered"`` and ends."""
    ident: fx.Channel[tuple[str, ...], str, None, tuple[str, ...], str, None] = channel.identity()
    return ident.catch_all(lambda _e: channel.succeed(("recovered",)))


@testing.effect
def test_pipe_through_channel_lets_the_channel_see_the_failure():
    recovered = _recovering()
    values = stream.make("a").concat(stream.fail("boom")).pipe_through_channel(recovered)
    assert (yield from values.run_collect()) == ["a", "recovered"]


@testing.effect
def test_pipe_through_channel_or_fail_keeps_the_failure_from_the_channel():
    values = (
        stream.make("a").concat(stream.fail("boom")).pipe_through_channel_or_fail(_recovering())
    )
    assert (yield from _run(values)) == Outcome(["a"], [1], "boom")


def test_pipe_through_channel_rejects_a_non_channel():
    with pytest.raises(TypeError, match=r"^channel must be a Channel"):
        stream.make(1).pipe_through_channel(lambda: None)  # pyright: ignore[reportArgumentType]


# --- ndjson -----------------------------------------------------------------------


@testing.effect
def test_ndjson_decode_fails_on_a_blank_line_unless_told_to_skip_it():
    failing = yield from _run(_bytes("1\n\n2\n").pipe_through_channel(ndjson.decode()))
    assert failing.values == [1]
    assert _unpack(failing.error) == ("InvalidJson", False)
    skipping = ndjson.decode(ignore_empty_lines=True)
    assert (yield from _run(_bytes("1\n\n2\n").pipe_through_channel(skipping))) == Outcome(
        [1, 2], [2]
    )


@testing.effect
def test_ndjson_decode_marks_a_bad_last_line_without_a_break_unterminated():
    last = yield from _run(_bytes("1\n2\nx").pipe_through_channel(ndjson.decode()))
    assert (last.values, _unpack(last.error)) == ([1, 2], ("InvalidJson", True))
    middle = yield from _run(_bytes("1\n2\nx\n3").pipe_through_channel(ndjson.decode()))
    assert (middle.values, _unpack(middle.error)) == ([1, 2], ("InvalidJson", False))
    texts = yield from _run(_texts("1\n2", "\nx").pipe_through_channel(ndjson.decode_string()))
    assert (texts.values, _unpack(texts.error)) == ([1, 2], ("InvalidJson", True))


@testing.effect
def test_ndjson_decode_fails_on_a_line_that_is_not_utf8():
    data = stream.make(bytes([0x31, 0x0A, 0xFF, 0x0A]))
    outcome = yield from _run(data.pipe_through_channel(ndjson.decode()))
    assert (outcome.values, _unpack(outcome.error)) == ([1], ("InvalidUtf8", False))


@testing.effect
def test_ndjson_decode_skips_the_byte_order_mark_only_at_the_start():
    alone = yield from _run(stream.make(b"\xef\xbb\xbf").pipe_through_channel(ndjson.decode()))
    assert alone == Outcome([], [])
    record = stream.make(b"\xef\xbb\xbf1").pipe_through_channel(ndjson.decode())
    assert (yield from _run(record)) == Outcome([1], [1])
    later = yield from _run(_bytes("﻿1\n﻿2\n").pipe_through_channel(ndjson.decode()))
    assert (later.values, _unpack(later.error)) == ([1], ("InvalidJson", False))


@testing.effect
def test_ndjson_max_line_bytes_counts_a_line_across_chunks_without_its_break():
    over = _bytes("12345\r\n", "1234", "5\n").pipe_through_channel(ndjson.decode(max_line_bytes=4))
    outcome = yield from _run(over)
    assert (outcome.values, _unpack(outcome.error)) == ([], ("LineTooLarge", False))
    at = _bytes("1234\r\n", "\n12\r", "\r34\n").pipe_through_channel(
        ndjson.decode(max_line_bytes=4)
    )
    outcome = yield from _run(at)
    # The "\r\r" makes an empty line, which is not JSON.
    assert (outcome.values, _unpack(outcome.error)) == ([1234], ("InvalidJson", False))
    empty = _bytes("\n").pipe_through_channel(ndjson.decode(max_line_bytes=0))
    assert _unpack((yield from _run(empty)).error) == ("InvalidJson", False)


@testing.effect
def test_ndjson_decode_string_writes_a_chunk_per_input_chunk():
    texts = _texts("1\n2", "\n3", "\r\n4").pipe_through_channel(ndjson.decode_string())
    assert (yield from _run(texts)) == Outcome([1, 2, 3, 4], [1, 1, 1, 1])


@testing.effect
def test_ndjson_encode_string_writes_one_string_per_chunk():
    values = stream.make(1, "a", {"b": [None]}, True).rechunk(2)
    lines = yield from _run(values.pipe_through_channel(ndjson.encode_string()))
    assert lines == Outcome(['1\n"a"\n', '{"b":[null]}\ntrue\n'], [1, 1])


@testing.effect
def test_ndjson_reads_nan_as_invalid_and_writes_it_as_null():
    """``JSON.parse`` rejects ``NaN`` and ``JSON.stringify`` writes it as
    ``null`` (Effect 4.1.2 under Node: ``"null\\n"``)."""
    parsed = yield from _run(_bytes("NaN\n").pipe_through_channel(ndjson.decode()))
    assert _unpack(parsed.error) == ("InvalidJson", False)
    written = yield from _run(stream.make(float("nan")).pipe_through_channel(ndjson.encode()))
    assert written.values == [b"null\n"]


@testing.effect
def test_ndjson_encode_escapes_lone_surrogates_as_json_stringify_does():
    """``JSON.stringify("\\ud83d")`` is ``'"\\\\ud83d"'`` (checked under Node):
    a lone surrogate is escaped, so the line encodes to UTF-8 and parses
    back to the same string; a pair is written as is."""
    lone = "\ud83d"
    written = yield from _run(
        stream.make({"s": lone, "pair": "\U0001f600"}).pipe_through_channel(ndjson.encode())
    )
    assert written == Outcome([b'{"s":"\\ud83d","pair":"\xf0\x9f\x98\x80"}\n'], [1])
    parsed = yield from _run(stream.make(*written.values).pipe_through_channel(ndjson.decode()))
    assert parsed.values == [{"s": lone, "pair": "\U0001f600"}]


type _Duplexed[T] = fx.Channel[
    tuple[T, ...], ndjson.NdjsonError, None, tuple[T, ...], ndjson.NdjsonError, None
]


@testing.effect
def test_ndjson_duplex_encodes_outgoing_values_and_decodes_the_replies():
    echo: _Duplexed[bytes] = channel.identity()
    items: list[Json] = [{"id": 1}, [2]]
    values = stream.from_iterable(items)
    replies = yield from values.pipe_through_channel(ndjson.duplex(echo)).run_collect()
    assert replies == [{"id": 1}, [2]]
    text_echo: _Duplexed[str] = channel.identity()
    replies = yield from values.pipe_through_channel(ndjson.duplex_string(text_echo)).run_collect()
    assert replies == [{"id": 1}, [2]]


# --- json_array -------------------------------------------------------------------


def _array_error(s: fx.Stream[Any, Any], **options: Any) -> fx.Effect[tuple[str, int | None, str]]:
    def describe(error: object) -> tuple[str, int | None, str]:
        assert isinstance(error, JsonArrayError)
        return error.kind, error.offset, error.message

    decoded = s.pipe_through_channel(json_array.decode_string(**options))
    ended = fx.die(AssertionError("the stream ended"))
    return decoded.run_drain().flip().catch_all(lambda _: ended).map(describe)


@pytest.mark.parametrize(
    ("chunks", "options", "expected"),
    [
        (['[1, {"a": x}]'], {}, ("Syntax", 4, "Invalid JSON value")),
        (['{"a": 1}'], {}, ("Pointer", 0, 'Expected an array at ""')),
        (['{"a": 1}'], {"pointer": "/b"}, ("Pointer", 7, 'No value at "/b"')),
        (['{"a": {"b": 1}}'], {"pointer": "/a/b"}, ("Pointer", 12, 'Expected an array at "/a/b"')),
        (["[[1,2],[3,[4]]]"], {"max_depth": 1}, ("Limit", 7, "Element exceeds max_depth of 1")),
        (
            ['{"x": [[1]], "a": []}'],
            {"pointer": "/a", "max_depth": 1},
            ("Limit", 6, 'Value outside the selected array at "/x" exceeds max_depth of 1'),
        ),
        (
            ['{"abcdefgh": 1, "a": []}'],
            {"pointer": "/a", "max_element_size": 6},
            ("Limit", 1, 'Key in "" exceeds max_element_size of 6'),
        ),
        (["[1] 2"], {}, ("Syntax", 4, "Unexpected content after the document")),
        (["[1,", "2,", "x]"], {}, ("Syntax", 5, 'Unexpected character "x"')),
        (
            ['{"a": [1], "a": [2]}'],
            {"pointer": "/a"},
            ("Pointer", 14, 'Duplicate key "a" along the pointer'),
        ),
        (["[0]"], {"pointer": "/1"}, ("Pointer", 2, 'No value at "/1"')),
        (["[", ""], {}, ("Syntax", 1, "Unexpected end of input")),
        (
            ['{"a": [1, 2]} x'],
            {"pointer": "/a"},
            ("Syntax", 14, "Unexpected content after the document"),
        ),
        (
            ['[{"k": "abcdefg"}]'],
            {"max_element_size": 5},
            ("Limit", 1, "Element exceeds max_element_size of 5"),
        ),
    ],
)
def test_json_array_errors_name_the_value_and_its_offset(
    chunks: list[str], options: dict[str, Any], expected: tuple[str, int | None, str]
):
    assert fx.run_blocking(_array_error(_texts(*chunks), **options)) == expected


@testing.effect
def test_json_array_streams_elements_split_across_chunks():
    index = _texts("[0, [5, 6], 7]").pipe_through_channel(json_array.decode_string(pointer="/1"))
    assert (yield from _run(index)) == Outcome([5, 6], [2])
    escaped = _texts('["ab\\', '"c", "d"]').pipe_through_channel(json_array.decode_string())
    assert (yield from _run(escaped)) == Outcome(['ab"c', "d"], [2])
    number = _texts("[1, 2", "3]").pipe_through_channel(json_array.decode_string())
    assert (yield from _run(number)) == Outcome([1, 23], [1, 1])


@testing.effect
def test_json_array_encode_writes_a_string_per_chunk():
    values = stream.make(1, 2, 3).rechunk(2)
    texts = yield from _run(values.pipe_through_channel(json_array.encode_string()))
    assert texts == Outcome(["[1,2", ",3", "]"], [1, 1, 1])
    data = yield from values.pipe_through_channel(json_array.encode()).run_bytes()
    assert data == b"[1,2,3]"


@testing.effect
def test_json_array_rejects_nan_and_infinity():
    """pyfect's own (see ``test_ndjson_rejects_nan_both_ways``)."""
    for text in ["[[NaN]]", '{"x": [Infinity], "a": []}', "[-Infinity]"]:
        error = (
            yield from _texts(text)
            .pipe_through_channel(json_array.decode_string(pointer="/a" if "x" in text else ""))
            .run_drain()
            .flip()
        )
        assert isinstance(error, JsonArrayError) and error.kind == "Syntax", text


# --- sse --------------------------------------------------------------------------


@testing.effect
def test_sse_decode_writes_the_events_before_a_retry_then_fails_with_it():
    texts = _texts("data: a\n\nretry: 1500\ndata: b\n\n", "data: c\n\n")
    outcome = yield from _run(texts.pipe_through_channel(sse.decode()))
    assert outcome.values == [sse.Event(data="a"), sse.Event(data="b")]
    assert outcome.error == sse.Retry(millis(1500))
    retry = yield from _run(_texts("id: 7\nretry: 20\n").pipe_through_channel(sse.decode()))
    assert retry == Outcome([], [], sse.Retry(millis(20), "7"))


@testing.effect
def test_sse_decode_drops_an_event_without_data_unless_it_is_named_and_asked_for():
    named = _texts("event: done\n\n")
    assert (yield from _run(named.pipe_through_channel(sse.decode()))) == Outcome([], [])
    asked = sse.decode(dispatch_empty_named_events=True)
    outcome = yield from _run(named.pipe_through_channel(asked))
    assert outcome == Outcome([sse.Event(event="done", data="")], [1])


@testing.effect
def test_sse_decode_ignores_comments_unknown_fields_and_ids_with_nul():
    texts = _texts(
        ": comment\ndata\n\ndata:x\nfoo: bar\nid: a\x00b\n\n", "data: a\r\rdata: b\r\n\r\n"
    )
    events = yield from texts.pipe_through_channel(sse.decode()).run_collect()
    assert events == [
        sse.Event(data=""),
        sse.Event(data="x"),
        sse.Event(data="a"),
        sse.Event(data="b"),
    ]


def test_sse_ignores_a_retry_in_non_ascii_digits():
    """pyfect's own: ``str.isdigit`` takes any Unicode digit; Effect's
    ``/^\\d+$/`` takes ASCII ones."""
    events: list[sse.AnyEvent] = []
    sse.make_parser(events.append).feed("retry: ١٢٣\n")
    assert events == []


@testing.effect
def test_sse_encode_writes_events_and_ends_with_a_retry():
    events = stream.make(
        sse.Event(event="up", id="1", data="a\nb"), sse.Event(data="")
    ).pipe_through_channel(sse.encode())
    assert (yield from _run(events)) == Outcome(
        ["id: 1\nevent: up\ndata: a\ndata: b\n\n", "data: \n\n"], [2]
    )
    retried = stream.make(sse.Event(data="x")).concat(
        stream.fail(sse.Retry(timedelta(seconds=0.25)))
    )
    outcome = yield from _run(retried.pipe_through_channel(sse.encode()))
    assert outcome == Outcome(["data: x\n\n", "retry: 250\n\n"], [1, 1])


@testing.effect
def test_sse_encode_lets_other_failures_pass_by_with_pipe_through_channel_or_fail():
    failing = stream.make(sse.Event(data="a")).concat(stream.fail("boom"))
    outcome = yield from _run(failing.pipe_through_channel_or_fail(sse.encode()))
    assert outcome == Outcome(["data: a\n\n"], [1], "boom")


def test_sse_write_keeps_fractions_of_a_millisecond():
    assert sse.write(sse.Retry(timedelta(microseconds=1500))) == "retry: 1.5\n\n"


@pytest.mark.parametrize("value", ["a\nevent: failure", "a\rretry: 1", "a\r\ndata: x"])
def test_an_sse_event_name_or_id_with_a_line_break_is_written_without_it(value: str):
    # A line break would start another field: an injected data:, retry: or event:.
    # Effect 4.1.2 removes it on write (it was a ValueError here before 4.1.2).
    flat = value.replace("\r", "").replace("\n", "")
    assert sse.write(sse.Event(data="x", event=value)) == f"event: {flat}\ndata: x\n\n"
    assert sse.write(sse.Event(data="x", id=value)) == f"id: {flat}\ndata: x\n\n"


def test_sse_event_data_lines_are_each_written_as_data():
    assert sse.write(sse.Event(data="a\nretry: 1", id="7")) == "id: 7\ndata: a\ndata: retry: 1\n\n"
