"""The little DER that ``key_format`` needs to rewrap PKCS#1 and SEC1
private keys as PKCS#8 (Effect's ``crypto/internal/der.ts``): reading
tag-length-value elements and encoding new ones. Lengths above three bytes
are rejected; no key needs them."""

from __future__ import annotations

from dataclasses import dataclass

SEQUENCE = 0x30
OCTET_STRING = 0x04
INTEGER = 0x02
OBJECT_IDENTIFIER = 0x06


@dataclass(frozen=True, slots=True)
class Element:
    """An element's ``tag``, where it starts (``offset``), and its contents
    from ``start`` to ``end``."""

    tag: int
    offset: int
    start: int
    end: int


def read(data: bytes, offset: int, end: int | None = None) -> Element | None:
    limit = len(data) if end is None else end
    if offset + 2 > limit:
        return None
    tag, first = data[offset], data[offset + 1]
    start = offset + 2
    length = first
    if first >= 0x80:
        size = first & 0x7F
        if size == 0 or size > 3 or start + size > limit:
            return None
        length = int.from_bytes(data[start : start + size])
        start += size
    return None if start + length > limit else Element(tag, offset, start, start + length)


def read_only(data: bytes, tag: int) -> Element | None:
    """The one element filling ``data``, when it has ``tag``."""
    element = read(data, 0)
    if element is not None and element.tag == tag and element.end == len(data):
        return element
    return None


def children(data: bytes, parent: Element) -> list[Element] | None:
    out: list[Element] = []
    offset = parent.start
    while offset < parent.end:
        element = read(data, offset, parent.end)
        if element is None:
            return None
        out.append(element)
        offset = element.end
    return out


def slice_of(data: bytes, element: Element) -> bytes:
    return data[element.offset : element.end]


def _length(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    size = (n.bit_length() + 7) // 8
    return bytes([0x80 | size]) + n.to_bytes(size)


def encode(tag: int, *contents: bytes) -> bytes:
    body = b"".join(contents)
    return bytes([tag]) + _length(len(body)) + body
