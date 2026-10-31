"""JSON text as Effect reads and writes it: ``JSON.parse`` and
``JSON.stringify``.

Every JSON text pyfect reads or writes goes through this module (a guard
test bans ``json.dumps`` / ``json.loads`` elsewhere): Python's ``json``
writes ``1.0``, ``1e-07``, ``1e+16`` and ``-0.0`` where JavaScript writes
``1``, ``1e-7``, ``10000000000000000`` and ``0``, raises past 4300 digits,
escapes non-ASCII by default and reads ``NaN`` / ``Infinity``. Numbers here
are JavaScript's (``pyfect._js.js_number``), so the bytes, hashes and
signatures of a value match Effect's.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Mapping
from json.encoder import encode_basestring as _encode_string
from typing import Never, cast

from pyfect._js import int_text, js_number
from pyfect._stack import with_fresh_stack

type Json = bool | int | float | str | list[Json] | dict[str, Json] | None
"""A parsed JSON value."""

PARSE_ERRORS = (ValueError, RecursionError)
"""What ``parse`` raises for text that is not JSON (``JSONDecodeError`` is a
``ValueError``)."""

STRINGIFY_ERRORS = (TypeError, ValueError, RecursionError)
"""What ``stringify`` raises for a value with no JSON form."""


def _reject_constant(name: str) -> Never:
    raise ValueError(f"{name} is not valid JSON")


def parse(text: str | bytes | bytearray) -> Json:
    """``JSON.parse``: ``json.loads`` without the ``NaN`` / ``Infinity``
    extensions (bytes are read as ``json.loads`` reads them). Text that is
    not JSON raises ``ValueError``, also when it nests too deeply to decode
    (where ``json.loads`` raises ``RecursionError``)."""
    try:
        value: Json = json.loads(text, parse_constant=_reject_constant)
    except RecursionError as cause:
        raise ValueError("JSON is nested too deeply") from cause
    return value


_SAFE_INTEGER = 2**53 - 1


def whole_numbers_as_ints(value: Json) -> Json:
    """``value`` with each whole float within the safe integers as an
    ``int`` (``1.0`` as ``1``, ``-0.0`` as ``0``): JavaScript has one number,
    so ``1.0`` from the wire is an integer to Effect's ``Schema.Int``."""
    if type(value) is float:
        return int(value) if value.is_integer() and abs(value) <= _SAFE_INTEGER else value
    if type(value) is list:
        return [whole_numbers_as_ints(item) for item in cast("list[Json]", value)]
    if type(value) is dict:
        pairs = cast("dict[str, Json]", value).items()
        return {key: whole_numbers_as_ints(item) for key, item in pairs}
    return value


_LONE_SURROGATE = re.compile("[\ud800-\udfff]")
_FLOAT_TOKEN = re.compile("[0-9][.eE]")


def _escape_surrogate(match: re.Match[str]) -> str:
    return f"\\u{ord(match.group()):04x}"


def quote(text: str) -> str:
    """``JSON.stringify(text)``: the string in double quotes, non-ASCII kept
    as is, lone surrogates escaped (``"\\ud83d"``) so the text encodes to
    UTF-8."""
    encoded = _encode_string(text)
    return encoded if text.isascii() else _LONE_SURROGATE.sub(_escape_surrogate, encoded)


def _number(value: int | float, null_non_finite: bool = False) -> str:
    if isinstance(value, int):
        return int_text(value)
    if not math.isfinite(value):
        if null_non_finite:
            return "null"
        raise ValueError(f"{js_number(value)} is not JSON")
    return js_number(value)


def _key(key: object) -> str:
    match key:
        case str():
            return key
        case bool():
            return "true" if key else "false"
        case int() | float():
            return js_number(key)
        case None:
            return "null"
        case _:
            raise TypeError(f"keys must be str, int, float, bool or None, not {type(key).__name__}")


_STACK_CHECK = 64
"""Containers nested between two checks of the stack (``with_fresh_stack``)."""


