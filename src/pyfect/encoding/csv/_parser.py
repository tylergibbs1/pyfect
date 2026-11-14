"""The CSV record parser behind ``csv.decode_string``: RFC 4180 with a
configurable delimiter, fed one chunk of text at a time.

Positions and sizes count UTF-16 code units, as Effect's do: a chunk with
characters outside the BMP is parsed as surrogate pairs, and each cell is
joined back when it is written.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pyfect.encoding.csv._error import CsvError, CsvErrorKind, Row

_ASTRAL = re.compile("[\U00010000-\U0010ffff]")
_SURROGATE = re.compile("[\ud800-\udfff]")

# States. QUOTE_IN_QUOTED follows a quote inside a quoted field, which either
# closes the field or starts an escaped quote.
_FIELD_START = 0
_UNQUOTED = 1
_QUOTED = 2
_QUOTE_IN_QUOTED = 3


def _pair(match: re.Match[str]) -> str:
    code = ord(match.group()) - 0x10000
    return chr(0xD800 + (code >> 10)) + chr(0xDC00 + (code & 0x3FF))


def _to_code_units(text: str) -> str:
    return _ASTRAL.sub(_pair, text) if _ASTRAL.search(text) else text


def _from_code_units(text: str) -> str:
    if not _SURROGATE.search(text):
        return text
    return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")


@dataclass(frozen=True, slots=True)
class Parsed:
    cells: Row
    record: int
    line: int


class Parser:
    """One run's parser state, carried across chunks."""

    def __init__(self, delimiter: str, max_record_size: float, ignore_empty_lines: bool) -> None:
        self.delimiter = delimiter
        self.max_record_size = max_record_size
        self.ignore_empty_lines = ignore_empty_lines
        self.special = re.compile(f'[{re.escape(delimiter)}\r\n"]')
        self.state = _FIELD_START
        # The partial field's pieces, carried across chunks and joined once it ends, so a field
        # trickled in small chunks costs linear time.
        self.field: list[str] = []
        self.cells: list[str] = []
        self.size = 0  # the current record's size before the current chunk
        self.record = 1
        self.line = 1
        self.record_line = 1
        self.started = False
        self.skip_lf = False  # a CR ended the previous record: a leading LF completes a CRLF
        self.quoted_cr = False  # quoted content ended with a CR: a leading LF is no new line

    def fail(self, kind: CsvErrorKind, message: str) -> CsvError:
        column = len(self.cells) + 1 if kind == "Syntax" else None
        return CsvError(kind, message, self.record, self.record_line, column)

    def check_size(self, size: float) -> None:
        if size > self.max_record_size:
            limit = self.max_record_size
            shown = int(limit) if limit == int(limit) else limit
            raise self.fail("RecordSize", f"CSV record exceeds maxRecordSize of {shown}")

    def fail_syntax(self, size: int, message: str) -> CsvError:
        # A record that is already too large reports its size, not the syntax error.
        self.check_size(size)
        return self.fail("Syntax", message)

    def push_cell(self, field: str) -> None:
        self.cells.append(_from_code_units(field))

    def end_record(self, size: int, out: list[Parsed]) -> None:
        self.check_size(size)
        if size > 0 or not self.ignore_empty_lines:
            out.append(Parsed(tuple(self.cells), self.record, self.record_line))
        self.cells = []
        self.size = 0
        self.record += 1

    def count_lines(self, text: str, start: int, end: int) -> None:
        if end <= start:
            return
        segment = text[start:end]
        crlf = segment.count("\r\n")
        self.line += segment.count("\r") + segment.count("\n") - crlf
        if segment[0] == "\n" and self.quoted_cr:
            self.line -= 1
        self.quoted_cr = segment[-1] == "\r"

    def feed(self, chunk: str, out: list[Parsed]) -> None:  # noqa: PLR0912, PLR0915 - one state machine
        text = _to_code_units(chunk)
        length = len(text)
        delimiter = self.delimiter
        i = 0
        if length > 0 and not self.started:
            self.started = True
            if text[0] == "\ufeff":
                i = 1
        # The current record starts at ``start`` in this chunk, so its size at
        # ``i`` is ``self.size + i - start``.
        start = i
        state = self.state
        field = self.field
        while i < length:
            if state == _FIELD_START:
                if self.skip_lf:
                    self.skip_lf = False
                    if text[i] == "\n":
                        i += 1
                        start = i
                        continue
                if text[i] == '"':
                    state = _QUOTED
                    self.quoted_cr = False
                    i += 1
                    continue
                state = _UNQUOTED
            if state == _UNQUOTED:
                found = self.special.search(text, i)
                j = length if found is None else found.start()
                if j > i:
                    field.append(text[i:j])
                if found is None:
                    i = j
                    break
                c = text[j]
                if c == '"':
                    raise self.fail_syntax(
                        self.size + j - start, "Unexpected quote in an unquoted field"
                    )
                self.push_cell("".join(field))
                field = []
                state = _FIELD_START
                i = j + 1
                if c != delimiter:
                    self.end_record(self.size + j - start, out)
                    self.line += 1
                    self.record_line = self.line
                    self.skip_lf = c == "\r"
                    start = i
                continue
            if state == _QUOTED:
                end = text.find('"', i)
                j = length if end == -1 else end
                if j > i:
                    field.append(text[i:j])
                    self.count_lines(text, i, j)
                if end == -1:
                    i = j
                    break
                state = _QUOTE_IN_QUOTED
                i = j + 1
                continue
            # _QUOTE_IN_QUOTED
            c = text[i]
            if c == '"':
                field.append('"')
                state = _QUOTED
                self.quoted_cr = False
                i += 1
            elif c in (delimiter, "\r", "\n"):
                self.push_cell("".join(field))
                field = []
                state = _FIELD_START
                i += 1
                if c != delimiter:
                    self.end_record(self.size + i - 1 - start, out)
                    self.line += 1
                    self.record_line = self.line
                    self.skip_lf = c == "\r"
                    start = i
            else:
                raise self.fail_syntax(
                    self.size + i - start,
                    "Expected a delimiter or line break after a closing quote",
                )
        self.state = state
        self.field = field
        self.size += length - start
        self.check_size(self.size)

    def end(self, out: list[Parsed]) -> None:
        if self.state == _QUOTED:
            raise self.fail("Syntax", "Unterminated quoted field")
        if self.size > 0 or self.cells:
            self.push_cell("".join(self.field))
            self.field = []
            self.state = _FIELD_START
            self.end_record(self.size, out)
