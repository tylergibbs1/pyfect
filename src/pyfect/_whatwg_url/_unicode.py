"""Lookups in the generated Unicode tables (``_unicode_data``), parsed on
first use: a host only needs them when it is not plain ASCII."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from functools import cache


@dataclass(frozen=True, slots=True)
class _Table:
    starts: tuple[int, ...]
    ends: tuple[int, ...]
    values: tuple[str, ...]

    def get(self, cp: int) -> str | None:
        i = bisect_right(self.starts, cp) - 1
        return self.values[i] if i >= 0 and cp <= self.ends[i] else None


def _parse(text: str) -> _Table:
    starts: list[int] = []
    ends: list[int] = []
    values: list[str] = []
    for line in text.splitlines():
        span, _, value = line.partition(" ")
        first, _, last = span.partition("..")
        starts.append(int(first, 16))
        ends.append(int(last or first, 16))
        values.append(value)
    return _Table(tuple(starts), tuple(ends), tuple(values))


@cache
def _tables() -> dict[str, _Table]:
    from pyfect._whatwg_url import _unicode_data as data

    return {
        "idna": _parse(data.IDNA),
        "bidi": _parse(data.BIDI),
        "joining": _parse(data.JOINING),
        "combining_class": _parse(data.COMBINING_CLASS),
        "decomposition": _parse(data.DECOMPOSITION),
        "composition_exclusion": _parse(data.COMPOSITION_EXCLUSION),
        "mark": _parse(data.MARK),
    }


def idna_status(ch: str) -> str:
    """``V`` (valid), ``X`` (disallowed), ``I`` (ignored) or ``M`` and the
    mapping's code points in hex."""
    status = _tables()["idna"].get(ord(ch))
    return "X" if status is None else status


def bidi_class(ch: str) -> str:
    """The bidi class among those RFC 5893 names (``L`` by default)."""
    return _tables()["bidi"].get(ord(ch)) or "L"


def joining_type(ch: str) -> str | None:
    """``D``, ``L``, ``R`` or ``T``; ``None`` for the others."""
    return _tables()["joining"].get(ord(ch))


def combining_class(ch: str) -> int:
    value = _tables()["combining_class"].get(ord(ch))
    return 0 if value is None else int(value)


def is_virama(ch: str) -> bool:
    return combining_class(ch) == 9


def decomposition(ch: str) -> str | None:
    """The canonical decomposition (one step), ``None`` when there is none."""
    value = _tables()["decomposition"].get(ord(ch))
    return None if value is None else "".join(chr(int(cp, 16)) for cp in value.split())


@cache
def compositions() -> dict[str, str]:
    """Each primary composite by the pair it decomposes to."""
    table = _tables()["decomposition"]
    excluded = _tables()["composition_exclusion"]
    pairs: dict[str, str] = {}
    for cp, value in zip(table.starts, table.values, strict=True):
        parts = value.split()
        if len(parts) == 2 and excluded.get(cp) is None:
            pairs["".join(chr(int(p, 16)) for p in parts)] = chr(cp)
    return pairs


def is_mark(ch: str) -> bool:
    return _tables()["mark"].get(ord(ch)) is not None
