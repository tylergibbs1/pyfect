"""Rendering logged values as text: the parts of Effect's ``Formatter``
the loggers use, read for Python values.

``format_unknown`` writes one line of JSON-like text (strings quoted,
``None`` as ``null``) and names the type of anything that is not a plain
``dict`` or ``list``. ``to_json`` turns a value into what
``pyfect._json_text.stringify`` accepts: exceptions become ``{"name", "message"}`` (plus their
attributes), and circular references are dropped.
"""

from __future__ import annotations

import dataclasses
import inspect
import math
import re
from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime
from typing import Any, cast

from pyfect import _json_text as _json
from pyfect._js import js_number, js_string, to_iso_string
from pyfect._stack import with_fresh_stack
from pyfect.logger._model import LogSpan

_LABEL_UNSAFE = re.compile(r'[\s="]')
_TEXT_ONLY = re.compile(r'^[^\s"=]*$')
# Every character ``str.splitlines`` breaks a line at.
_LINE_BREAK = "\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029"
_UNESCAPED_QUOTE = re.compile(r'\\([\s\S])|(["' + _LINE_BREAK + "])")
_RAW_LINE_BREAK = re.compile("[\x85\u2028\u2029]")


def format_label(key: str) -> str:
    """``key`` with spaces, ``=`` and ``"`` replaced by ``_``."""
    return _LABEL_UNSAFE.sub("_", key)


def format_log_span(span: LogSpan, now: int) -> str:
    return f"{format_label(span.label)}={now - span.start}ms"


def is_text_only(value: str) -> bool:
    return _TEXT_ONLY.match(value) is not None


_ESCAPED = {"\r": "r", "\n": "n"}


def _escaped(char: str) -> str:
    if char in _ESCAPED:
        return "\\" + _ESCAPED[char]
    return f"\\u{ord(char):04x}" if char in _LINE_BREAK else "\\" + char


def _escape(match: re.Match[str]) -> str:
    return _escaped(match[1] or match[2])


def escape_double_quotes(value: str) -> str:
    """``value`` in double quotes, its unescaped quotes escaped and its line
    breaks written ``\\r`` / ``\\n`` (``\\uXXXX`` for the other line
    separators), so one entry stays one line (Effect leaves them raw)."""
    return '"' + _UNESCAPED_QUOTE.sub(_escape, value) + '"'


def json_quote(value: str) -> str:
    return _json.quote(value)


def json_quote_line(value: str) -> str:
    """``json_quote`` that also escapes U+0085, U+2028 and U+2029, which
    JSON leaves raw and line readers split at."""
    return _RAW_LINE_BREAK.sub(lambda m: f"\\u{ord(m[0]):04x}", json_quote(value))


iso_millis = to_iso_string


def _is_function(value: object) -> bool:
    return inspect.isroutine(value) or isinstance(value, type)


def _shown_as_str(value: object) -> bool:
    """Functions, classes and objects with their own ``__str__`` are
    written as ``str(value)``."""
    return _is_function(value) or type(value).__str__ is not object.__str__


def _fields(value: object) -> Mapping[str, object] | None:
    """The attributes an object is written with, or ``None`` for an object
    that has none to show."""
    if dataclasses.is_dataclass(value):
        return {f.name: getattr(value, f.name) for f in dataclasses.fields(value)}
    attributes: dict[str, object] | None = getattr(value, "__dict__", None)
    return attributes


def _exception_text(error: BaseException) -> str:
    message = str(error)
    return f"{type(error).__name__}: {message}" if message else type(error).__name__


def _scalar_text(value: object) -> str | None:
    match value:
        case str():
            return json_quote(value)
        case None:
            return "null"
        case bool():
            return "true" if value else "false"
        case int() | float():
            return js_number(value)
        case _:
            return None


def _key(k: object) -> str:
    return json_quote(k) if isinstance(k, str) else js_string(k)


