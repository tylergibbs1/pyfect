"""The decoder's parser: text in unit form (``_chars``) to events."""

from __future__ import annotations

import re

from pyfect._digits import is_digits
from pyfect.encoding.xml._chars import (
    PUBID,
    SPACE,
    code_point_at,
    from_units,
    is_char,
    is_name,
    is_reserved_target,
    scan_name,
    search_invalid,
    search_invalid_decoded,
    skip_space,
    to_units,
)
from pyfect.encoding.xml._model import Comment as CommentEvent
from pyfect.encoding.xml._model import (
    Declaration,
    Doctype,
    EndElement,
    Event,
    ProcessingInstruction,
    StartElement,
    Text,
    XmlError,
    XmlErrorKind,
)
from pyfect.encoding.xml._scanner import (
    S_AFTER_SUBSET,
    S_DOCTYPE,
    S_START,
    S_TEXT,
    Scanner,
)

_PROLOG = 0
CONTENT = 1
EPILOG = 2

_PENDING_RUN = 256

_LINE_ENDINGS = re.compile(r"\r\n?")
_ATTRIBUTE_WHITESPACE = re.compile(r"\r\n|[\t\n\r]")
_ATTRIBUTE_SPECIAL = re.compile(r"[&<\t\n\r]")
_ATTRIBUTE_WHITESPACE_CHAR = re.compile(r"[\t\n\r]")
_PUBLIC_ID_WHITESPACE = re.compile(r"[ \r\n]+")
_HEX_DIGITS = re.compile(r"[0-9a-fA-F]+")
_NON_ASCII = re.compile(r"[\u0080-￿]")
_DECLARATION = re.compile(
    r"""[ \t\r\n]+version[ \t\r\n]*=[ \t\r\n]*(?:"(1\.[0-9]+)"|'(1\.[0-9]+)')"""
    r"""(?:[ \t\r\n]+encoding[ \t\r\n]*=[ \t\r\n]*"""
    r"""(?:"([A-Za-z][A-Za-z0-9._-]*)"|'([A-Za-z][A-Za-z0-9._-]*)'))?"""
    r"""(?:[ \t\r\n]+standalone[ \t\r\n]*=[ \t\r\n]*(?:"(yes|no)"|'(yes|no)'))?[ \t\r\n]*"""
)
_MAX_CHAR_DIGITS = 8
"""More significant digits than any character reference needs: ``int`` raises
past 4300 decimal digits, where JavaScript's ``parseInt`` gives a number no
character has."""


def _normalize_lines(s: str) -> str:
    return s if "\r" not in s else _LINE_ENDINGS.sub("\n", s)


def _normalize_attribute(s: str) -> str:
    return _ATTRIBUTE_WHITESPACE.sub(" ", s)


def _is_utf8(encoding: str) -> bool:
    return encoding.lower() in ("utf-8", "us-ascii")


def _index_or_end(s: str, search: str, start: int) -> int:
    i = s.find(search, start)
    return len(s) if i == -1 else i


def _describe_token(s: str, i: int) -> str:
    if s.startswith("<!--", i):
        return "comment"
    if s.startswith("<![CDATA[", i):
        return "CDATA section"
    if s.startswith("<!DOCTYPE", i):
        return "DOCTYPE"
    if s.startswith("<?", i):
        return "processing instruction"
    return "end tag" if s.startswith("</", i) else "start tag"


