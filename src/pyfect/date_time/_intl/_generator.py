"""ICU's ``DateTimePatternGenerator`` (``dtptngen.cpp``, ICU 78): the best
pattern for a skeleton, from a locale's ``availableFormats``, its standard
patterns and its ``appendItems``. Ported to give the patterns ICU gives, ties
and quirks included; the names follow ICU's.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from pyfect._digits import is_digits
from pyfect.date_time._intl._data import CalendarData

# UDateTimePatternField
ERA, YEAR, QUARTER, MONTH, WEEK_OF_YEAR, WEEK_OF_MONTH, WEEKDAY = range(7)
DAY_OF_YEAR, DAY_OF_WEEK_IN_MONTH, DAY, DAYPERIOD, HOUR, MINUTE, SECOND = range(7, 14)
FRACTIONAL_SECOND, ZONE = 14, 15
_FIELD_COUNT: Final = 16

_NARROW, _SHORTER, _SHORT, _LONG = -0x101, -0x102, -0x103, -0x104
_NUMERIC, _DELTA = 0x100, 0x10
_EXTRA_FIELD, _MISSING_FIELD = 0x10000, 0x1000

# dtTypes: pattern letter, field, type, minimum length.
_TYPES: Final[tuple[tuple[str, int, int, int], ...]] = (
    ("G", ERA, _SHORT, 1),
    ("G", ERA, _LONG, 4),
    ("G", ERA, _NARROW, 5),
    ("y", YEAR, _NUMERIC, 1),
    ("Y", YEAR, _NUMERIC + _DELTA, 1),
    ("u", YEAR, _NUMERIC + 2 * _DELTA, 1),
    ("r", YEAR, _NUMERIC + 3 * _DELTA, 1),
    ("U", YEAR, _SHORT, 1),
    ("U", YEAR, _LONG, 4),
    ("U", YEAR, _NARROW, 5),
    ("Q", QUARTER, _NUMERIC, 1),
    ("Q", QUARTER, _SHORT, 3),
    ("Q", QUARTER, _LONG, 4),
    ("Q", QUARTER, _NARROW, 5),
    ("q", QUARTER, _NUMERIC + _DELTA, 1),
    ("q", QUARTER, _SHORT - _DELTA, 3),
    ("q", QUARTER, _LONG - _DELTA, 4),
    ("q", QUARTER, _NARROW - _DELTA, 5),
    ("M", MONTH, _NUMERIC, 1),
    ("M", MONTH, _SHORT, 3),
    ("M", MONTH, _LONG, 4),
    ("M", MONTH, _NARROW, 5),
    ("L", MONTH, _NUMERIC + _DELTA, 1),
    ("L", MONTH, _SHORT - _DELTA, 3),
    ("L", MONTH, _LONG - _DELTA, 4),
    ("L", MONTH, _NARROW - _DELTA, 5),
    ("l", MONTH, _NUMERIC + _DELTA, 1),
    ("w", WEEK_OF_YEAR, _NUMERIC, 1),
    ("W", WEEK_OF_MONTH, _NUMERIC, 1),
    ("E", WEEKDAY, _SHORT, 1),
    ("E", WEEKDAY, _LONG, 4),
    ("E", WEEKDAY, _NARROW, 5),
    ("E", WEEKDAY, _SHORTER, 6),
    ("c", WEEKDAY, _NUMERIC + 2 * _DELTA, 1),
    ("c", WEEKDAY, _SHORT - 2 * _DELTA, 3),
    ("c", WEEKDAY, _LONG - 2 * _DELTA, 4),
    ("c", WEEKDAY, _NARROW - 2 * _DELTA, 5),
    ("c", WEEKDAY, _SHORTER - 2 * _DELTA, 6),
    ("e", WEEKDAY, _NUMERIC + _DELTA, 1),
    ("e", WEEKDAY, _SHORT - _DELTA, 3),
    ("e", WEEKDAY, _LONG - _DELTA, 4),
    ("e", WEEKDAY, _NARROW - _DELTA, 5),
    ("e", WEEKDAY, _SHORTER - _DELTA, 6),
    ("d", DAY, _NUMERIC, 1),
    ("g", DAY, _NUMERIC + _DELTA, 1),
    ("D", DAY_OF_YEAR, _NUMERIC, 1),
    ("F", DAY_OF_WEEK_IN_MONTH, _NUMERIC, 1),
    ("a", DAYPERIOD, _SHORT, 1),
    ("a", DAYPERIOD, _LONG, 4),
    ("a", DAYPERIOD, _NARROW, 5),
    ("b", DAYPERIOD, _SHORT - _DELTA, 1),
    ("b", DAYPERIOD, _LONG - _DELTA, 4),
    ("b", DAYPERIOD, _NARROW - _DELTA, 5),
    ("B", DAYPERIOD, _SHORT - 3 * _DELTA, 1),
    ("B", DAYPERIOD, _LONG - 3 * _DELTA, 4),
    ("B", DAYPERIOD, _NARROW - 3 * _DELTA, 5),
    ("H", HOUR, _NUMERIC + 10 * _DELTA, 1),
    ("k", HOUR, _NUMERIC + 11 * _DELTA, 1),
    ("h", HOUR, _NUMERIC, 1),
    ("K", HOUR, _NUMERIC + _DELTA, 1),
    ("J", HOUR, _NUMERIC + 5 * _DELTA, 1),
    ("j", HOUR, _NUMERIC + 6 * _DELTA, 1),
    ("C", HOUR, _NUMERIC + 7 * _DELTA, 1),
    ("m", MINUTE, _NUMERIC, 1),
    ("s", SECOND, _NUMERIC, 1),
    ("A", SECOND, _NUMERIC + _DELTA, 1),
    ("S", FRACTIONAL_SECOND, _NUMERIC, 1),
    ("v", ZONE, _SHORT - 2 * _DELTA, 1),
    ("v", ZONE, _LONG - 2 * _DELTA, 4),
    ("z", ZONE, _SHORT, 1),
    ("z", ZONE, _LONG, 4),
    ("Z", ZONE, _NARROW - _DELTA, 1),
    ("Z", ZONE, _LONG - _DELTA, 4),
    ("Z", ZONE, _SHORT - _DELTA, 5),
    ("O", ZONE, _SHORT - _DELTA, 1),
    ("O", ZONE, _LONG - _DELTA, 4),
    ("V", ZONE, _SHORT - _DELTA, 1),
    ("V", ZONE, _LONG - _DELTA, 2),
    ("V", ZONE, _LONG - 1 - _DELTA, 3),
    ("V", ZONE, _LONG - 2 - _DELTA, 4),
    ("X", ZONE, _NARROW - _DELTA, 1),
    ("X", ZONE, _SHORT - _DELTA, 2),
    ("X", ZONE, _LONG - _DELTA, 4),
    ("x", ZONE, _NARROW - _DELTA, 1),
    ("x", ZONE, _SHORT - _DELTA, 2),
    ("x", ZONE, _LONG - _DELTA, 4),
)
_CANONICAL_ITEMS: Final = "GyQMwWEDFdaHmsSv"
_APPEND_KEYS: Final = (
    "Era",
    "Year",
    "Quarter",
    "Month",
    "Week",
    "*",
    "Day-Of-Week",
    "*",
    "*",
    "Day",
    "*",
    "Hour",
    "Minute",
    "Second",
    "*",
    "Timezone",
)
_FIELD_NAMES: Final = (
    "era",
    "year",
    "quarter",
    "month",
    "week",
    "weekOfMonth",
    "weekday",
    "dayOfYear",
    "weekdayOfMonth",
    "day",
    "dayperiod",
    "hour",
    "minute",
    "second",
    "*",
    "zone",
)
_DEFAULT_APPEND: Final = "{0} ├{2}: {1}┤"
_DATE_MASK: Final = (1 << DAYPERIOD) - 1
_TIME_MASK: Final = (1 << _FIELD_COUNT) - 1 - _DATE_MASK
_FLAG_CAP_J: Final = 1
# Hour letters adjustFieldTypes treats as the locale's own: 12-hour for 12-hour,
# 24-hour for 24-hour.
_SAME_HALF: Final = (("h", "K"), ("H", "k"), ("k", "H"), ("K", "h"))


def tokens(pattern: str) -> list[str]:
    """``FormatParser``: runs of one ASCII letter, and every other character alone."""
    found: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        end = index + 1
        if char.isascii() and char.isalpha():
            while end < len(pattern) and pattern[end] == char:
                end += 1
        found.append(pattern[index:end])
        index = end
    return found


def _quote_literal(items: list[str], index: int) -> tuple[str, int]:
    """``getQuoteLiteral``: the quoted text starting at ``items[index]``, and
    the index of its closing quote."""
    quote = items[index]
    index += 1
    while index < len(items):
        if items[index][0] == "'":
            if index + 1 < len(items) and items[index + 1][0] == "'":
                quote += items[index] + items[index + 1]
                index += 2
                continue
            quote += items[index]
            break
        quote += items[index]
        index += 1
    return quote, index


def canonical_index(token: str) -> int:
    """The ``_TYPES`` row of a field like ``MMM``, or -1."""
    char = token[0]
    if any(other != char for other in token):
        return -1
    for index, row in enumerate(_TYPES):
        if row[0] != char:
            continue
        following = _TYPES[index + 1] if index + 1 < len(_TYPES) else None
        if following is None or following[0] != char or following[3] > len(token):
            return index
    return -1


@dataclass(slots=True)
class Skeleton:
    """``PtnSkeleton``: per field, the letters as written and as the base
    (minimum) form, and the type distances are measured with."""

    chars: list[str] = field(default_factory=lambda: [""] * _FIELD_COUNT)
    lengths: list[int] = field(default_factory=lambda: [0] * _FIELD_COUNT)
    base_chars: list[str] = field(default_factory=lambda: [""] * _FIELD_COUNT)
    base_lengths: list[int] = field(default_factory=lambda: [0] * _FIELD_COUNT)
    types: list[int] = field(default_factory=lambda: [0] * _FIELD_COUNT)

    def original(self) -> tuple[tuple[str, ...], tuple[int, ...]]:
        return tuple(self.chars), tuple(self.lengths)

    def base_pattern(self) -> str:
        return "".join(c * n for c, n in zip(self.base_chars, self.base_lengths, strict=True))

    def skeleton(self) -> str:
        return "".join(c * n for c, n in zip(self.chars, self.lengths, strict=True))

    def first_char(self) -> str:
        return next((c for c, n in zip(self.base_chars, self.base_lengths, strict=True) if n), "")

    def field_mask(self) -> int:
        return sum(1 << index for index, kind in enumerate(self.types) if kind)

    def distance(self, other: Skeleton, include: int) -> tuple[int, int, int]:
        """``getDistance``: the distance, and the missing and extra field masks."""
        result = missing = extra = 0
        for index in range(_FIELD_COUNT):
            mine = self.types[index] if include & (1 << index) else 0
            theirs = other.types[index]
            if mine == theirs:
                continue
            if mine == 0:
                result += _EXTRA_FIELD
                extra |= 1 << index
            elif theirs == 0:
                result += _MISSING_FIELD
                missing |= 1 << index
            else:
                result += abs(mine - theirs)
        return result, missing, extra


def skeleton_of(pattern: str) -> Skeleton:
    """``DateTimeMatcher::set``."""
    found = Skeleton()
    items = tokens(pattern)
    index = 0
    while index < len(items):
        item = items[index]
        if item[0] == "'":
            _, index = _quote_literal(items, index)
            index += 1
            continue
        row_index = canonical_index(item)
        index += 1
        if row_index < 0:
            continue
        char, which, kind, minimum = _TYPES[row_index]
        found.chars[which], found.lengths[which] = item[0], len(item)
        found.base_chars[which], found.base_lengths[which] = char, minimum
        found.types[which] = kind + len(item) if kind > 0 else kind
    if found.lengths[HOUR]:
        if found.chars[HOUR] in "hK":
            if not found.lengths[DAYPERIOD]:
                found.chars[DAYPERIOD], found.lengths[DAYPERIOD] = "a", 1
                found.base_chars[DAYPERIOD], found.base_lengths[DAYPERIOD] = "a", 1
                found.types[DAYPERIOD] = _SHORT
        else:
            found.chars[DAYPERIOD], found.lengths[DAYPERIOD] = "", 0
            found.base_chars[DAYPERIOD], found.base_lengths[DAYPERIOD] = "", 0
            found.types[DAYPERIOD] = 0
    return found


@dataclass(slots=True)
class _Entry:
    base: str
    skeleton: Skeleton
    pattern: str
    specified: bool


def _bucket(char: str) -> int:
    return ord(char) - ord("A") if char.isupper() else 26 + ord(char) - ord("a")


def simple_format(template: str, *values: str) -> str:
    """ICU's ``SimpleFormatter``: ``{n}`` replaced, ``''`` an apostrophe, and
    ``'{...}'`` quoted text."""
    out: list[str] = []
    index = 0
    while index < len(template):
        char = template[index]
        if char == "'":
            if template.startswith("''", index):
                out.append("'")
                index += 2
                continue
            if index + 1 < len(template) and template[index + 1] in "{}":
                end = template.find("'", index + 1)
                end = len(template) if end < 0 else end
                out.append(template[index + 1 : end])
                index = end + 1
                continue
            out.append(char)
            index += 1
        elif char == "{" and index + 2 < len(template) and template[index + 2] == "}":
            argument = template[index + 1]
            out.append(
                values[int(argument)] if is_digits(argument) else template[index : index + 3]
            )
            index += 3
        else:
            out.append(char)
            index += 1
    return "".join(out)


class Generator:
    """A ``DateTimePatternGenerator`` for one locale and calendar."""

    def __init__(
        self,
        calendar: CalendarData,
        fields: dict[str, str],
        hour_char: str,
        allowed: tuple[str, ...],
        *,
        standard_patterns: bool = True,
        match_hour: bool = True,
    ) -> None:
        self.match_hour = match_hour
        self._buckets: list[list[_Entry]] = [[] for _ in range(52)]
        self.hour_char = hour_char
        self._allowed = allowed
        for char in _CANONICAL_ITEMS:
            self._add(char, None, override=False)
        if standard_patterns:
            for pattern in (*calendar.time_formats, *calendar.date_formats):
                self._add(pattern, None, override=False)
        self._append_items = [
            calendar.append_items.get(key) or _DEFAULT_APPEND for key in _APPEND_KEYS
        ]
        self._field_names = [
            fields.get(name) or f"F{index}" for index, name in enumerate(_FIELD_NAMES)
        ]
        for skeleton, pattern in calendar.available_formats:
            self._add(pattern, skeleton, override=True)
        self._date_time = tuple(
            at or plain
            for at, plain in zip(calendar.at_time, calendar.date_time_formats, strict=True)
        )

    def _entries(self) -> list[_Entry]:
        return [entry for bucket in self._buckets for entry in bucket]

    def _from_base(self, base: str) -> _Entry | None:
        return next((e for e in self._buckets[_bucket(base[0])] if e.base == base), None)

    def _from_skeleton(self, skeleton: Skeleton) -> _Entry | None:
        first = skeleton.first_char()
        if not first:
            return None
        original = skeleton.original()
        return next(
            (e for e in self._buckets[_bucket(first)] if e.skeleton.original() == original), None
        )

    def _add(self, pattern: str, skeleton_text: str | None, *, override: bool) -> None:
        """``addPatternWithOptionalSkeleton``."""
        skeleton = skeleton_of(pattern if skeleton_text is None else skeleton_text)
        base = skeleton.base_pattern()
        if not base:
            return
        duplicate = self._from_base(base)
        if (
            duplicate is not None
            and (not duplicate.specified or (skeleton_text is not None and not override))
            and not override
        ):
            return
        same = self._from_skeleton(skeleton)
        if same is not None and (not override or (skeleton_text is not None and same.specified)):
            return
        bucket = self._buckets[_bucket(base[0])]
        for entry in bucket:
            if entry.base == base and entry.skeleton.types == skeleton.types:
                entry.pattern = pattern
                entry.specified = skeleton_text is not None
                return
        bucket.append(_Entry(base, skeleton, pattern, skeleton_text is not None))

    def _best_raw(self, request: Skeleton, include: int) -> tuple[_Entry, int, int]:
        """``getBestRaw``: the closest entry, and its missing and extra masks."""
        best: _Entry | None = None
        best_distance = 0x7FFFFFFF
        best_missing = -1
        found_missing = found_extra = 0
        for entry in self._entries():
            distance, missing, extra = request.distance(entry.skeleton, include)
            if distance < best_distance or (distance == best_distance and best_missing < missing):
                best_distance, best_missing = distance, missing
                best = self._from_skeleton(entry.skeleton)
                found_missing, found_extra = missing, extra
                if distance == 0:
                    break
        assert best is not None
        return best, found_missing, found_extra

    def _map_metacharacters(self, skeleton: str) -> tuple[str, int]:
        out: list[str] = []
        flags = 0
        in_quote = False
        index = 0
        while index < len(skeleton):
            char = skeleton[index]
            if char == "'":
                in_quote = not in_quote
            elif not in_quote:
                if char in "jC":
                    extra = 0
                    while index + 1 < len(skeleton) and skeleton[index + 1] == char:
                        extra += 1
                        index += 1
                    hour_length = 1 + (extra & 1)
                    period_length = 1 if extra < 2 else 3 + (extra >> 1)
                    hour, period = "h", "a"
                    if char == "j":
                        hour = self.hour_char
                    else:
                        best = self._allowed[0]
                        hour = best[0] if best[0] in "HKk" else "h"
                        if best[1:] in ("B", "b"):
                            period = best[1:]
                    if hour in "Hk":
                        period_length = 0
                    out.append(period * period_length + hour * hour_length)
                elif char == "J":
                    out.append("H")
                    flags |= _FLAG_CAP_J
                else:
                    out.append(char)
            index += 1
        return "".join(out), flags

    def _adjust(
        self, pattern: str, request: Skeleton, specified: Skeleton | None, flags: int
    ) -> str:
        """``adjustFieldTypes``; the hour keeps its asked length under
        ``UDATPG_MATCH_HOUR_FIELD_LENGTH`` (``self.match_hour``)."""
        out: list[str] = []
        items = tokens(pattern)
        index = 0
        while index < len(items):
            item = items[index]
            if item[0] == "'":
                quote, index = _quote_literal(items, index)
                out.append(quote)
                index += 1
                continue
            index += 1
            row_index = canonical_index(item) if item[0].isascii() and item[0].isalpha() else -1
            if row_index < 0:
                out.append(item)
                continue
            _, which, kind, _ = _TYPES[row_index]
            if not request.types[which]:
                out.append(item)
                continue
            asked_char = request.chars[which]
            asked_length = request.lengths[which]
            if asked_char == "E" and asked_length < 3:
                asked_length = 3
            length = asked_length
            if which in (MINUTE, SECOND) or (which == HOUR and not self.match_hour):
                length = len(item)
            elif specified is not None and asked_char not in "ce":
                specified_length = specified.lengths[which]
                pattern_numeric = kind > 0
                asked_numeric = request.types[which] > 0
                if specified_length == asked_length or pattern_numeric != asked_numeric:
                    length = len(item)
            keeps_found = which in (HOUR, MONTH, WEEKDAY) or (which == YEAR and asked_char != "Y")
            char = item[0] if keeps_found else asked_char
            if char == "E" and length < 3:
                char = "e"
            if which == HOUR and (
                flags & _FLAG_CAP_J
                or asked_char == self.hour_char
                or (asked_char, self.hour_char) in _SAME_HALF
            ):
                char = self.hour_char
            out.append(char * length)
        return "".join(out)

    def _best_appending(self, request: Skeleton, missing_fields: int, flags: int) -> str:
        if not missing_fields:
            return ""
        entry, missing, _ = self._best_raw(request, missing_fields)
        result = self._adjust(entry.pattern, request, _specified(entry), flags)
        last_missing = 0
        while missing:
            if last_missing == missing:
                break
            starting = missing
            entry, missing, _ = self._best_raw(request, missing)
            piece = self._adjust(entry.pattern, request, _specified(entry), flags)
            found = starting & ~missing
            top = min(found.bit_length() - 1, ZONE) if found else 0
            append = self._append_items[top]
            if append:
                name = f"'{self._field_names[top]}'"
                result = simple_format(append, result, piece, name)
            last_missing = missing
        return result

    def best_pattern(self, skeleton_text: str) -> str:
        """``getBestPattern``."""
        mapped, flags = self._map_metacharacters(skeleton_text)
        request = skeleton_of(mapped)
        entry, missing, extra = self._best_raw(request, -1)
        if not missing and not extra:
            return self._adjust(entry.pattern, request, _specified(entry), flags)
        needed = request.field_mask()
        date = self._best_appending(request, needed & _DATE_MASK, flags)
        time = self._best_appending(request, needed & _TIME_MASK, flags)
        if not date:
            return time
        if not time:
            return date
        style = 3
        if request.base_lengths[MONTH] == 4:
            style = 0 if request.base_lengths[WEEKDAY] > 0 else 1
        elif request.base_lengths[MONTH] == 3:
            style = 2
        return simple_format(self._date_time[style], time, date)


def _specified(entry: _Entry) -> Skeleton | None:
    return entry.skeleton if entry.specified else None
