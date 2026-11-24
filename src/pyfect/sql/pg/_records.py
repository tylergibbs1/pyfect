"""Anonymous records (``ROW(...)``, ``(a, b)``) with typed fields, as Effect's
``PgTypes`` decodes them.

A record's text form has no field types, so psycopg reads every field as
``str``. Its binary form names each field's type, and libpq takes one result
format for a whole statement. So a statement whose result has a ``record`` or
``record[]`` column is described first (once per session), and runs in binary when every column
loads in binary as it does in text (``loads_alike``); otherwise it stays text.
Inside a record, a field whose type has no binary loader reads as UTF-8 text
(``install``).
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Sequence
from typing import TYPE_CHECKING

import psycopg
from psycopg import pq
from psycopg.adapt import Loader

if TYPE_CHECKING:
    from psycopg.abc import Buffer
    from psycopg.adapt import AdaptersMap

_RECORDS = frozenset((2249, 2287))
"""``record`` and ``record[]``."""
_UNKNOWN = 0
"""psycopg's fallback key: the loader for a type with none of its own."""
_FLOAT4S = frozenset((700, 1021))
"""``float4`` and ``float4[]``: binary gives the 32-bit float's exact value
(``1.100000023841858``), text its shortest decimal (``1.1``)."""
_BINARY = pq.Format.BINARY
_TEXT = pq.Format.TEXT
_CACHE_SIZE = 512


class _Utf8BinaryLoader(Loader):
    """A type with no binary loader of its own reads as UTF-8 text, as
    Effect's fallback does: text-like types (enums, ``citext``, ``xml``,
    an untyped literal) send their text. PostgreSQL's text never holds a NUL
    byte, while binary layouts almost always do, so a NUL (or invalid UTF-8)
    fails, naming the type, instead of passing binary data off as text."""

    format = _BINARY

    def load(self, data: Buffer) -> str:
        try:
            text = bytes(data).decode()
        except UnicodeDecodeError:
            raise self._unreadable("is not valid UTF-8") from None
        if "\x00" in text:
            raise self._unreadable("contains a NUL byte, so it is binary data rather than text")
        return text

    def _unreadable(self, reason: str) -> psycopg.DataError:
        return psycopg.DataError(
            f"Cannot decode a value of type OID {self.oid}: no binary loader is registered for "
            f"the type, so it is read as UTF-8 text, but the value {reason}. Register a binary "
            "loader for the type in the client's types (a psycopg AdaptersMap), or cast the "
            "value to text in the query."
        )


def install(adapters: AdaptersMap) -> None:
    """Add the UTF-8 fallback a session's records need, unless ``adapters``
    (a session's own, copied from ``config.types``) has a fallback of its own."""
    defaults = psycopg.adapters
    if adapters.get_loader(_UNKNOWN, _BINARY) is defaults.get_loader(_UNKNOWN, _BINARY):
        adapters.register_loader(_UNKNOWN, _Utf8BinaryLoader)


def loads_alike(adapters: AdaptersMap, oid: int) -> bool:
    """Whether a column of ``oid`` gives the same value in binary as in text:
    the type has a binary loader of its own, and its text loader is psycopg's
    default unless its binary loader is not (one registered for both)."""
    binary = adapters.get_loader(oid, _BINARY)
    if binary is None or oid in _FLOAT4S:
        return False
    defaults = psycopg.adapters
    return binary is not defaults.get_loader(oid, _BINARY) or adapters.get_loader(
        oid, _TEXT
    ) is defaults.get_loader(oid, _TEXT)


def wants_binary(adapters: AdaptersMap, column_oids: Sequence[int]) -> bool:
    """Whether a result with these column types loads in binary: it has a
    record column and every column loads alike."""
    return any(oid in _RECORDS for oid in column_oids) and all(
        loads_alike(adapters, oid) for oid in column_oids
    )


type StatementKey = tuple[bytes, tuple[int, ...]]
"""A statement's text and parameter types, which fix its result's types."""


class ResultFormats:
    """A session's statements' result formats, so each is described once:
    the ``_CACHE_SIZE`` used most recently."""

    __slots__ = ("_binary",)

    def __init__(self) -> None:
        self._binary: OrderedDict[StatementKey, bool] = OrderedDict()

    def get(self, key: StatementKey) -> bool | None:
        binary = self._binary.get(key)
        if binary is not None:
            self._binary.move_to_end(key)
        return binary

    def put(self, key: StatementKey, binary: bool) -> None:
        self._binary[key] = binary
        if len(self._binary) > _CACHE_SIZE:
            self._binary.popitem(last=False)

    def clear(self) -> None:
        self._binary.clear()


__all__ = ["ResultFormats", "install", "loads_alike", "wants_binary"]
