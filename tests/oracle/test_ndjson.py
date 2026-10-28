"""Ports of Effect's ``encoding/Ndjson.test.ts``.

Each test's docstring is the Effect test title. ``Uint8Array`` is
``bytes`` and ``Stream.pipeThroughChannel`` is the
``pipe_through_channel`` method.

Adapted, with the reason:

- "fails for values without a JSON representation" passes a function, an
  object and a set, which ``json.dumps`` cannot write, where Effect passes
  ``undefined``, a function and a symbol (``JSON.stringify`` gives
  ``undefined`` for them).
- "identifies Ndjson errors" checks with ``isinstance``: type guards are
  ``isinstance`` in pyfect, so there is no ``is_ndjson_error``.
"""

from typing import Any, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import stream, testing
from pyfect.encoding import Json, ndjson


def _collect[E](
    s: fx.Stream[Json, E],
) -> fx.Effect[tuple[list[Json], E], None]:
    values: list[Json] = []

    @fx.gen
    def run():
        error = yield from s.run_for_each(
            lambda value: fx.sync(lambda: values.append(value))
        ).flip()
        return values, error

    return run


@testing.effect
def test_fails_for_values_without_a_json_representation():
    """fails for values without a JSON representation"""
    inputs: list[Any] = [lambda: None, object(), {1, 2}]
    for value in inputs:
        values = stream.make(value).pipe_through_channel(ndjson.encode_string())
        error = yield from values.run_collect().flip()
        assert isinstance(error, ndjson.NdjsonError)
        assert error.kind == "Pack"


@testing.effect
def test_decode_handles_a_leading_bom_crlf_split_across_chunks_and_a_bare_cr():
    """decode handles a leading BOM, CRLF split across chunks and a bare CR"""
    data = stream.from_arrays((b"\xef\xbb\xbf" + b"1\r",), (b"\n2\r",), (b"3\n",))
    values = yield from data.pipe_through_channel(ndjson.decode()).run_collect()
    assert values == [1, 2, 3]


@testing.effect
def test_decode_fails_a_line_over_max_line_bytes_before_reading_the_rest_of_it():
    """decode fails a line over maxLineBytes before reading the rest of it"""
    data = stream.make('"é"\r\n"éé'.encode()).concat(stream.fail("read past the oversized line"))
    values, error = yield from _collect(data.pipe_through_channel(ndjson.decode(max_line_bytes=4)))
    assert values == ["é"]
    assert isinstance(error, ndjson.NdjsonError)
    assert error.reason == "LineTooLarge"


def test_identifies_ndjson_errors():
    """identifies Ndjson errors"""
    error: object = ndjson.NdjsonError("Pack", RuntimeError("boom"))
    assert isinstance(error, ndjson.NdjsonError)
    assert not isinstance({"_tag": "NdjsonError"}, ndjson.NdjsonError)
    assert not isinstance(None, ndjson.NdjsonError)


class _Foo(TypedDict):
    foo: str


@testing.effect
def test_decode_schema_decodes_records_split_across_uint8_array_chunks():
    """decodeSchema decodes records split across Uint8Array chunks"""
    messages = yield from (
        stream.make(b'{"foo":"bar"}\n')
        .pipe_through_channel(ndjson.decode_schema(S.Struct(_Foo)))
        .run_collect()
    )
    assert messages == [{"foo": "bar"}]
