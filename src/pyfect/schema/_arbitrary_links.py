"""The ``to_codec_arbitrary`` annotations of the built-in declarations whose
JSON form random values rarely parse as (date-times, zones, URLs, bytes)
or whose size checks generation should honour (sets, maps): Effect's
``toCodecArbitrary`` cases. Each gives the node ``to_strategy`` draws and
the transformation to the declaration's values.

Date-times are drawn at millisecond precision within Python's years 1 to
9999 (Effect's ``Date`` range is wider; its date-times count milliseconds);
offsets in whole minutes from -12:00 to +14:00, and named zones from the
same five Effect uses.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from fractions import Fraction
from typing import Any, cast
from urllib.parse import SplitResult, urlsplit
from zoneinfo import ZoneInfo

from pyfect._equal import dict_of, frozenset_of
from pyfect._url import Url
from pyfect.date_time._epoch import EPOCH, from_epoch_millis, to_epoch_millis
from pyfect.date_time._zones import zone_named
from pyfect.schema import ast
from pyfect.schema._arbitrary_constraint import ArbitraryConstraint
from pyfect.schema._checks_number import int_value, is_between
from pyfect.schema._checks_size import is_between_length, is_max_length, is_min_length
from pyfect.schema._checks_string import is_pattern
from pyfect.schema._codec_links import link, partial_link

_FIRST = to_epoch_millis(datetime(1, 1, 1, tzinfo=UTC))
_LAST = to_epoch_millis(datetime(9999, 12, 31, 23, 59, 59, 999000, tzinfo=UTC))
_ZONE_MARGIN = 14 * 60 * 60 * 1000
_NAMED_ZONES = ("UTC", "Europe/London", "America/New_York", "Asia/Tokyo", "Australia/Sydney")


def _integers(minimum: int, maximum: int) -> ast.AST:
    return ast.append_checks(
        ast.number, (int_value(), is_between(minimum=minimum, maximum=maximum))
    )


def _millis_bounds(constraint: ArbitraryConstraint, first: int, last: int) -> tuple[int, int]:
    low, high = constraint.minimum, constraint.maximum
    if isinstance(low, datetime):
        exact = _exact_millis(low)
        low_ms = math.floor(exact) + 1 if constraint.exclusive_minimum else math.ceil(exact)
        first = max(first, low_ms)
    if isinstance(high, datetime):
        exact = _exact_millis(high)
        high_ms = math.ceil(exact) - 1 if constraint.exclusive_maximum else math.floor(exact)
        last = min(last, high_ms)
    return first, last


def _exact_millis(value: datetime) -> Fraction:
    return Fraction((value - EPOCH) // timedelta(microseconds=1), 1000)


def date_time_utc(_: tuple[ast.AST, ...], constraint: ArbitraryConstraint) -> ast.Link:
    first, last = _millis_bounds(constraint, _FIRST, _LAST)
    return link(_integers(first, last), decode=from_epoch_millis, encode=to_epoch_millis)


_OFFSET_MINUTES = _integers(-12 * 60, 14 * 60)
_ZONE = ast.Union((_OFFSET_MINUTES, ast.Union(tuple(map(ast.Literal, _NAMED_ZONES)))))


def _zone_of(value: int | str) -> tzinfo:
    if isinstance(value, str):
        return cast("ZoneInfo", zone_named(value))  # one of _NAMED_ZONES
    return timezone(timedelta(minutes=value))


def _zone_to(zone: tzinfo) -> int | str:
    if isinstance(zone, ZoneInfo):
        return zone.key
    return cast("timedelta", zone.utcoffset(None)) // timedelta(minutes=1)


def time_zone(_: tuple[ast.AST, ...], __: ArbitraryConstraint) -> ast.Link:
    return link(_ZONE, decode=_zone_of, encode=_zone_to)


def time_zone_named(_: tuple[ast.AST, ...], __: ArbitraryConstraint) -> ast.Link:
    names = ast.Union(tuple(map(ast.Literal, _NAMED_ZONES)))
    return link(names, decode=ZoneInfo, encode=lambda zone: zone.key)


def time_zone_offset(_: tuple[ast.AST, ...], __: ArbitraryConstraint) -> ast.Link:
    return link(_OFFSET_MINUTES, decode=_zone_of, encode=_zone_to)


def _zoned_of(value: Mapping[str, Any]) -> datetime:
    return from_epoch_millis(value["epoch_millis"]).astimezone(_zone_of(value["zone"]))


def _zoned_to(value: datetime) -> Mapping[str, Any]:
    return {"epoch_millis": to_epoch_millis(value), "zone": _zone_to(cast("tzinfo", value.tzinfo))}


def date_time_zoned(_: tuple[ast.AST, ...], constraint: ArbitraryConstraint) -> ast.Link:
    first, last = _millis_bounds(constraint, _FIRST + _ZONE_MARGIN, _LAST - _ZONE_MARGIN)
    struct = ast.Objects(
        (
            ast.PropertySignature("epoch_millis", _integers(first, last)),
            ast.PropertySignature("zone", _ZONE),
        )
    )
    return link(struct, decode=_zoned_of, encode=_zoned_to)


def _text(pattern: str, minimum: int, maximum: int) -> ast.AST:
    return ast.append_checks(ast.string, (is_pattern(pattern), is_between_length(minimum, maximum)))


_URL = ast.Objects(
    (
        ast.PropertySignature("scheme", ast.Union((ast.Literal("http"), ast.Literal("https")))),
        ast.PropertySignature("label", _text(r"^[a-z0-9]+\Z", 1, 63)),
        ast.PropertySignature("suffix", _text(r"^[a-z]+\Z", 2, 10)),
        ast.PropertySignature(
            "path",
            ast.append_checks(
                ast.Arrays(rest=(_text(r"^[A-Za-z0-9._~%-]*\Z", 0, 16),)), (is_max_length(4),)
            ),
        ),
    )
)


def _url_of(parts: Mapping[str, Any]) -> Url:
    path = "/".join(parts["path"])
    return Url._make(urlsplit(f"{parts['scheme']}://{parts['label']}.{parts['suffix']}/{path}"))


def _url_to(url: SplitResult) -> Mapping[str, Any]:
    label, _, suffix = url.netloc.partition(".")
    path = url.path.removeprefix("/")
    return {"scheme": url.scheme, "label": label, "suffix": suffix, "path": path.split("/")}


def url(_: tuple[ast.AST, ...], __: ArbitraryConstraint) -> ast.Link:
    return link(_URL, decode=_url_of, encode=_url_to)


def _sized(rest: ast.AST, minimum: int | None, maximum: int | None) -> ast.AST:
    checks: list[ast.Check[Any]] = []
    if minimum is not None:
        checks.append(is_min_length(minimum))
    if maximum is not None:
        checks.append(is_max_length(maximum))
    arrays = ast.Arrays(rest=(rest,))
    return ast.append_checks(arrays, (checks[0], *checks[1:])) if checks else arrays


def bytes_(_: tuple[ast.AST, ...], constraint: ArbitraryConstraint) -> ast.Link:
    items = _sized(_integers(0, 255), constraint.min_length, constraint.max_length)
    return link(items, decode=bytes, encode=tuple)


def frozen_set(parameters: tuple[ast.AST, ...], constraint: ArbitraryConstraint) -> ast.Link:
    (value,) = parameters
    sized = _sized(value, constraint.min_size, constraint.max_size)
    # Draws Python would merge (``1`` and ``True``) fail, so they are redrawn.
    return partial_link(sized, decode=frozenset_of, encode=tuple, expected="distinct items")


def _entries(mapping: Mapping[object, object]) -> tuple[tuple[object, object], ...]:
    return tuple(mapping.items())


def map_(parameters: tuple[ast.AST, ...], constraint: ArbitraryConstraint) -> ast.Link:
    entry = ast.Arrays(tuple(ast.Element(p) for p in parameters))
    sized = _sized(entry, constraint.min_size, constraint.max_size)
    return partial_link(sized, decode=dict_of, encode=_entries, expected="distinct keys")
