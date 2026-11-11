"""Fragments and the segments they are made of.

A ``Fragment`` is a sequence of segments: SQL text (``Literal``), escaped
names (``Identifier``), bound values (``Parameter``) and the helpers that
expand into several of them (``ArrayHelper`` for ``IN`` lists, the record
helpers for ``INSERT`` / ``UPDATE``, ``Custom`` for a dialect's own).

SQL text only ever comes from a ``LiteralString`` (a string literal in the
source, checked by pyright) or from ``unsafe``; values always become
parameters. ``segments_of`` reads a template into segments:
``"... {name} ..."`` with ``str.format``'s placeholders, or a t-string on
Python 3.14.
"""

from __future__ import annotations

import string
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, LiteralString, Self, TypeIs, cast, overload

from pyfect._digits import parse_digits

if sys.version_info >= (3, 14):
    from string.templatelib import Interpolation, Template

    type SqlText = LiteralString | Template
    """The SQL text of a statement: a string literal with ``{}``
    placeholders, or a t-string."""
else:
    type SqlText = LiteralString
    """The SQL text of a statement: a string literal with ``{}``
    placeholders (a t-string too on Python 3.14)."""


class Fragment:
    """A piece of SQL: its ``segments``. Statements are fragments too, so
    any of them can be placed inside another statement."""

    __slots__ = ("__weakref__", "segments")

    segments: tuple[Segment, ...]

    def __init__(self, segments: Sequence[Segment]) -> None:
        self.segments = tuple(segments)

    def __repr__(self) -> str:
        return f"Fragment({list(self.segments)!r})"


def fragment(segments: Sequence[Segment]) -> Fragment:
    return Fragment(segments)


def is_fragment(u: object) -> TypeIs[Fragment]:
    return isinstance(u, Fragment)


@dataclass(frozen=True, slots=True)
class Literal:
    """SQL text, inserted as it is, followed by its bound ``params``. The
    text is a ``LiteralString``, so pyright rejects text built at runtime
    here too; ``literal_unsafe`` is the explicit way to make one from it."""

    value: LiteralString
    params: tuple[object, ...] | None = None


def literal(value: LiteralString, params: Sequence[object] | None = None) -> Literal:
    """SQL text from a string literal (the only way plain text becomes SQL,
    with ``unsafe``)."""
    return Literal(value, None if params is None else tuple(params))


def literal_unsafe(value: str, params: Sequence[object] | None = None) -> Literal:
    """SQL text from any string: never build it from untrusted input."""
    return Literal(cast("LiteralString", value), None if params is None else tuple(params))


@dataclass(frozen=True, slots=True)
class Identifier:
    """A table, column or alias name, escaped by the dialect (and renamed by
    the client's query-name transform)."""

    value: str


def identifier(value: str) -> Identifier:
    return Identifier(value)


@dataclass(frozen=True, slots=True)
class Parameter:
    """A value bound to a placeholder."""

    value: object


def parameter(value: object) -> Parameter:
    return Parameter(value)


@dataclass(frozen=True, slots=True)
class ArrayHelper:
    """A parenthesized list of values (or fragments), for ``IN``. Empty, it
    compiles to a list that matches nothing."""

    value: tuple[object, ...]


def array_helper(value: Sequence[object]) -> ArrayHelper:
    return ArrayHelper(_values(value))


type Returning = str | Fragment | None
"""What a record helper returns: SQL text or a fragment."""


def _returning(sql: LiteralString | Identifier | Fragment) -> str | Fragment:
    return sql if isinstance(sql, (str, Fragment)) else Fragment((sql,))


@dataclass(frozen=True, slots=True)
class RecordInsertHelper:
    """Rows to insert: ``(columns) VALUES (...), (...)`` from the first row's
    keys, then ``RETURNING`` when ``returning`` gave one."""

    value: tuple[Mapping[str, object], ...]
    returning_identifier: Returning = field(default=None, kw_only=True)

    def returning(self, sql: LiteralString | Identifier | Fragment) -> Self:
        return replace(self, returning_identifier=_returning(sql))


