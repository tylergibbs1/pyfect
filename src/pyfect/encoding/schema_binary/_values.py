"""Which runtime values a layout takes (Effect's ``matchesLayout``), and the
cycle check of JSON and recursive values."""

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false
from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import UTC, datetime
from typing import cast

from pyfect import big_decimal as bd
from pyfect import redacted
from pyfect.cause import Cause, Die, Fail, Interrupt
from pyfect.duration import Duration
from pyfect.encoding.schema_binary import _layout as L
from pyfect.encoding.schema_binary import _wire as W
from pyfect.exit import Failure, Success
from pyfect.option import Some
from pyfect.redacted import Redacted
from pyfect.result import Err, Ok


def is_number_guard(value: object) -> bool:
    """A number in a union: a ``float``, or an ``int`` a JavaScript number
    holds (a wider one belongs to a bigint member)."""
    return isinstance(value, float) or (
        isinstance(value, int) and not isinstance(value, bool) and abs(value) <= W.MAX_SAFE
    )


def is_utc(value: object) -> bool:
    return isinstance(value, datetime) and value.tzinfo is UTC


def is_zoned(value: object) -> bool:
    return isinstance(value, datetime) and value.utcoffset() is not None


def is_reason(value: object) -> bool:
    return isinstance(value, Fail | Die | Interrupt)


def _is_array(value: object) -> bool:
    return isinstance(value, list | tuple)


def _is_bigint(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


_GUARDS: dict[str, Callable[[object], bool]] = {
    "bool": lambda value: isinstance(value, bool),
    "null": lambda value: value is None,
    "undefined": lambda value: value is None,
    "number": is_number_guard,
    "int": is_number_guard,
    "string": lambda value: isinstance(value, str),
    "bigint": _is_bigint,
    "i32": is_number_guard,
    "u32": is_number_guard,
    "i64": _is_bigint,
    "u64": _is_bigint,
    "bytes": lambda value: isinstance(value, bytes),
    "dateTimeUtc": is_utc,
    "dateTimeZoned": is_zoned,
    "duration": lambda value: isinstance(value, Duration),
    "bigDecimal": lambda value: isinstance(value, bd.BigDecimal),
    "option": lambda value: value is None or isinstance(value, Some),
    "result": lambda value: isinstance(value, Ok | Err),
    "exit": lambda value: isinstance(value, Success | Failure),
    "cause": lambda value: isinstance(value, Cause),
    "causeReason": is_reason,
    "array": _is_array,
    "struct": lambda value: isinstance(value, Mapping),
    "json": lambda _: True,
    "union": lambda _: False,
    "never": lambda _: False,
}


def matches_layout(layout: L.Layout, value: object) -> bool:
    if isinstance(layout, L.LiteralLayout):
        return layout.has(value)
    return _GUARDS[layout.kind](value)


def _children(value: object) -> Iterable[object] | None:  # noqa: PLR0911
    """What ``value`` holds, or ``None`` for a value holding nothing."""
    match value:
        case list() | tuple():
            return cast("Iterable[object]", value)
        case Mapping():
            return cast("Mapping[object, object]", value).values()
        case Some(value=inner) | Ok(value=inner) | Success(value=inner):
            return (inner,)
        case Err(error=inner) | Fail(error=inner):
            return (inner,)
        case Failure(cause=inner):
            return (inner,)
        case Cause(reasons=reasons):
            return reasons
        case Die(defect=inner):
            return (inner,)
        case Redacted():
            return (redacted.value(value),)
        case set() | frozenset():
            return cast("Iterable[object]", value)
        case _:
            return None


def is_cyclic(value: object) -> bool:
    """``value`` holds itself. Iterative, so any depth works; a value shared
    twice is not a cycle."""
    on_path: set[int] = set()
    done: set[int] = set()
    stack: list[tuple[int, Iterator[object]]] = []
    current = value
    while True:
        children = _children(current)
        if children is not None:
            key = id(current)
            if key in on_path:
                return True
            if key not in done:
                on_path.add(key)
                stack.append((key, iter(children)))
        while stack:
            key, items = stack[-1]
            item = next(items, stack)
            if item is not stack:
                current = item
                break
            stack.pop()
            on_path.discard(key)
            done.add(key)
        else:
            return False