class Parser:
    def __init__(self, max_token_size: float, max_depth: float, is_bytes: bool) -> None:
        self.out: list[Event] = []
        # The text being parsed, which starts at document offset ``_base``
        self._buf = ""
        self._base = 0
        # Number of characters received, excluding a byte order mark
        self.received = 0
        self._started = False
        # A token that continues in the next chunk
        self._pending: list[str] | None = None
        self._pending_start = 0
        self._pending_length = 0
        # Number of chunks added to ``_pending`` since its last chunks were joined
        self._pending_added = 0
        self._scanner = Scanner()
        # Line and column of document offset ``_counted``
        self._line = 1
        self._line_start = 0
        self._counted = 0
        self._state = _PROLOG
        self._stack: list[str] = []
        self._open_name_size = 0
        self._doctype = False
        self._literal_end = 0
        # Character data that has not been emitted yet, and its size in the input
        self._text = ""
        self._text_size = 0
        self._max_token_size = max_token_size
        self._max_depth = max_depth
        self._is_bytes = is_bytes
        self._ascii = False

    def feed(self, chunk: str, force: bool = False) -> None:
        """``force`` parses a pending token without waiting for its end, so that
        an error found before invalid input is reported however the input is
        chunked."""
        if not chunk and not force:
            return
        if not self._started:
            self._started = True
            if chunk[:1] == "﻿":
                chunk = chunk[1:]
        if self._is_bytes:
            non_ascii = _NON_ASCII.search(chunk)
            if non_ascii is not None:
                # The prefix may contain the declaration that selects US-ASCII.
                self.feed(chunk[: non_ascii.start()], True)
                if self._ascii:
                    raise self.error("Syntax", "invalid US-ASCII byte", self.received)
                chunk = chunk[non_ascii.start() :]
        invalid = search_invalid_decoded(chunk) if self._is_bytes else search_invalid(chunk)
        if invalid != -1:
            # Parse up to the invalid character first, so that earlier errors are
            # reported first however the input is chunked
            self._consume(chunk[:invalid], True)
            raise self.error(
                "Syntax",
                f"invalid character U+{code_point_at(chunk, invalid)}",
                self.received,
            )
        self._consume(chunk, force)

    def end(self) -> None:
        if self._pending is not None:
            self._load("".join(self._pending), self._pending_start)
            self._pending = None
        self._parse(True)
        if self._state == _PROLOG:
            raise self.error("Syntax", "no root element", self.received)
        if self._state == CONTENT:
            raise self.error("Syntax", f"unclosed element <{self._stack[-1]}>", self.received)

    def error(self, kind: XmlErrorKind, message: str, at: int) -> XmlError:
        if at > self._counted:
            if self._pending is not None:
                self._count("".join(self._pending), self._pending_start, at - self._pending_start)
            else:
                self._count(self._buf, self._base, at - self._base)
        column = at - self._line_start + 1
        return XmlError(
            kind,
            f"{from_units(message)} at line {self._line}, column {column}",
            self._line,
            column,
        )

    def _count(self, s: str, base: int, to: int) -> None:
        """Advances the line count from ``_counted`` to ``to``, an index of ``s``,
        which starts at document offset ``base``. Counting resumes only where
        parsing stopped, which is never between a CR and an LF."""
        i = max(self._counted - base, 0)
        if i >= to:
            return
        cr = s.find("\r", i)
        lf = s.find("\n", i)
        while True:
            if cr != -1 and cr < to and (lf == -1 or cr < lf):
                self._line += 1
                self._line_start = base + cr + 1
                cr = s.find("\r", cr + 1)
            elif lf != -1 and lf < to:
                # The LF of a CRLF does not start a new line
                if not (lf > 0 and s[lf - 1] == "\r"):
                    self._line += 1
                self._line_start = base + lf + 1
                lf = s.find("\n", lf + 1)
            else:
                break
        self._counted = base + to

    def _syntax(self, message: str, i: int) -> XmlError:
        return self.error("Syntax", message, self._base + i)

    def _token_limit(self, at: int) -> XmlError:
        return self.error(
            "Limit", f"token exceeds maxTokenSize of {_limit(self._max_token_size)}", at
        )

    def _consume(self, chunk: str, force: bool = False) -> None:
        self.received += len(chunk)
        if self._pending is not None:
            if not force and self._scanner.scan(chunk, 0) == -1:
                self._pending.append(chunk)
                self._pending_length += len(chunk)
                # Joins runs of chunks, so that a token split into many tiny
                # chunks does not take a list slot for each
                self._pending_added += 1
                if self._pending_added == _PENDING_RUN:
                    run = "".join(self._pending[-_PENDING_RUN:])
                    del self._pending[-_PENDING_RUN:]
                    self._pending.append(run)
                    self._pending_added = 0
                self._check_pending()
                return
            self._pending.append(chunk)
            self._load("".join(self._pending), self._pending_start)
            self._pending = None
        else:
            self._load(chunk, self.received - len(chunk))
        self._parse(False)

    def _load(self, buf: str, base: int) -> None:
        self._buf = buf
        self._base = base

    def _check_pending(self) -> None:
        """Fails an incomplete token over max_token_size, preferring an error in
        the first max_token_size + 1 characters of markup, as ``_parse`` does."""
        assert self._pending is not None
        is_text = self._scanner.state == S_TEXT
        if self._pending_length + (self._text_size if is_text else 0) <= self._max_token_size:
            return
        if not is_text:
            self._load("".join(self._pending)[: int(self._max_token_size + 1)], self._pending_start)
            self._markup(self._buf, 0)
        raise self._token_limit(self._pending_start)

    def _parse(self, final: bool) -> None:  # noqa: PLR0912, PLR0915
        s = self._buf
        n = len(s)
        # Positions of the next "&", CR and "]]>", so that text runs are checked
        # without searching past them repeatedly
        next_amp = -1
        next_cr = -1
        next_cdata_end = -1
        i = 0
        while i < n:
            if s[i] != "<":
                j = s.find("<", i)
                if j == -1:
                    if not final:
                        break
                    j = n
                if self._state != CONTENT:
                    self._check_size(i, j)
                    self._whitespace(s, i, j)
                else:
                    self._add_text(i, j - i)
                    if next_cdata_end < i:
                        next_cdata_end = _index_or_end(s, "]]>", i)
                    if next_cdata_end < j:
                        raise self._syntax('"]]>" is not allowed in text', next_cdata_end)
                    if next_amp < i:
                        next_amp = _index_or_end(s, "&", i)
                    if next_cr < i:
                        next_cr = _index_or_end(s, "\r", i)
                    raw = s[i:j]
                    if next_amp >= j:
                        self._text += raw if next_cr >= j else _normalize_lines(raw)
                    else:
                        self._text += self._decode_text(raw, i, False, next_cr < j)
                i = j
                continue
            # Markup is parsed from at most max_token_size + 1 characters, so that
            # its errors do not depend on how the input is chunked
            long = n - i > self._max_token_size
            end = self._markup(s[: int(i + self._max_token_size + 1)] if long else s, i)
            if end == -1:
                if long:
                    raise self._token_limit(self._base + i)
                if final:
                    raise self._syntax(f"unterminated {_describe_token(s, i)}", i)
                break
            i = end
        self._count(s, self._base, i)
        self._buf = ""
        if i < n:
            rest = s if i == 0 else s[i:]
            self._pending = [rest]
            self._pending_start = self._base + i
            self._pending_length = len(rest)
            self._pending_added = 0
            # Brings the scanner to the end of the incomplete token
            self._scanner.reset(S_START)
            self._scanner.scan(rest, 0)
            self._check_pending()

    def _flush_text(self) -> None:
        if self._text:
            self.out.append(Text(from_units(self._text)))
            self._text = ""
        self._text_size = 0

    def _add_text(self, i: int, size: int) -> None:
        """Adds the size of the text run or CDATA section at ``i``. Exceeding the
        limit is reported there, rather than at the start of the text."""
        self._text_size += size
        if self._text_size > self._max_token_size:
            raise self._token_limit(self._base + i)

    def _whitespace(self, s: str, i: int, j: int) -> None:
        """Checks that the text run ``s[i:j]`` outside the root element is whitespace."""
        for k in range(i, j):
            if s[k] not in SPACE:
                raise self._syntax(
                    "text before the root element"
                    if self._state == _PROLOG
                    else "text after the root element",
                    k,
                )

    def _decode_text(self, raw: str, offset: int, attribute: bool, whitespace: bool) -> str:
        """Replaces references and normalizes line endings, or attribute
        whitespace. ``whitespace`` is false when ``raw`` has nothing to normalize."""
        parts: list[str] = []
        k = 0
        while True:
            amp = raw.find("&", k)
            literal = raw[k:] if amp == -1 else raw[k:amp]
            if not whitespace:
                parts.append(literal)
            elif attribute:
                parts.append(_normalize_attribute(literal))
            else:
                parts.append(_normalize_lines(literal))
            if amp == -1:
                return "".join(parts)
            semicolon = raw.find(";", amp + 1)
            if semicolon == -1:
                raise self._syntax("unterminated reference", offset + amp)
            parts.append(self._reference(raw, amp, semicolon, offset))
            k = semicolon + 1

    def _reference(self, raw: str, amp: int, semicolon: int, offset: int) -> str:
        """Decodes the reference ``raw[amp : semicolon + 1]``."""
        name = raw[amp + 1 : semicolon]
        predefined = {"amp": "&", "apos": "'", "lt": "<", "gt": ">", "quot": '"'}.get(name)
        if predefined is not None:
            return predefined
        if name[:1] == "#":
            is_hex = name[1:2] == "x"
            digits = name[2:] if is_hex else name[1:]
            code = -1
            if _HEX_DIGITS.fullmatch(digits) if is_hex else is_digits(digits):
                significant = digits.lstrip("0")
                if len(significant) <= _MAX_CHAR_DIGITS:
                    code = int(significant or "0", 16 if is_hex else 10)
            if not is_char(code):
                raise self._syntax("invalid character reference", offset + amp)
            return to_units(chr(code))
        if not is_name(name):
            raise self._syntax("invalid reference", offset + amp)
        if self._doctype:
            raise self.error(
                "Unsupported",
                f"entity references other than the predefined entities are not supported: &{name};",
                self._base + offset + amp,
            )
        raise self._syntax(f"undefined entity &{name};", offset + amp)

    def _markup(self, s: str, i: int) -> int:  # noqa: PLR0911
        """Parses the markup at ``i``, and returns its end or -1 when it is incomplete."""
        n = len(s)
        if i + 1 >= n:
            return -1
        c = s[i + 1]
        if c == "/":
            return self._end_tag(s, i)
        if c == "?":
            return self._processing_instruction(s, i)
        if c != "!":
            return self._start_tag(s, i)
        if i + 2 >= n:
            return -1
        third = s[i + 2]
        keyword = "<!--" if third == "-" else "<![CDATA[" if third == "[" else "<!DOCTYPE"
        if not s.startswith(keyword, i):
            if n - i < len(keyword) and keyword.startswith(s[i:]):
                return -1
            raise self._syntax("invalid markup", i)
        if keyword == "<!--":
            return self._comment(s, i)
        return self._doctype_declaration(s, i) if keyword == "<!DOCTYPE" else self._cdata(s, i)

    def _check_size(self, i: int, end: int) -> None:
        if end - i > self._max_token_size:
            raise self._token_limit(self._base + i)

    def _start_tag(self, s: str, i: int) -> int:  # noqa: PLR0911, PLR0912, PLR0915
        n = len(s)
        if self._state == EPILOG:
            raise self._syntax("content after the root element", i)
        j = scan_name(s, i + 1, n)
        if j == i + 1:
            raise self._syntax("invalid element name", i + 1)
        if j >= n:
            return -1
        name = s[i + 1 : j]
        attributes: dict[str, str] = {}
        self_closing = False
        while True:
            c = s[j]
            space = c in SPACE
            if space:
                j = skip_space(s, j, n)
                if j >= n:
                    return -1
                c = s[j]
            if c == ">":
                j += 1
                break
            if c == "/":
                if j + 1 >= n:
                    return -1
                if s[j + 1] != ">":
                    raise self._syntax('expected ">"', j + 1)
                j += 2
                self_closing = True
                break
            if not space:
                raise self._syntax('expected whitespace, ">" or "/>"', j)
            name_start = j
            j = scan_name(s, j, n)
            if j == name_start:
                raise self._syntax("invalid attribute name", j)
            if j >= n:
                return -1
            attribute = s[name_start:j]
            j = skip_space(s, j, n)
            if j >= n:
                return -1
            if s[j] != "=":
                raise self._syntax('expected "="', j)
            j = skip_space(s, j + 1, n)
            if j >= n:
                return -1
            quote = s[j]
            if quote not in "\"'":
                raise self._syntax("expected a quoted attribute value", j)
            close = s.find(quote, j + 1)
            if close == -1:
                lt = s.find("<", j + 1)
                if lt != -1:
                    raise self._syntax('"<" is not allowed in attribute values', lt)
                return -1
            value = self._attribute_value(s, j + 1, close)
            key = from_units(attribute)
            if key in attributes:
                raise self._syntax(f"duplicate attribute {attribute}", name_start)
            attributes[key] = from_units(value)
            j = close + 1
            if j >= n:
                return -1
        self._check_size(i, j)
        if len(self._stack) >= self._max_depth:
            raise self.error(
                "Limit",
                f"element nesting exceeds maxDepth of {_limit(self._max_depth)}",
                self._base + i,
            )
        if not self_closing and self._open_name_size + len(name) > self._max_token_size:
            raise self.error(
                "Limit",
                f"open element names exceed maxTokenSize of {_limit(self._max_token_size)}",
                self._base + i,
            )
        self._flush_text()
        event_name = from_units(name)
        self.out.append(StartElement(event_name, attributes))
        if self_closing:
            self.out.append(EndElement(event_name))
            if not self._stack:
                self._state = EPILOG
        else:
            self._stack.append(name)
            self._open_name_size += len(name)
            self._state = CONTENT
        return j

    def _attribute_value(self, s: str, i: int, j: int) -> str:
        raw = s[i:j]
        if _ATTRIBUTE_SPECIAL.search(raw) is None:
            return raw
        lt = raw.find("<")
        if lt != -1:
            raise self._syntax('"<" is not allowed in attribute values', i + lt)
        if "&" not in raw:
            return _normalize_attribute(raw)
        return self._decode_text(raw, i, True, _ATTRIBUTE_WHITESPACE_CHAR.search(raw) is not None)

    def _end_tag(self, s: str, i: int) -> int:
        n = len(s)
        j = scan_name(s, i + 2, n)
        if j == i + 2:
            if j >= n:
                return -1
            raise self._syntax("invalid element name", j)
        k = skip_space(s, j, n)
        if k >= n:
            return -1
        if s[k] != ">":
            raise self._syntax('expected ">"', k)
        if not self._stack:
            raise self._syntax("end tag without a start tag", i)
        open_name = self._stack[-1]
        if j - i - 2 != len(open_name) or not s.startswith(open_name, i + 2):
            raise self._syntax(f"end tag </{s[i + 2 : j]}> does not match <{open_name}>", i)
        self._check_size(i, k + 1)
        self._flush_text()
        self._stack.pop()
        self._open_name_size -= len(open_name)
        self.out.append(EndElement(from_units(open_name)))
        if not self._stack:
            self._state = EPILOG
        return k + 1

    def _comment(self, s: str, i: int) -> int:
        end = s.find("-->", i + 4)
        if end == -1:
            return -1
        dashes = s.find("--", i + 4)
        if dashes < end:
            raise self._syntax('"--" is not allowed in comments', dashes)
        self._check_size(i, end + 3)
        self._flush_text()
        self.out.append(CommentEvent(from_units(_normalize_lines(s[i + 4 : end]))))
        return end + 3

    def _processing_instruction(self, s: str, i: int) -> int:
        end = s.find("?>", i + 2)
        if end == -1:
            return -1
        t = scan_name(s, i + 2, end)
        if t == i + 2:
            raise self._syntax("invalid processing instruction target", i + 2)
        target = s[i + 2 : t]
        if is_reserved_target(target):
            if target == "xml" and self._base + i == 0:
                return self._declaration(s, i, t, end)
            raise self._syntax(
                "the XML declaration is only allowed at the start of the document"
                if target == "xml"
                else f"processing instruction target {target} is reserved",
                i,
            )
        data = ""
        if t < end:
            if s[t] not in SPACE:
                raise self._syntax("expected whitespace after the target", t)
            data = _normalize_lines(s[skip_space(s, t, end) : end])
        self._check_size(i, end + 2)
        self._flush_text()
        self.out.append(ProcessingInstruction(from_units(target), from_units(data)))
        return end + 2

    def _declaration(self, s: str, i: int, t: int, end: int) -> int:
        self._check_size(i, end + 2)
        match = _DECLARATION.fullmatch(s, t, end)
        if match is None:
            raise self._syntax("invalid XML declaration", i)
        version = match[1] or match[2]
        encoding: str | None = match[3] or match[4]
        standalone: str | None = match[5] or match[6]
        if self._is_bytes and encoding is not None and not _is_utf8(encoding):
            raise self.error(
                "Unsupported",
                f"encoding {encoding} is not supported for byte input, "
                "decode the bytes to text first",
                self._base + i,
            )
        self._ascii = self._is_bytes and encoding is not None and encoding.lower() == "us-ascii"
        self.out.append(
            Declaration(version, encoding, None if standalone is None else standalone == "yes")
        )
        return end + 2

    def _cdata(self, s: str, i: int) -> int:
        end = s.find("]]>", i + 9)
        if end == -1:
            return -1
        if self._state != CONTENT:
            raise self._syntax("CDATA sections are only allowed inside the root element", i)
        self._add_text(i, end + 3 - i)
        self._text += _normalize_lines(s[i + 9 : end])
        return end + 3

    def _doctype_declaration(self, s: str, i: int) -> int:
        if self._state != _PROLOG or self._doctype:
            raise self._syntax("a DOCTYPE is only allowed once, before the root element", i)
        scanner = Scanner()
        scanner.reset(S_DOCTYPE)
        end = scanner.scan(s, i + 9)
        if end == -1:
            return -1
        self._check_size(i, end)
        self._doctype = True
        j = self._space(s, i + 9, end)
        name_end = self._name(s, j, end)
        name = s[j:name_end]
        public_id: str | None = None
        system_id: str | None = None
        j = skip_space(s, name_end, end)
        if j > name_end and (s.startswith("PUBLIC", j) or s.startswith("SYSTEM", j)):
            if s[j] == "P":
                # Whitespace in public identifiers is normalized for matching
                literal = self._public_literal(s, self._space(s, j + 6, end), end)
                public_id = _PUBLIC_ID_WHITESPACE.sub(" ", literal).strip(_JS_TRIM)
                j = self._literal_end
            system_id = _normalize_lines(
                self._literal(s, self._space(s, j + (6 if public_id is None else 0), end), end)
            )
            j = skip_space(s, self._literal_end, end)
        if s[j : j + 1] == "[":
            # The scanner skips the internal subset, whose declarations are not
            # checked, and ends the token early only at malformed markup
            if scanner.state != S_AFTER_SUBSET:
                raise self._syntax("invalid markup in the internal subset", end)
            j = skip_space(s, s.rfind("]", 0, end) + 1, end)
        if j != end - 1 or s[j : j + 1] != ">":
            raise self._syntax("invalid DOCTYPE", j)
        self.out.append(
            Doctype(
                from_units(name),
                public_id,
                None if system_id is None else from_units(system_id),
            )
        )
        return end

    def _space(self, s: str, i: int, end: int) -> int:
        """Skips the whitespace that is required at ``i``."""
        if i >= end or s[i] not in SPACE:
            raise self._syntax("expected whitespace", i)
        return skip_space(s, i, end)

    def _name(self, s: str, i: int, end: int) -> int:
        """The end of the name that is required at ``i``."""
        name_end = scan_name(s, i, end)
        if name_end == i:
            raise self._syntax("expected a name", i)
        return name_end

    def _literal(self, s: str, i: int, end: int) -> str:
        """Reads the quoted literal at ``i``, and sets ``_literal_end`` after it."""
        quote = s[i : i + 1]
        if quote not in ('"', "'"):
            raise self._syntax("expected a quoted literal", i)
        close = s.find(quote, i + 1)
        if close == -1 or close >= end:
            raise self._syntax("unterminated literal", i)
        self._literal_end = close + 1
        return s[i + 1 : close]

    def _public_literal(self, s: str, i: int, end: int) -> str:
        literal = self._literal(s, i, end)
        if PUBID.fullmatch(literal) is None:
            raise self._syntax("invalid public identifier", i)
        return literal


_JS_TRIM = " \r\n"
"""What ``trim`` can find in a public identifier, whose characters are ``PUBID``'s."""


def _limit(value: float) -> str:
    """``String(limit)``: ``10`` for an integral limit, ``Infinity`` never reaches
    a message."""
    return str(int(value)) if float(value).is_integer() else str(value)