class _Writer:
    __slots__ = ("ancestors", "default", "indent", "null_non_finite", "out", "sort_keys")

    def __init__(
        self,
        indent: str | None,
        sort_keys: bool,
        default: Callable[[object], object] | None,
        null_non_finite: bool = False,
    ) -> None:
        self.out: list[str] = []
        self.indent = indent
        self.sort_keys = sort_keys
        self.default = default
        self.null_non_finite = null_non_finite
        self.ancestors: set[int] = set()

    def write(self, value: object, depth: int) -> None:
        kind = type(value)
        if kind is str:
            self.out.append(quote(cast("str", value)))
        elif kind is dict or kind is list or kind is tuple:
            self._container(value, depth)
        elif value is None:
            self.out.append("null")
        elif kind is bool:
            self.out.append("true" if value else "false")
        elif kind is int or kind is float:
            self.out.append(_number(cast("float", value), self.null_non_finite))
        else:
            self._other(value, depth)

    def _other(self, value: object, depth: int) -> None:
        match value:
            case str():
                self.out.append(quote(value))
            case bool():
                self.out.append("true" if value else "false")
            case int() | float():
                self.out.append(_number(value, self.null_non_finite))
            case list() | tuple() | Mapping():
                self._container(cast("object", value), depth)
            case _ if self.default is not None:
                self.write(self.default(value), depth)
            case _:
                raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

    def _container(self, value: object, depth: int) -> None:
        if id(value) in self.ancestors:
            raise ValueError("Circular reference detected")
        self.ancestors.add(id(value))
        if depth % _STACK_CHECK == _STACK_CHECK - 1:
            with_fresh_stack(lambda: self._items(value, depth))
        else:
            self._items(value, depth)
        self.ancestors.discard(id(value))

    def _items(self, value: object, depth: int) -> None:
        out = self.out
        indent = self.indent
        inner = "" if indent is None else "\n" + indent * (depth + 1)
        separator = "," + inner
        if isinstance(value, Mapping):
            pairs = [(_key(k), v) for k, v in cast("Mapping[object, object]", value).items()]
            if not pairs:
                out.append("{}")
                return
            if self.sort_keys:
                pairs.sort(key=lambda pair: pair[0])
            colon = ":" if indent is None else ": "
            out.append("{" + inner)
            for i, (key, item) in enumerate(pairs):
                if i:
                    out.append(separator)
                out.append(quote(key) + colon)
                self.write(item, depth + 1)
            close = "}"
        else:
            items = cast("list[object] | tuple[object, ...]", value)
            if not items:
                out.append("[]")
                return
            out.append("[" + inner)
            for i, item in enumerate(items):
                if i:
                    out.append(separator)
                self.write(item, depth + 1)
            close = "]"
        out.append(close if indent is None else "\n" + indent * depth + close)


def stringify(
    value: object,
    *,
    indent: int | str | None = None,
    sort_keys: bool = False,
    default: Callable[[object], object] | None = None,
    null_non_finite: bool = False,
) -> str:
    """``JSON.stringify(value, null, indent)``: compact unless ``indent`` (a
    number of spaces, at most 10, or the text itself, as JavaScript's
    ``space``), numbers as JavaScript writes them, ints in full, non-ASCII
    kept and lone surrogates escaped; keys sorted when ``sort_keys``; any
    other object written as ``default`` of it (when given).
    ``NaN`` and infinities raise ``ValueError``, or are written ``null`` as
    JavaScript writes them when ``null_non_finite``; a value with no JSON
    form raises ``TypeError``, a cycle ``ValueError``."""
    space = (" " * min(indent, 10) if isinstance(indent, int) else (indent or "")[:10]) or None

    # Python's own encoder writes what JavaScript writes, but for floats
    # (every float it writes has a digit before ``.`` or ``e``), ints past
    # 4300 digits and mappings that are not dicts: those take a second try
    # with floats it writes as JavaScript does, then the writer.
    def dumps(value: object) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=space,
            separators=(",", ":" if space is None else ": "),
            sort_keys=sort_keys,
            default=default,
        )

    try:
        text = dumps(value)
        if _FLOAT_TOKEN.search(text) is not None:
            text = dumps(_plain(value))
    except (*STRINGIFY_ERRORS, _NeedsWriter):
        writer = _Writer(space, sort_keys, default, null_non_finite)
        writer.write(value, 0)
        return "".join(writer.out)
    return text if text.isascii() else _LONE_SURROGATE.sub(_escape_surrogate, text)


def js_stringify(value: object) -> str:
    """Exactly ``JSON.stringify(value)``: ``stringify`` with ``NaN`` and the
    infinities written ``null``. For JSON sent where Effect sends
    ``JSON.stringify``'s text (request bodies, protocol frames)."""
    return stringify(value, null_non_finite=True)


class _NeedsWriter(Exception):
    """A value ``json.dumps`` would not write as JavaScript does."""


def _plain(value: object) -> object:
    """``value`` with each float ``json.dumps`` writes as JavaScript does:
    whole ones below ``1e16`` as ints (``2``, ``0`` for ``-0.0``), others
    from ``1e-4`` to ``1e16`` as they are (``repr`` matches JavaScript there);
    anything else raises ``_NeedsWriter``."""
    kind = type(value)
    if kind is float:
        number = cast("float", value)
        if number.is_integer():
            if -1e16 < number < 1e16:
                return int(number)
        elif 1e-4 <= abs(number) < 1e16:
            return number
        raise _NeedsWriter
    if kind is dict:
        pairs = cast("dict[object, object]", value).items()
        return {k if type(k) is str else _plain_key(k): _plain(x) for k, x in pairs}
    if kind is list or kind is tuple:
        return [_plain(x) for x in cast("list[object]", value)]
    if kind is str or kind is int or kind is bool or value is None:
        return value
    raise _NeedsWriter


def _plain_key(key: object) -> str:
    if type(key) is float:
        raise _NeedsWriter
    return _key(key)
