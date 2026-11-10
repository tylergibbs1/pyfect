"""The CSV channels over rows and header records: ``decode_string``,
``decode``, ``encode_string`` and ``encode``, with the record-level channels
the schema adapters build on."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Never, cast, overload

from pyfect._js import text_encode
from pyfect._json_text import quote
from pyfect._primitives import _FailCause, _Succeed, _Suspend, _Sync
from pyfect.cause import Cause
from pyfect.cause import fail as fail_cause
from pyfect.channel import Channel, decode_text, from_transform
from pyfect.channel._base import AnyPull, end_with
from pyfect.encoding.csv._error import CsvError, Row
from pyfect.encoding.csv._parser import Parsed, Parser
from pyfect.pull import match_effect
from pyfect.scope import CloseableScope

type Newline = Literal["\n", "\r\n"]
type HeaderRecord = dict[str, str]
"""A record keyed by the header row's names."""

DEFAULT_MAX_RECORD_SIZE = 1024 * 1024
"""1 MiB, in UTF-16 code units."""


def check_delimiter(delimiter: str) -> str:
    if len(delimiter) != 1 or delimiter in ('"', "\r", "\n"):
        raise ValueError(
            "Csv: delimiter must be one character other than a quote or line break, "
            f"got {delimiter}"
        )
    return delimiter


@dataclass(frozen=True, slots=True)
class Decoded:
    value: Row | HeaderRecord
    record: int


def decode_records(
    delimiter: str, max_record_size: float, ignore_empty_lines: bool, headers: bool
) -> Channel[tuple[Decoded, ...], Any, Any, tuple[str, ...], Any, Any]:
    """Text chunks to records, each with its record number."""
    check_delimiter(delimiter)
    if not max_record_size > 0:
        raise ValueError(f"Csv: maxRecordSize must be positive, got {max_record_size}")

    def build(upstream: AnyPull) -> AnyPull:
        parser = Parser(delimiter, max_record_size, ignore_empty_lines)
        names: list[Row] = []  # the header row, once read
        done: list[object] = []

        def to_record(row: Parsed) -> Decoded:
            if not headers:
                return Decoded(row.cells, row.record)
            header = names[0]
            if len(row.cells) != len(header):
                raise CsvError(
                    "Header",
                    f"Expected {len(header)} cells, got {len(row.cells)}",
                    row.record,
                    row.line,
                )
            return Decoded(dict(zip(header, row.cells, strict=True)), row.record)

        def emit(run: Callable[[list[Parsed]], None]) -> AnyPull:
            rows: list[Parsed] = []
            out: list[Decoded] = []
            try:
                run(rows)
                for row in rows:
                    if headers and not names:
                        if len(set(row.cells)) != len(row.cells):
                            raise CsvError("Header", "Duplicate header name", row.record, row.line)
                        names.append(row.cells)
                    else:
                        out.append(to_record(row))
            except CsvError as error:
                return _FailCause(fail_cause(error))
            return _Succeed(tuple(out)) if out else pull

        def feed(texts: tuple[str, ...]) -> AnyPull:
            def run(out: list[Parsed]) -> None:
                for text in texts:
                    parser.feed(text, out)

            return emit(run)

        def failed(cause: Cause[Any]) -> AnyPull:
            return _FailCause(cause)

        def ended(leftover: object) -> AnyPull:
            done.append(leftover)
            return emit(parser.end)

        def next_pull() -> AnyPull:
            if done:
                return end_with(done[0])
            return match_effect(upstream, on_success=feed, on_failure=failed, on_done=ended)

        pull: AnyPull = _Suspend(next_pull)
        return pull

    def transform(upstream: AnyPull, _scope: CloseableScope) -> AnyPull:
        return _Sync(lambda: build(upstream))

    return cast(
        "Channel[tuple[Decoded, ...], Any, Any, tuple[str, ...], Any, Any]",
        from_transform(transform),
    )


def _values(records: tuple[Decoded, ...]) -> tuple[Row | HeaderRecord, ...]:
    return tuple(record.value for record in records)