def record_insert_helper(value: Sequence[Mapping[str, object]]) -> RecordInsertHelper:
    rows = tuple(value)
    if not rows:
        raise ValueError("insert needs at least one row")
    return RecordInsertHelper(rows)


@dataclass(frozen=True, slots=True)
class RecordUpdateHelper:
    """Rows for a multi-row update, as a ``VALUES`` list named ``alias``
    (escaped, never renamed). Not supported by SQLite."""

    value: tuple[Mapping[str, object], ...]
    alias: str
    returning_identifier: Returning = field(default=None, kw_only=True)

    def returning(self, sql: LiteralString | Identifier | Fragment) -> Self:
        return replace(self, returning_identifier=_returning(sql))


def record_update_helper(value: Sequence[Mapping[str, object]], alias: str) -> RecordUpdateHelper:
    rows = tuple(value)
    if not rows:
        raise ValueError("update_values needs at least one row")
    return RecordUpdateHelper(rows, alias)


@dataclass(frozen=True, slots=True)
class RecordUpdateHelperSingle:
    """One row's ``column = value, ...`` assignments, without the columns in
    ``omit``."""

    value: Mapping[str, object]
    omit: tuple[str, ...]
    returning_identifier: Returning = field(default=None, kw_only=True)

    def returning(self, sql: LiteralString | Identifier | Fragment) -> Self:
        return replace(self, returning_identifier=_returning(sql))


def record_update_helper_single(
    value: Mapping[str, object], omit: Sequence[str]
) -> RecordUpdateHelperSingle:
    return RecordUpdateHelperSingle(value, _names(omit))


@dataclass(frozen=True, slots=True)
class Custom[K: str = str, A = None, B = None, C = None]:
    """A segment of kind ``kind`` that the compiler's ``on_custom`` renders."""

    kind: K
    param_a: A
    param_b: B
    param_c: C


def custom[K: str, A, B, C](kind: K) -> Callable[[A, B, C], Custom[K, A, B, C]]:
    """The constructor of ``kind``'s custom segments."""
    return lambda a, b, c: Custom(kind, a, b, c)


def is_custom(kind: str) -> Callable[[object], TypeIs[Custom[Any, Any, Any, Any]]]:
    """A guard for custom segments of ``kind``."""

    def guard(u: object) -> TypeIs[Custom[Any, Any, Any, Any]]:
        return isinstance(u, Custom) and cast("Custom[Any, Any, Any, Any]", u).kind == kind

    return guard


type Segment = (
    Literal
    | Identifier
    | Parameter
    | ArrayHelper
    | RecordInsertHelper
    | RecordUpdateHelper
    | RecordUpdateHelperSingle
    | Custom[Any, Any, Any, Any]
)

type Helper = (
    ArrayHelper
    | RecordInsertHelper
    | RecordUpdateHelper
    | RecordUpdateHelperSingle
    | Identifier
    | Custom[Any, Any, Any, Any]
)
"""The segments a template places as they are (not as parameters)."""

_SEGMENT_TYPES = (
    Literal,
    Identifier,
    Parameter,
    ArrayHelper,
    RecordInsertHelper,
    RecordUpdateHelper,
    RecordUpdateHelperSingle,
    Custom,
)


def is_segment(u: object) -> TypeIs[Segment]:
    return isinstance(u, _SEGMENT_TYPES)


# --- templates -----------------------------------------------------------------


def _placed(value: object) -> tuple[Segment, ...]:
    """A template value: a fragment's segments, a segment as it is, or a
    parameter."""
    if isinstance(value, Fragment):
        return value.segments
    if isinstance(value, _SEGMENT_TYPES):
        return (cast("Segment", value),)
    return (Parameter(value),)


