"""Bytes Effect wrote under Node (``schema_binary_wire.ts``) decode here, and the
values here write the same bytes. Not Effect test titles: the wire contract."""
# pyright: reportPrivateUsage=false, reportUnknownMemberType=false

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from pyfect import big_decimal as bd
from pyfect import duration, redacted
from pyfect import exit as Exit
from pyfect import schema as S
from pyfect.cause import Cause, Fail, Interrupt
from pyfect.encoding import schema_binary as B
from pyfect.option import Some
from pyfect.result import Err
from pyfect.rpc._encoded_schema import EncodedSchema

from ._schema_binary import Opt, struct
from ._schema_binary_frames import DICTIONARY, FRAMES, MANY, RPC

AnyDefect: Any = S.Unknown
Int = S.Number.check(S.is_int())
Person = struct(name=S.String, age=S.Number, active=S.Boolean, nickname=Opt(S.String))
Row = struct(
    id=S.String,
    label=S.String,
    tags=S.Array(S.String),
    attributes=S.Record(S.String, S.String),
    score=Opt(S.Number),
)
Tagged = S.Union(
    struct(_tag=S.Literal("A"), n=S.Number), struct(_tag=S.Literal("B"), text=S.String)
)
Mixed = S.Union(S.String, S.Number, struct(n=S.Boolean))
Natives = struct(
    option=S.Option(S.String),
    none=S.Option(S.String),
    result=S.Result(S.Number, S.String),
    big=S.BigInt,
    bytes=S.Bytes,
    when=S.DateTimeUtc,
    zoned=S.DateTimeZoned,
    offset=S.DateTimeZoned,
    duration=S.Duration,
    decimal=S.BigDecimal,
    secret=S.Redacted(S.String),
    json=S.Unknown,
)
_second = datetime.fromtimestamp(1, UTC)
_cause: Cause[str] = Cause((Fail("boom"), Interrupt(7), Interrupt(None)))
_node: Any = struct(v=S.Number, children=S.Array(S.suspend(lambda: _node)))
_rows = tuple(
    {
        "id": f"row-{i}",
        "label": "odd" if i % 2 else "even",
        "tags": ("blue",) if i % 2 else ("red", "blue"),
        "attributes": {"region": "eu", "worker": f"w{i}"},
        **({"score": 1.5} if i == 2 else {}),
    }
    for i in range(4)
)

CASES: dict[str, tuple[Any, Any]] = {
    "number_ints": (S.Array(S.Number), (0, 1, -1, 1000)),
    "number_decimals": (S.Array(S.Number), (1.5, -0.25, 12.75)),
    "number_floats": (S.Array(S.Number), (1, math.pi, 1e300)),
    "int_array": (S.Array(Int), (1, -2, 3)),
    "person": (Person, {"name": "Ada", "age": 36, "active": True}),
    "person_decimal": (Person, {"name": "Ada", "age": 36.5, "active": False, "nickname": "A"}),
    "rows": (S.Array(Row), _rows),
    "record": (S.Record(S.String, S.Number), {"b": 2, "a": 1, "é": 3}),
    "tagged_a": (Tagged, {"_tag": "A", "n": 1.5}),
    "tagged_b": (Tagged, {"_tag": "B", "text": "x"}),
    "mixed_string": (Mixed, "x"),
    "mixed_number": (Mixed, 1.5),
    "mixed_struct": (Mixed, {"n": True}),
    "tuple": (S.Tuple(S.Boolean, S.String), (True, "x")),
    "natives": (
        Natives,
        {
            "option": Some("x"),
            "none": None,
            "result": Err("boom"),
            "big": -(2**70),
            "bytes": bytes((1, 2, 3)),
            "when": _second,
            "zoned": _second.astimezone(ZoneInfo("Europe/London")),
            "offset": _second.astimezone(timezone(timedelta(hours=1))),
            "duration": duration.nanos(1_500_000_000),
            "decimal": bd.make(123, 2),
            "secret": redacted.make("hush"),
            "json": {"nested": [1, "two", True, None]},
        },
    ),
    "exit_ok": (S.Exit(S.Number, S.String, AnyDefect), Exit.succeed(42)),
    "exit_cause": (S.Exit(S.Number, S.String, AnyDefect), Exit.fail_cause(_cause)),
    "cause": (S.Cause(S.String, AnyDefect), _cause),
    "recursive": (
        _node,
        {
            "v": 1,
            "children": ({"v": 2, "children": ()}, {"v": 3, "children": ()}),
        },
    ),
    "field_id": (
        struct(n=S.Number.pipe(B.field_id(7)), s=S.String.pipe(B.field_id(200))),
        {"n": 1, "s": "x"},
    ),
}
_same_cases = [(name, mode) for name in CASES for mode in ("default", "fingerprint")]


