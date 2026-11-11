"""Schema decoding of untrusted values: JSON documents (also through the JSON
and Go JSON codecs), binary frames, and the ``...FromString`` codecs. Decoding
fails only with ``SchemaError``; a value that decodes encodes and decodes back
to itself."""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from pyfect import _json_text
from pyfect import schema as S
from pyfect.encoding import schema_binary as B

from ._harness import Crash, outcome, raises_only, target, text


class _Tree(TypedDict):
    label: str
    children: tuple[Any, ...]


def _tree() -> Any:
    return _TREE


_TREE: Any = S.Struct(_Tree, label=S.String, children=S.Array(S.suspend(_tree)))


class _Sink(TypedDict):
    n: int
    s: str
    f: float
    b: bool
    items: tuple[object, ...]
    counts: dict[str, tuple[int, ...]]
    pair: tuple[str, float]
    kind: str
    when: NotRequired[object]
    span: NotRequired[object]
    amount: NotRequired[object]
    tree: NotRequired[_Tree]
    raw: NotRequired[object]


SINK: Any = S.Struct(
    _Sink,
    n=S.Int,
    s=S.NonEmptyString,
    f=S.Finite,
    b=S.Boolean,
    items=S.Array(S.Union(S.String, S.Number, S.Null, S.Boolean)),
    counts=S.Record(S.String, S.Array(S.Int)),
    pair=S.Tuple(S.String, S.Number),
    kind=S.Literals("a", "b"),
    when=S.DateTimeUtcFromString,
    span=S.DurationFromString,
    amount=S.BigDecimalFromString,
    tree=_TREE,
    raw=S.Json,
)


def _decoded(schema: Any, value: object) -> object:
    """The decoded value, or ``None`` for a ``SchemaError``."""
    return outcome(S.decode_unknown_exit(schema)(value), S.SchemaError)


def _lone_surrogate(value: object) -> bool:
    return isinstance(value, str) and any(0xD800 <= ord(char) <= 0xDFFF for char in value)


def _round_trip(schema: Any, value: object) -> None:
    decoded = _decoded(schema, value)
    if decoded is None:
        return
    if schema is S.StringFromUriComponent and _lone_surrogate(decoded):
        return  # encodeURIComponent throws on a lone surrogate, in Effect too: a defect
    encoded = S.encode_unknown_sync(schema)(decoded)
    again = S.decode_unknown_sync(schema)(encoded)
    if again != decoded and repr(again) != repr(decoded):
        raise Crash(f"{decoded!r} encodes to {encoded!r}, which decodes to {again!r}")


@target("schema_json")
def schema_json(data: bytes) -> None:
    """A JSON document decoded by a schema of most kinds, directly and through
    ``to_codec_json`` and ``to_codec_go_json``."""
    value = raises_only(lambda: _json_text.parse(data), ValueError)
    if value is None and data.strip() != b"null":
        return
    _round_trip(SINK, value)
    _round_trip(S.to_codec_json(SINK), value)
    _round_trip(S.to_codec_go_json(SINK), value)
    _round_trip(S.UnknownFromJsonString, text(data))


@target("schema_binary")
def schema_binary(data: bytes) -> None:
    """A binary frame read by the default, strict and fingerprint codecs."""
    for codec in (B.to_codec(SINK), B.to_codec_strict(SINK), B.to_codec(SINK, fingerprint=True)):
        _round_trip(codec, data)


_FROM_STRING: tuple[Any, ...] = (
    S.BigDecimalFromString,
    S.BigIntFromString,
    S.ByteSizeFromString,
    S.DateTimeUtcFromString,
    S.DateTimeZonedFromString,
    S.DomainNameFromString,
    S.DurationFromIsoString,
    S.DurationFromString,
    S.FiniteFromString,
    S.NumberFromString,
    S.HostFromString,
    S.HostPortFromString,
    S.InetAddressFromString,
    S.IpAddressFromString,
    S.IpNetworkFromString,
    S.IpInterfaceFromString,
    S.Ipv6AddressFromString,
    S.ScopedIpv6LiteralFromString,
    S.MacAddressFromString,
    S.SemVerFromString,
    S.SemVerRangeFromString,
    S.TimeZoneFromString,
    S.URLFromString,
    S.BytesFromBase64,
    S.BytesFromBase64Url,
    S.BytesFromHex,
    S.StringFromUriComponent,
    S.UnixPathAddressFromString,
)


@target("schema_strings")
def schema_strings(data: bytes) -> None:
    """The first byte picks a ``...FromString`` codec for the rest."""
    if not data:
        return
    _round_trip(_FROM_STRING[data[0] % len(_FROM_STRING)], text(data[1:]))