_FORMATTER = string.Formatter()


def segments_of(
    template: SqlText, args: Sequence[object], kwargs: Mapping[str, object]
) -> tuple[Segment, ...]:
    """The segments of ``template``: its text as literals, and each
    placeholder's value (``{}`` / ``{0}`` from ``args``, ``{name}`` from
    ``kwargs``; ``{{`` and ``}}`` are braces). Every value must be used, and
    placeholders take no conversion or format spec."""
    if sys.version_info >= (3, 14) and isinstance(template, Template):
        if args or kwargs:
            raise TypeError("a t-string carries its own values; pass no other arguments")
        return _segments_of_template(template)
    return _segments_of_format(template, args, kwargs)


class _Values:
    """The values of a ``str.format``-style template, and which were used."""

    __slots__ = ("args", "auto", "kwargs", "used_args", "used_kwargs")

    def __init__(self, args: Sequence[object], kwargs: Mapping[str, object]) -> None:
        self.args = args
        self.kwargs = kwargs
        self.used_args: set[int] = set()
        self.used_kwargs: set[str] = set()
        self.auto: int | None = None

    def get(self, name: str) -> object:
        if name == "":
            if self.auto is None:
                if self.used_args:
                    raise ValueError("cannot mix automatic and numbered placeholders")
                self.auto = 0
            index = self.auto
            self.auto += 1
            return self._positional(index)
        if (position := parse_digits(name)) is not None:
            if self.auto is not None:
                raise ValueError("cannot mix automatic and numbered placeholders")
            return self._positional(position)
        if name.isidentifier():
            if name not in self.kwargs:
                raise KeyError(f"no value for placeholder {{{name}}}")
            self.used_kwargs.add(name)
            return self.kwargs[name]
        raise ValueError(f"placeholder {{{name}}} must be empty, a number or a name")

    def _positional(self, index: int) -> object:
        if index >= len(self.args):
            raise IndexError(f"no value for placeholder {{{index}}}")
        self.used_args.add(index)
        return self.args[index]

    def check_all_used(self) -> None:
        unused = [str(i) for i in range(len(self.args)) if i not in self.used_args]
        unused += [name for name in self.kwargs if name not in self.used_kwargs]
        if unused:
            raise TypeError(f"values not used by the template: {', '.join(unused)}")


def _segments_of_format(
    template: LiteralString, args: Sequence[object], kwargs: Mapping[str, object]
) -> tuple[Segment, ...]:
    segments: list[Segment] = []
    values = _Values(args, kwargs)
    for text, name, spec, conversion in _FORMATTER.parse(template):
        if text:
            # A piece of the template, which is a ``LiteralString``.
            segments.append(Literal(cast("LiteralString", text)))
        if name is None:
            continue
        if spec or conversion:
            raise ValueError(f"placeholder {{{name}}} takes no conversion or format spec")
        segments.extend(_placed(values.get(name)))
    values.check_all_used()
    return tuple(segments)


if sys.version_info >= (3, 14):

    def _segments_of_template(template: Template) -> tuple[Segment, ...]:
        segments: list[Segment] = []
        for item in template:
            if isinstance(item, Interpolation):
                if item.conversion is not None or item.format_spec:
                    raise ValueError(f"{{{item.expression}}} takes no conversion or format spec")
                segments.extend(_placed(item.value))
            else:
                # A t-string's text is written in the source.
                segments.append(Literal(cast("LiteralString", item)))
        return tuple(segments)


# --- combinators -----------------------------------------------------------------


def _clause(clause: LiteralString | Fragment) -> tuple[Segment, ...]:
    return clause.segments if isinstance(clause, Fragment) else (Literal(clause),)


