"""What a node's checks say about the values ``to_strategy`` should build
(Effect's ``Annotations.ToArbitrary.GenerationConstraint``).

Each built-in check is read from its ``representation`` (bounds, lengths,
sizes, patterns); a user check can carry an ``arbitrary_constraint``
annotation. Constraints only steer generation: every check still runs on
each value, so a constraint may be looser than its check. Python's ``len``
counts a string's code points, so Effect's code-point bounds are lengths.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast

from pyfect._digits import parse_signed_digits
from pyfect.schema._checks_string import js_regex
from pyfect.schema._ecma_pattern import compile_ecma
from pyfect.schema._jsonschema._checks import BUILTINS, CheckContext
from pyfect.schema.ast import Check, FilterGroup

type NumberKind = Literal["finite", "integer"]


@dataclass(frozen=True, slots=True, kw_only=True)
class ArbitraryConstraint:
    """Bounds and shapes to generate within. ``minimum`` / ``maximum`` are
    numbers, ``int`` bigints or ``datetime`` values (the node's own kind);
    lengths count ``len``; ``size`` is a set's or a mapping's ``len``;
    ``properties`` a mapping's keys; ``patterns`` are matched with
    ``re.search``; ``unique`` asks for distinct items."""

    minimum: Any = None
    exclusive_minimum: bool = False
    maximum: Any = None
    exclusive_maximum: bool = False
    min_length: int | None = None
    max_length: int | None = None
    min_size: int | None = None
    max_size: int | None = None
    min_properties: int | None = None
    max_properties: int | None = None
    patterns: tuple[re.Pattern[str], ...] = ()
    number: NumberKind | None = None
    unique: bool = False

    def merge(self, that: ArbitraryConstraint) -> ArbitraryConstraint:
        """Both constraints at once: the tighter bound of each pair."""
        minimum, exclusive_minimum = _tighter(
            (self.minimum, self.exclusive_minimum), (that.minimum, that.exclusive_minimum), 1
        )
        maximum, exclusive_maximum = _tighter(
            (self.maximum, self.exclusive_maximum), (that.maximum, that.exclusive_maximum), -1
        )
        number: NumberKind | None = (
            "integer"
            if "integer" in (self.number, that.number)
            else "finite"
            if "finite" in (self.number, that.number)
            else None
        )
        return ArbitraryConstraint(
            minimum=minimum,
            exclusive_minimum=exclusive_minimum,
            maximum=maximum,
            exclusive_maximum=exclusive_maximum,
            min_length=_larger(self.min_length, that.min_length),
            max_length=_smaller(self.max_length, that.max_length),
            min_size=_larger(self.min_size, that.min_size),
            max_size=_smaller(self.max_size, that.max_size),
            min_properties=_larger(self.min_properties, that.min_properties),
            max_properties=_smaller(self.max_properties, that.max_properties),
            patterns=(*self.patterns, *that.patterns),
            number=number,
            unique=self.unique or that.unique,
        )


NONE = ArbitraryConstraint()


def _larger(a: int | None, b: int | None) -> int | None:
    return a if b is None else b if a is None else max(a, b)


def _smaller(a: int | None, b: int | None) -> int | None:
    return a if b is None else b if a is None else min(a, b)


def _tighter(a: tuple[Any, bool], b: tuple[Any, bool], direction: int) -> tuple[Any, bool]:
    """The tighter of two bounds: the larger minimum (``direction`` 1) or
    the smaller maximum (-1); at a tie, exclusive wins."""
    if a[0] is None:
        return b
    if b[0] is None:
        return a
    if a[0] == b[0]:
        return a[0], a[1] or b[1]
    return a if (a[0] > b[0]) == (direction == 1) else b


def constraint_of(checks: Sequence[Check[Any]] | None) -> ArbitraryConstraint:
    """What ``checks`` (and the groups inside them) say, merged."""
    out = NONE
    for check in checks or ():
        annotations = check.annotations or {}
        custom = annotations.get("arbitrary_constraint")
        if isinstance(custom, ArbitraryConstraint):
            out = out.merge(custom)
        if isinstance(check, FilterGroup):
            out = out.merge(constraint_of(check.checks))
        else:
            out = out.merge(_builtin(annotations))
    return out


def _builtin(annotations: Mapping[str, object]) -> ArbitraryConstraint:
    representation = annotations.get("representation")
    if not isinstance(representation, Mapping):
        return NONE
    representation = cast("Mapping[str, object]", representation)
    id = representation.get("id")
    if not isinstance(id, str) or not id.startswith("effect/schema/"):
        return NONE
    payload = representation.get("payload")
    data: Mapping[str, Any] = (
        cast("Mapping[str, Any]", payload) if isinstance(payload, Mapping) else {}
    )
    return _read(id.removeprefix("effect/schema/"), data)


def _bound(text: object) -> Any:
    """A payload bound: a bigint's digits and a date's ISO text are read back."""
    if isinstance(text, str):
        number = None if text.startswith("+") else parse_signed_digits(text)
        if number is not None:
            return number
        return datetime.fromisoformat(text)
    return text


def _bounds(data: Mapping[str, Any]) -> ArbitraryConstraint:
    def side(inclusive: str, exclusive: str) -> tuple[Any, bool]:
        if exclusive in data and not isinstance(data[exclusive], bool):
            return _bound(data[exclusive]), True
        return _bound(data.get(inclusive)), bool(data.get(exclusive))

    minimum, exclusive_minimum = side("minimum", "exclusiveMinimum")
    maximum, exclusive_maximum = side("maximum", "exclusiveMaximum")
    return ArbitraryConstraint(
        minimum=minimum,
        exclusive_minimum=exclusive_minimum,
        maximum=maximum,
        exclusive_maximum=exclusive_maximum,
    )


_ORDERED = frozenset(
    f"{name}{suffix}"
    for name in (
        "isGreaterThan",
        "isGreaterThanOrEqualTo",
        "isLessThan",
        "isLessThanOrEqualTo",
        "isBetween",
    )
    for suffix in ("", "BigInt", "Date")
)

type _Reader = Callable[[Mapping[str, Any]], ArbitraryConstraint]

_READERS: Mapping[str, _Reader] = {
    "isFinite": lambda _: ArbitraryConstraint(number="finite"),
    "isInt": lambda _: ArbitraryConstraint(number="integer"),
    "isMinLength": lambda d: ArbitraryConstraint(min_length=d["minLength"]),
    "isMaxLength": lambda d: ArbitraryConstraint(max_length=d["maxLength"]),
    "isMinCodePoints": lambda d: ArbitraryConstraint(min_length=d["minCodePoints"]),
    "isMaxCodePoints": lambda d: ArbitraryConstraint(max_length=d["maxCodePoints"]),
    "isBetweenLength": lambda d: ArbitraryConstraint(
        min_length=d["minimum"], max_length=d["maximum"]
    ),
    "isBetweenCodePoints": lambda d: ArbitraryConstraint(
        min_length=d["minimum"], max_length=d["maximum"]
    ),
    "isMinSize": lambda d: ArbitraryConstraint(min_size=d["minSize"]),
    "isMaxSize": lambda d: ArbitraryConstraint(max_size=d["maxSize"]),
    "isBetweenSize": lambda d: ArbitraryConstraint(min_size=d["minimum"], max_size=d["maximum"]),
    "isMinProperties": lambda d: ArbitraryConstraint(min_properties=d["minProperties"]),
    "isMaxProperties": lambda d: ArbitraryConstraint(max_properties=d["maxProperties"]),
    "isBetweenProperties": lambda d: ArbitraryConstraint(
        min_properties=d["minimum"], max_properties=d["maximum"]
    ),
    "isUnique": lambda _: ArbitraryConstraint(unique=True),
    "isPattern": lambda d: ArbitraryConstraint(
        patterns=(
            compile_ecma(d["source"], d["flags"])
            if isinstance(d["flags"], str)
            else re.compile(d["source"], d["flags"]),
        )
    ),
}
"""By the id after ``effect/schema/``; the ordered checks read their bounds."""


_STRING_PATTERNS = frozenset(
    (
        "isTrimmed",
        "isStringFinite",
        "isStringBigInt",
        "isUUID",
        "isGUID",
        "isULID",
        "isAscii",
        "isBase64",
        "isBase64Url",
        "isStartingWith",
        "isEndingWith",
        "isIncluding",
        "isUppercased",
        "isLowercased",
        "isCapitalized",
        "isUncapitalized",
    )
)
"""The string checks generated from the (JavaScript) pattern of their JSON
Schema."""


def _read(id: str, data: Mapping[str, Any]) -> ArbitraryConstraint:
    if id in _ORDERED:
        return _bounds(data)
    if id in _STRING_PATTERNS:
        return _string_pattern(id, data)
    reader = _READERS.get(id)
    return NONE if reader is None else reader(data)


def _string_pattern(id: str, data: Mapping[str, Any]) -> ArbitraryConstraint:
    """A string check's pattern, from its JSON Schema fragment."""
    output = BUILTINS[id](data, CheckContext("string", ()))
    fragment = output[0] if isinstance(output, tuple) else output
    return ArbitraryConstraint(patterns=(js_regex(cast("str", fragment["pattern"])),))
