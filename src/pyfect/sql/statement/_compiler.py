"""Compilers: from a fragment to SQL text and bound parameters, for one
dialect (Effect's ``Statement.Compiler`` / ``makeCompiler``)."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast
from weakref import WeakKeyDictionary

from pyfect.sql.statement._segments import (
    ArrayHelper,
    Custom,
    Fragment,
    Identifier,
    Parameter,
    RecordInsertHelper,
    RecordUpdateHelper,
    RecordUpdateHelperSingle,
    Returning,
)
from pyfect.sql.statement._segments import Literal as LiteralSegment

type Dialect = Literal["sqlite", "pg", "mysql", "mssql", "clickhouse"]

type Compiled = tuple[str, tuple[object, ...]]
"""SQL text and its parameters, in placeholder order."""

type Placeholder = Callable[[object], str]
"""Renders the placeholder of the next parameter."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CompilerOptions:
    """How a dialect renders each part (Effect's ``CompilerOptions``).

    - ``placeholder(index, value)``: the ``index``-th parameter (from 1)
    - ``on_identifier(name, without_transform)``: an escaped name
    - ``on_record_update(placeholders, alias, columns, values, returning)``:
      ``update_values``; ``alias`` is already escaped
    - ``on_custom(segment, placeholder, without_transform)``: a ``Custom``
    - ``on_insert(columns, placeholders, values, returning)`` and
      ``on_record_update_single(columns, values, returning)``: replace the
      default ``INSERT`` / ``UPDATE`` rendering when given
    """

    dialect: Dialect
    placeholder: Callable[[int, object], str]
    on_identifier: Callable[[str, bool], str]
    on_record_update: Callable[
        [str, str, str, Sequence[Sequence[object]], Compiled | None], Compiled
    ]
    on_custom: Callable[[Custom[Any, Any, Any, Any], Placeholder, bool], Compiled]
    on_insert: (
        Callable[[Sequence[str], str, Sequence[Sequence[object]], Compiled | None], Compiled] | None
    ) = None
    on_record_update_single: (
        Callable[[Sequence[str], Sequence[object], Compiled | None], Compiled] | None
    ) = None


_EMPTY_IN_KEYWORD = re.compile(r"\b(NOT\s+)?IN\s*$", re.IGNORECASE)


def _in_line_comment(sql: str, index: int) -> bool:
    # JavaScript's ``lastIndexOf(s, index)``: the last ``s`` starting at or
    # before ``index``.
    return sql.rfind("--", 0, index + 2) > sql.rfind("\n", 0, index + 1)


class Compiler:
    """Compiles fragments for ``dialect``. Results are cached per fragment
    (and per ``without_transform``)."""

    __slots__ = ("_cache", "_cache_no_transform", "_disable_transforms", "_options")

    def __init__(
        self,
        options: CompilerOptions,
        *,
        disable_transforms: bool = False,
        caches: tuple[WeakKeyDictionary[Fragment, Compiled], WeakKeyDictionary[Fragment, Compiled]]
        | None = None,
    ) -> None:
        self._options = options
        self._disable_transforms = disable_transforms
        self._cache, self._cache_no_transform = caches or (WeakKeyDictionary(), WeakKeyDictionary())

    @property
    def dialect(self) -> Dialect:
        return self._options.dialect

    @property
    def options(self) -> CompilerOptions:
        return self._options

    @property
    def without_transform(self) -> Compiler:
        """This compiler, never renaming identifiers."""
        return Compiler(
            self._options,
            disable_transforms=True,
            caches=(self._cache, self._cache_no_transform),
        )

    def compile(self, statement: Fragment, without_transform: bool = False) -> Compiled:
        """``statement``'s SQL and parameters; ``without_transform`` keeps
        identifiers as they are."""
        return self._compile(statement, without_transform, None)

    def _compile(
        self, statement: Fragment, without_transform: bool, override: Placeholder | None
    ) -> Compiled:
        without_transform = without_transform or self._disable_transforms
        cache = self._cache_no_transform if without_transform else self._cache
        if override is None:
            cached = cache.get(statement)
            if cached is not None:
                return cached
        result = _Run(self, without_transform, override).compile(statement)
        if override is None:
            cache[statement] = result
        return result