def format_unknown(value: object) -> str:
    """``value`` as one line of JSON-like text. Never raises."""
    ancestors: set[int] = set()

    def entries(pairs: Iterable[tuple[object, object]]) -> str:
        return "{" + ",".join(f"{_key(k)}:{recur(v)}" for k, v in pairs) + "}"

    def items(values: Iterable[object]) -> str:
        return "[" + ",".join(recur(v) for v in values) + "]"

    def compound(v: object) -> str:
        kind = type(v)
        name = kind.__name__
        if isinstance(v, (list, tuple)):
            text = items(cast("Iterable[object]", v))
        elif isinstance(v, (datetime, date)):
            text = v.isoformat()
        elif isinstance(v, BaseException):
            text = _exception_text(v)
            if v.__cause__ is not None:
                text += f" (cause: {recur(v.__cause__)})"
        elif _shown_as_str(v):
            text = str(v)
        elif isinstance(v, Mapping):
            body = entries(cast("Mapping[object, object]", v).items())
            text = body if kind is dict else f"{name}({body})"
        elif isinstance(v, Iterable):
            text = f"{name}({items(cast('Iterable[object]', v))})"
        elif (fields := _fields(v)) is not None:
            text = f"{name}({entries(fields.items())})"
        else:
            text = f"{name}({{}})"
        return text

    def recur(v: object) -> str:
        scalar = _scalar_text(v)
        if scalar is not None:
            return scalar
        if id(v) in ancestors:
            return "[Circular]"
        ancestors.add(id(v))
        try:
            return compound(v)
        except Exception:
            return "[inspection threw]"
        finally:
            ancestors.discard(id(v))

    return recur(value)


def structured_message(value: object) -> object:
    """A logged item as structured loggers keep it: functions and classes
    by name, sequences item by item, anything else as it is."""
    if _is_function(value):
        return str(value)
    if isinstance(value, (list, tuple)):
        items = cast("Iterable[object]", value)
        return with_fresh_stack(lambda: [structured_message(v) for v in items])
    return value


_DROP = object()


def to_json(value: object) -> Any:
    """``value`` as plain JSON data: dicts with string keys, lists,
    strings, numbers, booleans and ``None``."""
    ancestors: set[int] = set()

    def mapping(pairs: Iterable[tuple[object, object]]) -> dict[str, object]:
        out: dict[str, object] = {}
        for k, x in pairs:
            converted = recur(x)
            if converted is not _DROP:
                out[js_string(k)] = converted
        return out

    def sequence(values: Iterable[object]) -> list[object]:
        return [None if (c := recur(x)) is _DROP else c for x in values]

    def container(identity: int, convert: Callable[[], object]) -> object:
        if identity in ancestors:
            return _DROP
        ancestors.add(identity)
        try:
            return with_fresh_stack(convert)  # as deep as the value
        finally:
            ancestors.discard(identity)

    def compound(v: object) -> object:  # noqa: PLR0911
        identity = id(v)
        if isinstance(v, BaseException):
            error = v
            pairs = [*vars(error).items(), ("name", type(error).__name__), ("message", str(error))]
            return container(identity, lambda: mapping(pairs))
        if isinstance(v, Mapping):
            pairs = list(cast("Mapping[object, object]", v).items())
            return container(identity, lambda: mapping(pairs))
        if isinstance(v, (list, tuple)):
            values = list(cast("Iterable[object]", v))
            return container(identity, lambda: sequence(values))
        if isinstance(v, (set, frozenset)):
            return {}  # a JavaScript ``Set`` has no enumerable keys
        if isinstance(v, (bytes, bytearray)):
            return {str(index): byte for index, byte in enumerate(v)}  # a ``Uint8Array``
        if _is_function(v):
            return _DROP  # ``JSON.stringify`` leaves a function out
        fields = None if _shown_as_str(v) else _fields(v)
        if fields is None:
            return str(v)
        return container(identity, lambda: mapping(fields.items()))

    def recur(v: object) -> object:
        if v is None or isinstance(v, (str, bool, int)):
            return v
        if isinstance(v, float):
            return v if math.isfinite(v) else None
        if isinstance(v, datetime):
            return iso_millis(v)
        if isinstance(v, date):
            return v.isoformat()
        return compound(v)

    converted = recur(value)
    return None if converted is _DROP else converted


def json_text(value: object) -> str:
    """``value`` as compact JSON (``to_json``)."""
    return _json.stringify(to_json(value))


def to_string_unknown(value: object) -> str:
    """Effect's ``toStringUnknown``: a string as it is, anything else as
    JSON indented by two spaces (``to_json``)."""
    if isinstance(value, str):
        return value
    return _json.stringify(to_json(value), indent=2)
