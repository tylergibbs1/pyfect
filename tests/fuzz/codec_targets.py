"""Text and binary codecs: JSON and its relatives, base64/hex, CSV, NDJSON,
SSE, XML, TOML, YAML, INI and the tar and zip archive decoders."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pyfect import _json_text, stream
from pyfect._binary_codecs import (
    EncodingError,
    base64_decode,
    base64_encode,
    base64_url_decode,
    base64_url_encode,
    hex_decode,
    hex_encode,
)
from pyfect.encoding import csv, ini, json5, json_array, jsonc, ndjson, sse, toml, xml, yaml
from pyfect.encoding import tar as Tar
from pyfect.encoding import zip as Zip
from pyfect.encoding.csv import CsvError
from pyfect.encoding.json_array import JsonArrayError
from pyfect.encoding.ndjson import NdjsonError
from pyfect.encoding.sse import Retry, SseError
from pyfect.encoding.tar import TarError
from pyfect.encoding.xml import XmlError
from pyfect.encoding.zip import ZipError
from pyfect.result import Ok, Result

from ._harness import Crash, chunks, raises_only, run_channel, settle, target, text


@target("json")
def json(data: bytes) -> None:
    """``JSON.parse`` (``ValueError`` only, deep nesting included); what it
    reads, written as JavaScript writes it and read again, is written the same."""
    value = raises_only(lambda: _json_text.parse(data), ValueError)
    if value is None:
        return
    written = _json_text.stringify(value, null_non_finite=True)
    if _json_text.stringify(_json_text.parse(written), null_non_finite=True) != written:
        raise Crash(f"JSON does not round-trip: {written!r}")


@target("json5")
def json5_(data: bytes) -> None:
    json5.parse(text(data))
    jsonc.parse(text(data))


def _round_trips(
    value: str,
    encode: Callable[[bytes], str],
    decode: Callable[[str], Result[bytes, EncodingError]],
) -> None:
    decoded = decode(value)
    if isinstance(decoded, Ok):
        again = decode(encode(decoded.value))
        if not (isinstance(again, Ok) and again.value == decoded.value):
            raise Crash(f"{decoded.value!r} does not round-trip: {again!r}")


@target("base64_hex")
def base64_hex(data: bytes) -> None:
    """Base64, Base64Url and hex decoding; a decoded value encodes and
    decodes back to itself."""
    value = text(data)
    _round_trips(value, base64_encode, base64_decode)
    _round_trips(value, base64_url_encode, base64_url_decode)
    _round_trips(value, hex_encode, hex_decode)


@target("toml_yaml_ini")
def toml_yaml_ini(data: bytes) -> None:
    """The first byte picks the format."""
    if not data:
        return
    value = text(data[1:])
    match data[0] % 3:
        case 0:
            toml.parse(value)
        case 1:
            raises_only(lambda: yaml.parse(value), ValueError)
        case _:
            raises_only(lambda: ini.parse(value), TypeError)


@target("csv")
def csv_(data: bytes) -> None:
    headers = bool(data) and data[0] & 0x40 != 0
    channel = csv.decode(headers=headers, max_record_size=256)
    settle(run_channel(chunks(data), channel), CsvError)


@target("ndjson")
def ndjson_(data: bytes) -> None:
    settle(run_channel(chunks(data), ndjson.decode()), NdjsonError)


@target("json_array")
def json_array_(data: bytes) -> None:
    pieces = [text(piece) for piece in chunks(data)]
    channel = json_array.decode_string(pointer="/a", max_depth=16, max_element_size=256)
    settle(run_channel(pieces, channel), JsonArrayError)
    settle(run_channel(pieces, json_array.decode_string()), JsonArrayError)


@target("sse")
def sse_(data: bytes) -> None:
    pieces = [text(piece) for piece in chunks(data)]
    settle(run_channel(pieces, sse.decode(max_event_size=256)), Retry, SseError)


@target("xml")
def xml_(data: bytes) -> None:
    """UTF-8 XML with small limits, and its elements under ``/a``."""
    channel = xml.decode(max_token_size=512, max_depth=16)
    events = settle(run_channel(chunks(data), channel), XmlError)
    if events is None:
        return
    elements = (
        stream.from_iterable(events, chunk_size=1)
        .pipe_through_channel(xml.elements(["a"], max_element_size=1024))
        .run_collect()
    )
    settle(elements, XmlError)


def _archive(data: bytes, channel: Any, error: type) -> None:
    """Every entry's body read in full (and counted)."""
    total = [0]

    def read(entry: Any) -> Any:
        def counted(body: bytes) -> None:
            total[0] += len(body)

        return entry.body.run_bytes().map(counted)

    entries = (
        stream.from_iterable(chunks(data), chunk_size=1)
        .pipe_through_channel(channel)
        .map_effect(read)
        .run_drain()
    )
    settle(entries, error)


@target("tar")
def tar(data: bytes) -> None:
    _archive(data, Tar.decode(), TarError)


@target("zip")
def zip_(data: bytes) -> None:
    _archive(data, Zip.decode(), ZipError)
