"""Fingerprint mode's layout hash, over the compiled layout graph with cycle
back-edge distances (Effect's ``layoutFingerprint``)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache

from pyfect._js import text_encode
from pyfect.encoding.schema_binary import _layout as L
from pyfect.encoding.schema_binary import _wire as W
from pyfect.encoding.schema_binary._literals import literal_kind_code, literal_text

_LEAF_CODES = {
    "bool": 1,
    "null": 2,
    "undefined": 3,
    "number": 4,
    "int": 5,
    "string": 6,
    "bytes": 8,
    "bigint": 9,
    "json": 10,
    "duration": 11,
    "bigDecimal": 12,
    "dateTimeZoned": 13,
    "dateTimeUtc": 15,
    "i32": 26,
    "u32": 27,
    "i64": 28,
    "u64": 29,
}
_BACK_EDGE = 0
_NEVER = 16
_STRUCT = 17
_ARRAY = 18
_UNION = 19
_OPTION = 20
_RESULT = 21
_EXIT = 22
_CAUSE = 23
_CAUSE_REASON = 24
_LITERAL = 25


def layout_fingerprint(root: L.Layout) -> int:  # noqa: PLR0915
    cache: dict[int, int] = {}
    stack: list[L.Layout] = []
    never_escapes = 2**62
    escape = never_escapes

    def go(layout: L.Layout) -> int:
        nonlocal escape
        at = next((i for i in range(len(stack) - 1, -1, -1) if stack[i] is layout), -1)
        if at >= 0:
            escape = min(escape, at)
            return W.fnv64(bytes((_BACK_EDGE,)) + W.uvarint_bytes(len(stack) - at))
        cached = cache.get(id(layout))
        if cached is not None:
            return cached
        here = len(stack)
        outer = escape
        escape = never_escapes
        stack.append(layout)
        hash_ = W.fnv64(structure(layout))
        stack.pop()
        closed = escape >= here
        if closed:
            cache[id(layout)] = hash_
        escape = outer if closed else min(outer, escape)
        return hash_

    def u64(layout: L.Layout) -> bytes:
        return go(layout).to_bytes(8, "little")

    def structure(layout: L.Layout) -> bytes:  # noqa: PLR0911, PLR0912
        match layout:
            case L.LeafLayout(kind=kind):
                return bytes((_LEAF_CODES[kind],))
            case L.LiteralLayout():
                return _literal(layout)
            case L.NeverLayout():
                return bytes((_NEVER,))
            case L.StructLayout():
                out = bytearray((_STRUCT,)) + W.uvarint_bytes(len(layout.fields))
                for field in layout.fields:
                    out += W.U32.pack(field.id)
                    out.append(1 if field.optional else 0)
                    out += u64(field.layout)
                out += W.uvarint_bytes(len(layout.extra))
                for signature in layout.extra:
                    out += u64(signature.layout)
                return bytes(out)
            case L.ArrayLayout():
                out = bytearray((_ARRAY,)) + W.uvarint_bytes(len(layout.elements))
                for slot in layout.elements:
                    out.append(1 if slot.optional else 0)
                    out += u64(slot.layout)
                out += W.uvarint_bytes(len(layout.rest))
                for rest in layout.rest:
                    out += u64(rest)
                return bytes(out)
            case L.UnionLayout():
                out = bytearray((_UNION,)) + W.uvarint_bytes(len(layout.by_pos))
                for position in layout.by_pos:
                    variant = position.variant
                    if variant is None:
                        out.append(0)
                    else:
                        out += bytes((1, 1 if variant.tuple_ else 0))
                        out += W.U32.pack(variant.tag)
                    out += u64(position.layout)
                return bytes(out)
            case L.OptionLayout():
                return bytes((_OPTION,)) + u64(layout.value)
            case L.ResultLayout():
                return bytes((_RESULT,)) + u64(layout.success) + u64(layout.failure)
            case L.ExitLayout():
                return (
                    bytes((_EXIT,))
                    + u64(layout.value)
                    + u64(layout.cause.error)
                    + u64(layout.cause.defect)
                )
            case L.ReasonLayout():
                code = _CAUSE if layout.kind == "cause" else _CAUSE_REASON
                return bytes((code,)) + u64(layout.error) + u64(layout.defect)

    return go(root)


def _literal(layout: L.LiteralLayout) -> bytes:
    out = bytearray((_LITERAL, _LEAF_CODES[layout.leaf.kind]))
    out += W.uvarint_bytes(len(layout.values))
    # Sorted, so a union hashes the same whatever order it declares.
    texts = [(literal_text(v), literal_kind_code(v)) for v in layout.values]
    for text, kind in sorted(texts, key=lambda pair: (_utf16(pair[0]), pair[1])):
        out.append(kind)
        data = text_encode(text)
        out += W.uvarint_bytes(len(data))
        out += data
    return bytes(out)


def _utf16(text: str) -> bytes:
    """JavaScript compares strings by UTF-16 code units."""
    return text.encode("utf-16-be", "surrogatepass")


@dataclass(frozen=True, slots=True)
class Mode:
    positional: bool
    envelope: int
    expected_envelope: str
    fingerprint: bytes
    reject_unknown_fields: bool = False
    """``to_codec_strict``: a field, key, union member or wire kind the schema
    does not know fails instead of being skipped."""


DEFAULT_MODE = Mode(False, W.ENVELOPE, "version 2 envelope, flags 0", bytes(8))
STRICT_MODE = replace(DEFAULT_MODE, reject_unknown_fields=True)


@lru_cache(maxsize=4096)
def _fingerprint_mode(layout: L.Layout) -> Mode:
    return Mode(
        True,
        W.ENVELOPE_FINGERPRINT,
        "version 2 envelope, flags 1",
        layout_fingerprint(layout).to_bytes(8, "little"),
    )


def compile_mode(layout: L.Layout, fingerprint: bool) -> Mode:
    return _fingerprint_mode(layout) if fingerprint else DEFAULT_MODE