class _Run:
    """One compilation: the SQL so far, its parameters and the placeholder
    count."""

    __slots__ = ("binds", "compiler", "count", "opts", "placeholder", "sql", "without_transform")

    def __init__(
        self, compiler: Compiler, without_transform: bool, override: Placeholder | None
    ) -> None:
        self.compiler = compiler
        self.opts = compiler.options
        self.without_transform = without_transform
        self.sql = ""
        self.binds: list[object] = []
        self.count = 0
        self.placeholder: Placeholder = override or self._next_placeholder

    def _next_placeholder(self, value: object) -> str:
        self.count += 1
        return self.opts.placeholder(self.count, value)

    def _same_placeholder(self, value: object) -> str:
        return self.opts.placeholder(self.count, value)

    def _identifier(self, name: str) -> str:
        return self.opts.on_identifier(name, self.without_transform)

    def _primitive(self, value: object) -> object:
        """The value bound for a record field: a parameter's value, a
        custom segment's first bind, or the value itself."""
        if isinstance(value, Fragment):
            head = value.segments[0]
            if isinstance(head, Custom):
                compiled = self.opts.on_custom(head, self._same_placeholder, self.without_transform)
                return compiled[1][0] if compiled[1] else None
            if isinstance(head, Parameter):
                return head.value
            return None
        return value

    def _returning(self, returning: Returning) -> Compiled | None:
        if isinstance(returning, str):
            return (returning, ())
        if returning is None:
            return None
        return self.compiler._compile(returning, self.without_transform, self.placeholder)  # pyright: ignore[reportPrivateUsage]

    def _columns(self, keys: Sequence[str]) -> str:
        if not keys:
            return "()"
        return "(" + ",".join(self._identifier(key) for key in keys) + ")"

    def _rows(
        self, rows: Sequence[Any], keys: Sequence[str]
    ) -> tuple[str, list[tuple[object, ...]]]:
        """The ``(?,?),(?,?)`` placeholders of ``rows`` and their values."""
        values: list[tuple[object, ...]] = []
        placeholders = ""
        for i, row in enumerate(rows):
            placeholders += "(" if i == 0 else ",("
            items: list[object] = []
            for j, key in enumerate(keys):
                value = row.get(key)
                items.append(self._primitive(value))
                rendered = self.placeholder(value)
                placeholders += rendered if j == 0 else f",{rendered}"
            placeholders += ")"
            values.append(tuple(items))
        return placeholders, values

    def compile(self, statement: Fragment) -> Compiled:
        for segment in statement.segments:
            match segment:
                case LiteralSegment(value, params):
                    self.sql += value
                    if params:
                        self.binds.extend(params)
                case Identifier(value):
                    self.sql += self._identifier(value)
                case Parameter(value):
                    self.sql += self.placeholder(value)
                    self.binds.append(value)
                case ArrayHelper(value):
                    self._array(value)
                case RecordInsertHelper():
                    self._insert(segment)
                case RecordUpdateHelperSingle():
                    self._update_single(segment)
                case RecordUpdateHelper():
                    self._update(segment)
                case Custom():
                    sql, binds = self.opts.on_custom(
                        segment, self.placeholder, self.without_transform
                    )
                    self.sql += sql
                    self.binds.extend(binds)
        return (self.sql, tuple(self.binds))

    def _array(self, value: tuple[object, ...]) -> None:
        if not value:
            match = _EMPTY_IN_KEYWORD.search(self.sql)
            if match is None or _in_line_comment(self.sql, match.start()):
                self.sql += "()"
            elif self.opts.dialect == "pg":
                # An empty subquery is typed as text in Postgres, so compare
                # with an empty array, which takes the left operand's type.
                self.sql = self.sql[: match.start()] + (
                    "<> ALL('{}')" if match.group(1) else "= ANY('{}')"
                )
            else:
                self.sql += "(SELECT NULL WHERE 1=0)"
            return
        self.sql += "(" + ",".join(self.placeholder(v) for v in value) + ")"
        self.binds.extend(value)

    def _insert(self, segment: RecordInsertHelper) -> None:
        keys = list(segment.value[0])
        placeholders, values = self._rows(segment.value, keys)
        if self.opts.on_insert is not None:
            sql, binds = self.opts.on_insert(
                [self._identifier(key) for key in keys],
                placeholders,
                values,
                self._returning(segment.returning_identifier),
            )
            self.sql += sql
            self.binds.extend(binds)
            return
        for row in values:
            self.binds.extend(row)
        self.sql += f"{self._columns(keys)} VALUES {placeholders}"
        returning = segment.returning_identifier
        if isinstance(returning, str):
            self.sql += f" RETURNING {returning}"
        elif returning is not None:
            sql, binds = cast("Compiled", self._returning(returning))
            self.sql += f" RETURNING {sql}"
            self.binds.extend(binds)

    def _update_single(self, segment: RecordUpdateHelperSingle) -> None:
        keys = [key for key in segment.value if key not in segment.omit]
        if self.opts.on_record_update_single is not None:
            sql, binds = self.opts.on_record_update_single(
                [self._identifier(key) for key in keys],
                [self._primitive(segment.value[key]) for key in keys],
                self._returning(segment.returning_identifier),
            )
            self.sql += sql
            self.binds.extend(binds)
            return
        for i, key in enumerate(keys):
            value = segment.value[key]
            assignment = f"{self._identifier(key)} = {self.placeholder(value)}"
            self.sql += assignment if i == 0 else f", {assignment}"
            self.binds.append(self._primitive(value))
        returning = segment.returning_identifier
        mssql = self.opts.dialect == "mssql"
        if isinstance(returning, str):
            if mssql:
                self.sql += f" OUTPUT {'INSERTED.*' if returning == '*' else returning}"
            else:
                self.sql += f" RETURNING {returning}"
        elif returning is not None:
            self.sql += " OUTPUT " if mssql else " RETURNING "
            sql, binds = cast("Compiled", self._returning(returning))
            self.sql += sql
            self.binds.extend(binds)

    def _update(self, segment: RecordUpdateHelper) -> None:
        keys = list(segment.value[0])
        placeholders, values = self._rows(segment.value, keys)
        sql, binds = self.opts.on_record_update(
            placeholders,
            self.opts.on_identifier(segment.alias, True),
            self._columns(keys),
            values,
            self._returning(segment.returning_identifier),
        )
        self.sql += sql
        self.binds.extend(binds)