@overload
def decode_string[E = Never, D = None](
    *,
    headers: Literal[True],
    delimiter: str = ",",
    max_record_size: float = DEFAULT_MAX_RECORD_SIZE,
    ignore_empty_lines: bool = False,
) -> Channel[tuple[HeaderRecord, ...], E | CsvError, D, tuple[str, ...], E, D]: ...
@overload
def decode_string[E = Never, D = None](
    *,
    headers: Literal[False] = False,
    delimiter: str = ",",
    max_record_size: float = DEFAULT_MAX_RECORD_SIZE,
    ignore_empty_lines: bool = False,
) -> Channel[tuple[Row, ...], E | CsvError, D, tuple[str, ...], E, D]: ...
@overload
def decode_string[E = Never, D = None](
    *,
    headers: bool,
    delimiter: str = ",",
    max_record_size: float = DEFAULT_MAX_RECORD_SIZE,
    ignore_empty_lines: bool = False,
) -> Channel[tuple[Row | HeaderRecord, ...], E | CsvError, D, tuple[str, ...], E, D]: ...
def decode_string(
    *,
    headers: bool = False,
    delimiter: str = ",",
    max_record_size: float = DEFAULT_MAX_RECORD_SIZE,
    ignore_empty_lines: bool = False,
) -> Channel[Any, Any, Any, Any, Any, Any]:
    """Parse chunks of text into records: rows of cells, or with ``headers``
    dicts keyed by the first record's names (which must be unique, and every
    record as wide). ``max_record_size`` bounds a record's length in UTF-16
    code units, quotes and delimiters included (``math.inf`` for none);
    ``ignore_empty_lines`` skips records with no characters, which are
    otherwise one empty cell. A leading byte-order mark is skipped, and LF,
    CRLF and CR end a record. Invalid options raise ``ValueError`` here; the
    parser's state is made per run."""
    return decode_records(delimiter, max_record_size, ignore_empty_lines, headers).map(_values)


@overload
def decode[E = Never, D = None](
    *,
    headers: Literal[True],
    delimiter: str = ",",
    max_record_size: float = DEFAULT_MAX_RECORD_SIZE,
    ignore_empty_lines: bool = False,
) -> Channel[tuple[HeaderRecord, ...], E | CsvError, D, tuple[bytes, ...], E, D]: ...
@overload
def decode[E = Never, D = None](
    *,
    headers: Literal[False] = False,
    delimiter: str = ",",
    max_record_size: float = DEFAULT_MAX_RECORD_SIZE,
    ignore_empty_lines: bool = False,
) -> Channel[tuple[Row, ...], E | CsvError, D, tuple[bytes, ...], E, D]: ...
@overload
def decode[E = Never, D = None](
    *,
    headers: bool,
    delimiter: str = ",",
    max_record_size: float = DEFAULT_MAX_RECORD_SIZE,
    ignore_empty_lines: bool = False,
) -> Channel[tuple[Row | HeaderRecord, ...], E | CsvError, D, tuple[bytes, ...], E, D]: ...
def decode(
    *,
    headers: bool = False,
    delimiter: str = ",",
    max_record_size: float = DEFAULT_MAX_RECORD_SIZE,
    ignore_empty_lines: bool = False,
) -> Channel[Any, Any, Any, Any, Any, Any]:
    """``decode_string`` of UTF-8 bytes."""
    text: Channel[Any, Any, Any, Any, Any, Any] = decode_text("utf-8", ignore_bom=True)
    return text.pipe_to(
        decode_string(
            headers=headers,
            delimiter=delimiter,
            max_record_size=max_record_size,
            ignore_empty_lines=ignore_empty_lines,
        )
    )


# --- encoding ---------------------------------------------------------------------


def make_writer(
    delimiter: str, newline: str, columns: Sequence[str] | None, headers: bool
) -> tuple[str | None, Callable[[object], str]]:
    """The header line (when ``headers``) and a function writing one record."""
    check_delimiter(delimiter)
    if newline not in ("\n", "\r\n"):
        raise ValueError(f'Csv: newline must be "\\n" or "\\r\\n", got {quote(newline)}')
    if headers and columns is None:
        raise ValueError("Csv: headers requires columns")
    special = re.compile(f'[{re.escape(delimiter)}"\r\n]')

    def cell(value: object) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise TypeError(f"Csv: expected a string cell, got {type(value).__name__}")
        # A leading BOM is quoted so that decoders do not strip it.
        if special.search(value) or value.startswith("\ufeff"):
            return '"' + value.replace('"', '""') + '"'
        return value

    def write(cells: Sequence[object]) -> str:
        # A single empty cell is quoted so that it is not read back as an empty line.
        if len(cells) == 1 and cells[0] in ("", None):
            return '""' + newline
        return delimiter.join(map(cell, cells)) + newline

    def write_record(value: object) -> str:
        if isinstance(value, list | tuple):
            return write(cast("Sequence[object]", value))
        if columns is None:
            raise TypeError("Csv: encoding object records requires columns")
        record = cast("Mapping[str, object]", value)
        return write([record.get(key) for key in columns])

    return (write(columns) if headers and columns is not None else None), write_record


