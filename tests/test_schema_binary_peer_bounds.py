"""SchemaBinary frames from a peer cost work in proportion to their size."""

from typing import Any, TypedDict

import pytest
from _growth import Make, Work, assert_near_linear

import pyfect as fx
from pyfect import schema as S
from pyfect.encoding import schema_binary
from pyfect.rpc.serialization import make_schema_binary


def _uvarint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if not n:
            out.append(b)
            return bytes(out)
        out.append(b | 0x80)


class _Number(TypedDict):
    n: float


class _Big(TypedDict):
    n: int


def _with_run(schema: S.Codec[Any, Any, Any, Any], value: object) -> Make:
    codec = make_schema_binary().codec_for(schema)
    decode = S.decode_unknown_exit(codec)
    base: bytes = S.encode_unknown_sync(codec)(value)
    # A one-byte frame length, the body, then the varint 0x02 that ends it.
    assert base[0] == len(base) - 1
    assert base[-1] == 0x02
    body = base[1:-1]

    def sized(run: int) -> Work:
        payload = body + b"\xff" * run + b"\x02"
        frame = _uvarint(len(payload)) + payload
        return lambda: decode(frame)

    return sized


def test_a_long_number_varint_fails_after_the_longest_finite_double() -> None:
    sized = _with_run(S.Struct(_Number), {"n": 1})
    assert isinstance(sized(148)(), fx.Failure)
    assert_near_linear(sized, 16_000, 8 * 16_000, bound=32, floor=0.0032)


def test_a_long_big_int_varint_decodes_in_near_linear_time() -> None:
    codec = make_schema_binary().codec_for(S.Struct(_Big, n=S.BigInt))
    decode = S.decode_unknown_sync(codec)
    encode = S.encode_unknown_sync(codec)

    def sized(groups: int) -> Work:
        value = (1 << (7 * groups)) - 1
        frame = encode({"n": value})
        assert len(frame) > groups
        return lambda: decode(frame)["n"] == value

    assert sized(1000)()
    assert_near_linear(sized, 16_000, 8 * 16_000, bound=32, floor=0.0032)


class _Row(TypedDict):
    name: str


class _Rows(TypedDict):
    rows: tuple[_Row, ...]


_CHECKED = S.Struct(_Rows, rows=S.Array(S.Struct(_Row, name=S.String.check(S.is_lowercased()))))


def test_back_references_name_at_most_max_expanded_size_when_a_schema_pass_runs() -> None:
    shared = "x" * 4096
    frame = schema_binary.to_codec(_CHECKED)
    encoded = S.encode_unknown_sync(frame)({"rows": [{"name": shared}] * 100})
    assert len(encoded) < 4096 + 1000
    small = schema_binary.to_codec(_CHECKED, max_expanded_size=64 * 1024)
    with pytest.raises(S.SchemaError, match="max_expanded_size"):
        S.decode_unknown_sync(small)(encoded)
    assert len(S.decode_unknown_sync(frame)(encoded)["rows"]) == 100
    unbounded = schema_binary.to_codec(_CHECKED, max_expanded_size=None)
    assert len(S.decode_unknown_sync(unbounded)(encoded)["rows"]) == 100


def test_rpc_payloads_with_checks_bound_their_back_references() -> None:
    codec = make_schema_binary(max_expanded_size=1024 * 1024).codec_for(_CHECKED)
    encoded = S.encode_unknown_sync(codec)({"rows": [{"name": "x" * 512 * 1024}] * 8})
    assert isinstance(S.decode_unknown_exit(codec)(encoded), fx.Failure)


def test_the_parser_bounds_back_references_too() -> None:
    encoded = S.encode_unknown_sync(schema_binary.to_codec(_CHECKED))(
        {"rows": [{"name": "x" * 4096}] * 100}
    )
    parser = schema_binary.parser(_CHECKED, max_expanded_size=64 * 1024)
    with pytest.raises(S.SchemaError, match="max_expanded_size"):
        parser.feed_sync(encoded)
    assert len(schema_binary.parser(_CHECKED).feed_sync(encoded)) == 1