def _same(left: object, right: object) -> None:
    """Equal, reading a ``Redacted`` by its value and a cause by its reasons."""
    if isinstance(right, dict):
        assert isinstance(left, dict)
        assert left.keys() == right.keys()
        for key in right:  # pyright: ignore[reportUnknownVariableType]
            _same(left[key], right[key])  # pyright: ignore[reportUnknownArgumentType]
        return
    if isinstance(right, redacted.Redacted):
        assert redacted.value(left) == redacted.value(right)  # pyright: ignore[reportUnknownArgumentType, reportArgumentType]
        return
    if isinstance(right, bd.BigDecimal):
        assert isinstance(left, bd.BigDecimal)
        assert (left.value, left.scale) == (right.value, right.scale)
        return
    assert left == right


@pytest.mark.parametrize(("name", "mode"), _same_cases)
def test_writes_effects_bytes(name: str, mode: str) -> None:
    schema, value = CASES[name]
    fingerprint = mode == "fingerprint"
    written = S.encode_unknown_sync(B.to_codec(schema, fingerprint=fingerprint))(value)
    assert written.hex() == FRAMES[name][mode]


@pytest.mark.parametrize(("name", "mode"), _same_cases)
def test_reads_effects_bytes(name: str, mode: str) -> None:
    schema, value = CASES[name]
    fingerprint = mode == "fingerprint"
    decode = S.decode_unknown_sync(B.to_codec(schema, fingerprint=fingerprint))
    _same(decode(bytes.fromhex(FRAMES[name][mode])), value)


Message = struct(tag=S.String, traceId=S.String, body=S.String, n=S.Number)
_messages = [
    {
        "tag": ("Search", "Get", "Delete")[i % 3],
        "traceId": "0123456789abcdef0123456789abcdef",
        "body": f"body {i % 2}",
        "n": i,
    }
    for i in range(5)
]


def test_dictionary_streams_match_effects() -> None:
    writer = B.encoder(Message, dictionary=True)
    assert [writer.encode(m).hex() for m in _messages] == DICTIONARY
    reader = B.parser(Message, dictionary=True)
    assert [v for h in DICTIONARY for v in reader.feed_sync(bytes.fromhex(h))] == _messages


def test_batched_frames_match_effects() -> None:
    people = [
        {"name": "Ada", "age": 36, "active": True},
        {"name": "Grace", "age": 45, "active": False},
    ]
    assert B.encode_many_unknown_sync(Person)(people).hex() == MANY
    assert B.parser(Person).feed_sync(bytes.fromhex(MANY)) == people


_payload = bytes((9, 8))
_RPC_MESSAGES: dict[str, dict[str, Any]] = {
    "request": {
        "_tag": "Request",
        "id": "1",
        "tag": "Get",
        "payload": _payload,
        "headers": (("a", "b"),),
    },
    "request_full": {
        "_tag": "Request",
        "id": 7,
        "tag": "Get",
        "payload": _payload,
        "headers": (),
        "isNotification": True,
        "traceId": "t",
        "spanId": "s",
        "sampled": True,
    },
    "ack": {"_tag": "Ack", "requestId": "1"},
    "interrupt": {"_tag": "Interrupt", "requestId": 7},
    "ping": {"_tag": "Ping"},
    "eof": {"_tag": "Eof"},
    "chunk": {"_tag": "Chunk", "requestId": "1", "values": _payload},
    "exit": {"_tag": "Exit", "requestId": "1", "exit": _payload},
    "defect": {"_tag": "Defect", "defect": _payload},
    "pong": {"_tag": "Pong"},
}


@pytest.mark.parametrize("name", list(_RPC_MESSAGES))
def test_rpc_envelopes_match_effects(name: str) -> None:
    writer = B.encoder(EncodedSchema, fingerprint=True)
    assert writer.encode(_RPC_MESSAGES[name]).hex() == RPC[name]
    reader = B.parser(EncodedSchema, fingerprint=True)
    assert reader.feed_sync(bytes.fromhex(RPC[name])) == [_RPC_MESSAGES[name]]