def encode_records(
    delimiter: str, newline: str, columns: Sequence[str] | None, headers: bool
) -> Channel[tuple[str, ...], Any, Any, tuple[Any, ...], Any, Any]:
    """Records to text, one string per record, after the header line."""
    header, write_record = make_writer(delimiter, newline, columns, headers)

    def written(records: tuple[object, ...]) -> AnyPull:
        return _Sync(lambda: tuple(map(write_record, records)))

    def build(upstream: AnyPull) -> AnyPull:
        pending = [header] if header is not None else []

        def next_pull() -> AnyPull:
            if pending:
                return _Succeed((pending.pop(),))
            return upstream.flat_map(written)

        return _Suspend(next_pull)

    def transform(upstream: AnyPull, _scope: CloseableScope) -> AnyPull:
        return _Sync(lambda: build(upstream))

    return cast(
        "Channel[tuple[str, ...], Any, Any, tuple[Any, ...], Any, Any]", from_transform(transform)
    )


def _joined_bytes(texts: tuple[str, ...]) -> tuple[bytes, ...]:
    return (text_encode("".join(texts)),)


@overload
def encode_string[E = Never, D = None](
    *,
    columns: Sequence[str],
    headers: bool = False,
    delimiter: str = ",",
    newline: Newline = "\r\n",
) -> Channel[tuple[str, ...], E, D, tuple[Mapping[str, str | None], ...], E, D]: ...
@overload
def encode_string[E = Never, D = None](
    *,
    columns: None = None,
    headers: Literal[False] = False,
    delimiter: str = ",",
    newline: Newline = "\r\n",
) -> Channel[tuple[str, ...], E, D, tuple[Sequence[str | None], ...], E, D]: ...
def encode_string(
    *,
    columns: Sequence[str] | None = None,
    headers: bool = False,
    delimiter: str = ",",
    newline: Newline = "\r\n",
) -> Channel[Any, Any, Any, Any, Any, Any]:
    """Write records as text, one string per record, each ending with
    ``newline``. Without ``columns`` records are rows of cells; with them,
    mappings written by those keys (a missing or ``None`` value is an empty
    cell), and ``headers`` writes the columns first, even for an empty
    stream. A cell that is not a string is a defect (``TypeError``); invalid
    options raise ``ValueError`` here."""
    return encode_records(delimiter, newline, columns, headers)


@overload
def encode[E = Never, D = None](
    *,
    columns: Sequence[str],
    headers: bool = False,
    delimiter: str = ",",
    newline: Newline = "\r\n",
) -> Channel[tuple[bytes, ...], E, D, tuple[Mapping[str, str | None], ...], E, D]: ...
@overload
def encode[E = Never, D = None](
    *,
    columns: None = None,
    headers: Literal[False] = False,
    delimiter: str = ",",
    newline: Newline = "\r\n",
) -> Channel[tuple[bytes, ...], E, D, tuple[Sequence[str | None], ...], E, D]: ...
def encode(
    *,
    columns: Sequence[str] | None = None,
    headers: bool = False,
    delimiter: str = ",",
    newline: Newline = "\r\n",
) -> Channel[Any, Any, Any, Any, Any, Any]:
    """``encode_string`` as UTF-8 bytes, one ``bytes`` per input chunk."""
    return encode_records(delimiter, newline, columns, headers).map(_joined_bytes)


__all__ = [
    "DEFAULT_MAX_RECORD_SIZE",
    "HeaderRecord",
    "Newline",
    "decode",
    "decode_string",
    "encode",
    "encode_string",
]