def join(
    separator: LiteralString, add_parens: bool = True, fallback: LiteralString = ""
) -> Callable[[Sequence[LiteralString | Fragment]], Fragment]:
    """Join clauses with ``separator``: several in parentheses (unless
    ``add_parens=False``), one as it is, none as ``fallback``."""
    separator_segment = Literal(separator)
    fallback_fragment = Fragment((Literal(fallback),))

    def joined(clauses: Sequence[LiteralString | Fragment]) -> Fragment:
        if not clauses:
            return fallback_fragment
        if len(clauses) == 1:
            return Fragment(_clause(clauses[0]))
        segments: list[Segment] = [Literal("(")] if add_parens else []
        segments.extend(_clause(clauses[0]))
        for clause in clauses[1:]:
            segments.append(separator_segment)
            segments.extend(_clause(clause))
        if add_parens:
            segments.append(Literal(")"))
        return Fragment(segments)

    return joined


and_ = join(" AND ", True, "1=1")
"""Clauses joined with ``AND`` (``1=1`` for none)."""

or_ = join(" OR ", True, "1=1")
"""Clauses joined with ``OR`` (``1=1`` for none)."""

_csv_raw = join(",", False)
_EMPTY_FRAGMENT = Fragment((Literal(""),))


def csv(
    values: Sequence[LiteralString | Fragment], prefix: LiteralString | None = None
) -> Fragment:
    """Comma-separated values, after ``prefix`` and a space (``ORDER BY``,
    ``GROUP BY``); nothing at all for no values."""
    if not values:
        return _EMPTY_FRAGMENT
    if prefix is None:
        return _csv_raw(values)
    return Fragment((Literal(f"{prefix} "), *_csv_raw(values).segments))


_NEVER = Fragment((Literal("1=0"),))


@overload
def in_(values: Sequence[object], /) -> ArrayHelper: ...
@overload
def in_(column: str, values: Sequence[object], /) -> Fragment: ...
def in_(*args: Any) -> ArrayHelper | Fragment:
    """``in_(values)``: the list ``(a, b, ...)``; ``in_(column, values)``:
    ``column IN (...)``, or ``1=0`` for no values."""
    if len(args) == 1:
        return array_helper(args[0])
    column, values = args
    items = _values(values)
    if not items:
        return _NEVER
    return Fragment((Identifier(column), Literal(" IN "), ArrayHelper(items)))


def insert(value: Mapping[str, object] | Sequence[Mapping[str, object]]) -> RecordInsertHelper:
    """Rows to insert (one mapping, or several)."""
    return record_insert_helper([value] if isinstance(value, Mapping) else value)


def update(value: Mapping[str, object], omit: Sequence[str] = ()) -> RecordUpdateHelperSingle:
    """One row's ``SET`` assignments, without the ``omit`` columns."""
    return record_update_helper_single(value, omit)


def update_values(value: Sequence[Mapping[str, object]], alias: str) -> RecordUpdateHelper:
    """Several rows to update from a ``VALUES`` list named ``alias``. Not
    supported by SQLite."""
    return record_update_helper(value, alias)


def _values(value: Sequence[object]) -> tuple[object, ...]:
    if isinstance(value, (str, bytes)):
        raise TypeError("expected a sequence of values, got a string")
    return tuple(value)


def _names(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, str):
        raise TypeError("expected a sequence of column names, got a string")
    return tuple(value)


__all__ = [
    "ArrayHelper",
    "Custom",
    "Fragment",
    "Helper",
    "Identifier",
    "Literal",
    "Parameter",
    "RecordInsertHelper",
    "RecordUpdateHelper",
    "RecordUpdateHelperSingle",
    "Segment",
    "SqlText",
    "and_",
    "array_helper",
    "csv",
    "custom",
    "fragment",
    "identifier",
    "in_",
    "insert",
    "is_custom",
    "is_fragment",
    "is_segment",
    "join",
    "literal",
    "literal_unsafe",
    "or_",
    "parameter",
    "record_insert_helper",
    "record_update_helper",
    "record_update_helper_single",
    "segments_of",
    "update",
    "update_values",
]