def make_compiler(
    *,
    dialect: Dialect,
    placeholder: Callable[[int, object], str],
    on_identifier: Callable[[str, bool], str],
    on_record_update: Callable[
        [str, str, str, Sequence[Sequence[object]], Compiled | None], Compiled
    ],
    on_custom: Callable[[Custom[Any, Any, Any, Any], Placeholder, bool], Compiled],
    on_insert: Callable[[Sequence[str], str, Sequence[Sequence[object]], Compiled | None], Compiled]
    | None = None,
    on_record_update_single: Callable[[Sequence[str], Sequence[object], Compiled | None], Compiled]
    | None = None,
) -> Compiler:
    """A compiler for ``dialect`` from its rendering callbacks (see
    ``CompilerOptions``)."""
    return Compiler(
        CompilerOptions(
            dialect=dialect,
            placeholder=placeholder,
            on_identifier=on_identifier,
            on_record_update=on_record_update,
            on_custom=on_custom,
            on_insert=on_insert,
            on_record_update_single=on_record_update_single,
        )
    )


def default_escape(c: str) -> Callable[[str], str]:
    """Escape names with the quote ``c``: wrapped in it, ``c`` doubled, and
    each dot a boundary between quoted parts (``a.b`` is ``"a"."b"``)."""
    double = c + c
    dot = c + "." + c

    def escape(name: str) -> str:
        return c + name.replace(c, double).replace(".", dot) + c

    return escape


_escape_sqlite = default_escape('"')


def _nothing(*_args: object) -> Compiled:
    return ("", ())


def make_compiler_sqlite(transform: Callable[[str], str] | None = None) -> Compiler:
    """SQLite's compiler: ``?`` placeholders and ``"quoted"`` names, renamed
    with ``transform`` unless a statement runs without transforms."""

    def on_identifier(value: str, without_transform: bool) -> str:
        if transform is None or without_transform:
            return _escape_sqlite(value)
        return _escape_sqlite(transform(value))

    return make_compiler(
        dialect="sqlite",
        placeholder=lambda _index, _value: "?",
        on_identifier=on_identifier,
        on_record_update=_nothing,
        on_custom=_nothing,
    )


__all__ = [
    "Compiled",
    "Compiler",
    "CompilerOptions",
    "Dialect",
    "Placeholder",
    "default_escape",
    "make_compiler",
    "make_compiler_sqlite",
]
