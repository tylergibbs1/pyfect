"""URL query parameters (Effect's ``UrlParams``): ordered ``(name, value)``
pairs, where a value may be ``Redacted`` to keep it out of logs while it is
still sent.

``from_input`` takes a mapping or pairs; values are coerced the way
JavaScript's ``String`` does (``True`` is ``"true"``, ``None`` is
``"null"``, ``1.0`` is ``"1"``), a sequence value adds one pair per item and
a nested mapping adds ``a[b]`` keys::

    params = from_input({"q": "effect", "page": 2}).append("tag", "a")
    to_string(params)   # "q=effect&page=2&tag=a"
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from typing import cast, final
from urllib.parse import unquote

from pyfect._js import js_number, to_well_formed
from pyfect._whatwg_url import form as _form
from pyfect.context import Reference
from pyfect.http.headers import Pattern, is_redacted_name
from pyfect.redacted import Redacted
from pyfect.redacted import value as redacted_value

type Value = str | Redacted[str]
type Param = tuple[str, Value]
type Coercible = str | int | float | bool | Redacted[str] | None

type CoercibleRecord = Mapping[str, Coercible | Sequence[Coercible] | CoercibleRecord]

type Input = UrlParams | CoercibleRecord | Iterable[tuple[str, Coercible]]


def unwrap(value: Value) -> str:
    """A value as sent: a ``Redacted`` one written out."""
    return value if isinstance(value, str) else redacted_value(value)


_unwrap = unwrap


@final
class UrlParams:
    """Ordered query parameters. Iterating gives the pairs; ``repr`` hides
    the values of ``CurrentRedactedNames`` and of ``Redacted`` values."""

    __slots__ = ("params",)

    def __init__(self, params: Iterable[Param] = ()) -> None:
        self.params: tuple[Param, ...] = tuple(params)

    def __iter__(self) -> Iterator[Param]:
        return iter(self.params)

    def __len__(self) -> int:
        return len(self.params)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, UrlParams):
            return NotImplemented
        return self.params == other.params

    def __hash__(self) -> int:
        return hash(self.params)

    def __repr__(self) -> str:
        return f"UrlParams({self.redact(current_redacted_names())!r})"

    def get_all(self, key: str) -> list[str]:
        return [_unwrap(v) for k, v in self.params if k == key]

    def get_first(self, key: str) -> str | None:
        return next((_unwrap(v) for k, v in self.params if k == key), None)

    def get_last(self, key: str) -> str | None:
        return next((_unwrap(v) for k, v in reversed(self.params) if k == key), None)

    def set(self, key: str, value: Coercible) -> UrlParams:
        """Replace every pair named ``key`` with one, at the end."""
        return UrlParams((*(p for p in self.params if p[0] != key), (key, _coerce(value))))

    def transform(self, f: Callable[[tuple[Param, ...]], Iterable[Param]]) -> UrlParams:
        return UrlParams(f(self.params))

    def set_all(self, input: Input) -> UrlParams:
        """The pairs of ``input``, then the pairs of ``self`` whose names
        ``input`` does not set."""
        params = from_input(input).params
        keys = {k for k, _ in params}
        return UrlParams((*params, *(p for p in self.params if p[0] not in keys)))

    def append(self, key: str, value: Coercible) -> UrlParams:
        return UrlParams((*self.params, (key, _coerce(value))))

    def append_all(self, input: Input) -> UrlParams:
        return UrlParams((*self.params, *from_input(input).params))

    def remove(self, key: str) -> UrlParams:
        return UrlParams(p for p in self.params if p[0] != key)

    def to_record(self) -> dict[str, str | list[str]]:
        """Each name to its value, or to its values when repeated."""
        out: dict[str, str | list[str]] = {}
        for key, raw in self.params:
            value = _unwrap(raw)
            current = out.get(key)
            if current is None:
                out[key] = value
            elif isinstance(current, str):
                out[key] = [current, value]
            else:
                current.append(value)
        return out

    def redact(self, key: Pattern | Sequence[Pattern]) -> list[tuple[str, Value]]:
        """The pairs, with plain values of the names matching ``key`` hidden
        in ``Redacted``."""
        patterns: Sequence[Pattern] = (key,) if isinstance(key, (str, re.Pattern)) else key
        return [
            (
                name,
                Redacted(value)
                if isinstance(value, str) and is_redacted_name(name, patterns)
                else value,
            )
            for name, value in self.params
        ]

    def to_json(self) -> dict[str, object]:
        return {
            "_id": "UrlParams",
            "params": {k: str(v) for k, v in self.redact(current_redacted_names())},
        }


EMPTY: UrlParams = UrlParams()


def make(params: Iterable[Param]) -> UrlParams:
    return UrlParams(params)


def _coerce(value: Coercible) -> Value:
    if isinstance(value, (Redacted, str)):
        return value
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return js_number(value)


def from_input(input: Input) -> UrlParams:
    if isinstance(input, UrlParams):
        return input
    return UrlParams(
        (key if isinstance(key, str) else f"{key[0]}[{']['.join(key[1:])}]", value)
        for key, value in _nested(input)
    )


def _nested(
    input: CoercibleRecord | Iterable[tuple[str, Coercible]],
) -> list[tuple[str | list[str], Value]]:
    entries: Iterable[tuple[str, object]] = (
        cast("Mapping[str, object]", input).items() if isinstance(input, Mapping) else input
    )
    out: list[tuple[str | list[str], Value]] = []
    for key, value in entries:
        if isinstance(value, (list, tuple)):
            out.extend((key, _coerce(item)) for item in cast("Sequence[Coercible]", value))
        elif isinstance(value, Mapping):
            for k, v in _nested(cast("CoercibleRecord", value)):
                out.append(([key, *([k] if isinstance(k, str) else k)], v))
        else:
            out.append((key, _coerce(cast("Coercible", value))))
    return out


def to_string(input: Input) -> str:
    """The parameters as a query string, without the ``?``, as
    ``URLSearchParams`` writes them (only ``*-._`` and alphanumerics stay,
    a space is ``+``); ``Redacted`` values are written out."""
    return _form.serialize((k, _unwrap(v)) for k, v in from_input(input))


def parse(query: str) -> UrlParams:
    """A query string (``?`` optional) as ``URLSearchParams`` reads it:
    ``+`` is a space and bad escapes stay as written."""
    return UrlParams(_form.parse(to_well_formed(query).removeprefix("?")))


class CurrentRedactedNames(Reference[tuple[Pattern, ...]]):
    """The parameter names whose values logs and spans hide; the default is OpenTelemetry's
    ``url.full`` list."""

    @classmethod
    def default(cls) -> tuple[Pattern, ...]:
        return (
            "X-Amz-Signature",
            "X-Amz-Credential",
            "X-Amz-Security-Token",
            "AWSAccessKeyId",
            "Signature",
            "sig",
            "X-Goog-Signature",
        )


def current_redacted_names() -> tuple[Pattern, ...]:
    """``CurrentRedactedNames`` of the running fiber, or the default."""
    from pyfect._fiber import current_fiber

    fiber = current_fiber()
    return CurrentRedactedNames.default() if fiber is None else fiber.get_ref(CurrentRedactedNames)


_BAD_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_AUTHORITY_START = re.compile(
    r"^(?:(https?|ftp|wss?):[/\\]*|[a-z][a-z0-9+.-]*://|[/\\]{2,})", re.I | re.ASCII
)
_SPECIAL_AUTHORITY_END = re.compile(r"[/\\?#]")
_AUTHORITY_END = re.compile(r"[/?#]")


def _redact_userinfo(url: str) -> str:
    # Normalize only to locate the userinfo; offsets keep the original spelling.
    normalized: list[str] = []
    offsets: list[int] = []
    for i, ch in enumerate(url):
        if ch in "\t\n\r" or (not normalized and ord(ch) <= 32):
            continue
        normalized.append(ch)
        offsets.append(i)
    text = "".join(normalized)
    authority = _AUTHORITY_START.match(text)
    if authority is None:
        return url
    start = len(authority[0])
    special = authority[1] is not None or ":" not in authority[0]
    rest = text[start:]
    end = (_SPECIAL_AUTHORITY_END if special else _AUTHORITY_END).search(rest)
    userinfo_end = (rest if end is None else rest[: end.start()]).rfind("@")
    if userinfo_end == -1:
        return url
    return url[: offsets[start]] + "REDACTED:REDACTED" + url[offsets[start + userinfo_end] :]


def _decode_query_key(key: str) -> str:
    if "%" not in key and "+" not in key:
        return key
    if _BAD_ESCAPE.search(key):
        return key

    try:
        return unquote(key.replace("+", " "), errors="strict")
    except UnicodeDecodeError:
        return key


def _redact_query(query: str, names: Sequence[Pattern]) -> str:
    def part(text: str) -> str:
        index = text.find("=")
        if index != -1 and is_redacted_name(_decode_query_key(text[:index]), names):
            return text[: index + 1] + "REDACTED"
        return text

    return "&".join(part(p) for p in query.split("&"))


def redact_url(url: str, redacted_names: Sequence[Pattern] | None = None) -> str:
    """``url`` with its userinfo replaced by ``REDACTED:REDACTED`` and the
    values of the redacted query parameters by ``REDACTED`` (by default
    those of the running fiber's ``CurrentRedactedNames``)."""
    names = current_redacted_names() if redacted_names is None else redacted_names
    if "@" in url:
        url = _redact_userinfo(url)
    query_start = url.find("?")
    if query_start == -1 or not names:
        return url
    hash_start = url.find("#")
    if hash_start != -1 and hash_start < query_start:
        return url
    query_end = len(url) if hash_start == -1 else hash_start
    return (
        url[: query_start + 1]
        + _redact_query(url[query_start + 1 : query_end], names)
        + url[query_end:]
    )


__all__ = [
    "EMPTY",
    "Coercible",
    "CoercibleRecord",
    "CurrentRedactedNames",
    "Input",
    "Param",
    "UrlParams",
    "Value",
    "current_redacted_names",
    "from_input",
    "is_redacted_name",
    "make",
    "parse",
    "redact_url",
    "to_string",
    "unwrap",
]
