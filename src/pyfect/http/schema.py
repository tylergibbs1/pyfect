"""Schemas of the HTTP values (Effect's ``Schema.Headers``, ``Cookie``,
``Cookies``, ``RecordFromCookies``, ``UrlParams``, ``JsonFromUrlParamsField``,
``RecordFromUrlParams``, ``RetryAfter``, ``RetryAfterFromString`` and
``DateTimeUtcFromHttpDate``). They live here, not in ``pyfect.schema``,
because ``pyfect.http`` is built on ``pyfect.schema``::

    from pyfect.http import schema as HS

    S.decode_unknown_sync(HS.RecordFromCookies)(cookies)  # {"session": "abc"}

``RetryAfter`` is a declaration of ``headers.RetryAfterDuration`` /
``RetryAfterDateTime`` (Effect's is a union of tagged structs of the same
shape): the duration must be finite and non-negative.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import TypeIs

from pyfect import redacted
from pyfect.exit import Exit, Success
from pyfect.exit import fail as fail_exit
from pyfect.http import cookies as _cookies
from pyfect.http import headers as _headers
from pyfect.http import url_params as _url_params
from pyfect.result import Ok, Result
from pyfect.schema import (
    Array,
    Bottom,
    DateTimeUtc,
    DecodeToSchema,
    NonEmptyArray,
    Record,
    String,
    Tuple,
    Union,
    Unknown,
    declare,
    decode_to,
    from_json_string,
    link,
)
from pyfect.schema import ast as _ast
from pyfect.schema import transformation as T
from pyfect.schema._options import ParseOptions
from pyfect.schema.issue import InvalidValue, Issue, MissingKey, Pointer, reported

type _CodecLink = Callable[[tuple[_ast.AST, ...]], _ast.Link]


def _codec(make: Callable[[], _ast.Link]) -> _CodecLink:
    return lambda _: make()


def _is_headers(value: object) -> TypeIs[_headers.Headers]:
    return isinstance(value, _headers.Headers)


def _headers_record(value: _headers.Headers) -> dict[str, str]:
    return dict(value)


Headers: Bottom[_headers.Headers] = declare(
    _is_headers,
    expected="Headers",
    representation={"id": "effect/http/Headers", "payload": None},
    to_codec=_codec(
        lambda: link(
            Record(String, String),
            T.transform(decode=_headers.from_input, encode=_headers_record),
        )
    ),
)
"""``pyfect.http.headers.Headers``, written as a ``{name: value}`` record."""


def _is_cookie(value: object) -> TypeIs[_cookies.Cookie]:
    return isinstance(value, _cookies.Cookie)


Cookie: Bottom[_cookies.Cookie] = declare(
    _is_cookie,
    expected="Cookie",
    representation={"id": "effect/http/Cookie", "payload": None},
)
"""A ``pyfect.http.cookies.Cookie``."""


def _is_cookies(value: object) -> TypeIs[_cookies.Cookies]:
    return isinstance(value, _cookies.Cookies)


def _set_cookies(value: Sequence[str]) -> _cookies.Cookies:
    return _cookies.from_set_cookie(value)


def _set_cookie_headers(value: _cookies.Cookies) -> Sequence[str]:
    return value.to_set_cookie_headers()


Cookies: Bottom[_cookies.Cookies] = declare(
    _is_cookies,
    expected="Cookies",
    representation={"id": "effect/http/Cookies", "payload": None},
    to_codec_json=_codec(
        lambda: link(Array(String), T.transform(decode=_set_cookies, encode=_set_cookie_headers))
    ),
)
"""``pyfect.http.cookies.Cookies``, written in JSON as its ``Set-Cookie``
headers."""


def _cookies_of(record: Mapping[str, str]) -> _cookies.Cookies:
    return _cookies.from_iterable(
        _cookies.make_cookie_unsafe(name, value) for name, value in record.items()
    )


def _cookie_values(value: _cookies.Cookies) -> dict[str, str]:
    return value.to_record()


RecordFromCookies: DecodeToSchema[dict[str, str], _cookies.Cookies] = Cookies.pipe(
    decode_to(Record(String, String), T.transform(decode=_cookie_values, encode=_cookies_of))
)
"""The cookies' values by name; encoding makes plain cookies."""


def _is_url_params(value: object) -> TypeIs[_url_params.UrlParams]:
    return isinstance(value, _url_params.UrlParams)


def _params_of(pairs: Sequence[tuple[str, str]]) -> _url_params.UrlParams:
    return _url_params.make(pairs)


def _pairs_of(params: _url_params.UrlParams) -> tuple[tuple[str, str], ...]:
    return tuple(
        (key, value if isinstance(value, str) else redacted.value(value)) for key, value in params
    )


UrlParams: Bottom[_url_params.UrlParams] = declare(
    _is_url_params,
    expected="UrlParams",
    representation={"id": "effect/http/UrlParams", "payload": None},
    to_codec=_codec(
        lambda: link(Array(Tuple(String, String)), T.transform(decode=_params_of, encode=_pairs_of))
    ),
)
"""``pyfect.http.url_params.UrlParams``, written as its ``(key, value)``
pairs (a redacted value as its text)."""


def _record_of(params: _url_params.UrlParams) -> dict[str, str | tuple[str, ...]]:
    return {
        key: value if isinstance(value, str) else tuple(value)
        for key, value in params.to_record().items()
    }


def _params_from_record(record: Mapping[str, str | Sequence[str]]) -> _url_params.UrlParams:
    return _url_params.from_input(record)


RecordFromUrlParams: DecodeToSchema[dict[str, str | tuple[str, ...]], _url_params.UrlParams] = (
    UrlParams.pipe(
        decode_to(
            Record(String, Union(String, NonEmptyArray(String))),
            T.transform(decode=_record_of, encode=_params_from_record),
        )
    )
)
"""The params by key: one value, or a tuple of a repeated key's values."""


def JsonFromUrlParamsField(field: str, /) -> DecodeToSchema[object, _url_params.UrlParams]:
    """The JSON text of the params' first ``field`` value, parsed (missing:
    a ``MissingKey`` at ``field``). Effect's ``reviver`` option is not
    ported, as for ``S.from_json_string``."""

    def decode(params: _url_params.UrlParams, _: ParseOptions) -> Exit[str, Issue]:
        value = params.get_first(field)
        if value is None:
            return fail_exit(Pointer((field,), MissingKey()))
        return Success(value)

    def encode(value: str, _: ParseOptions) -> Exit[_url_params.UrlParams, Issue]:
        return Success(_url_params.make([(field, value)]))

    json = from_json_string(Unknown)
    return UrlParams.pipe(decode_to(json, T.transform_effect(decode=decode, encode=encode)))


def _is_retry_after(value: object) -> TypeIs[_headers.RetryAfter]:
    if isinstance(value, _headers.RetryAfterDuration):
        return math.isfinite(value.duration) and value.duration >= 0
    return isinstance(value, _headers.RetryAfterDateTime)


RetryAfter: Bottom[_headers.RetryAfter] = declare(_is_retry_after, expected="RetryAfter")
"""A parsed ``Retry-After``: a finite, non-negative delay or a date."""


def _parsed[A](
    parse: Callable[[str], Result[A, object]], expected: str
) -> Callable[[str, ParseOptions], Exit[A, Issue]]:
    def run(text: str, options: ParseOptions) -> Exit[A, Issue]:
        result = parse(text)
        if isinstance(result, Ok):
            return Success(result.value)
        return fail_exit(InvalidValue({"expected": expected}, reported(text, options)))

    return run


def _done[A, B](f: Callable[[A], B]) -> Callable[[A, ParseOptions], Exit[B, Issue]]:
    return lambda value, _: Success(f(value))


RetryAfterFromString: DecodeToSchema[_headers.RetryAfter, str] = String.annotate(
    expected="a Retry-After header value"
).pipe(
    decode_to(
        RetryAfter,
        T.transform_effect(
            decode=_parsed(
                _headers.parse_retry_after,
                "whole non-negative seconds or an HTTP date (RFC 9110 §10.2.3)",
            ),
            encode=_done(_headers.format_retry_after),
        ),
    )
)
"""A ``Retry-After`` header value: whole seconds or an HTTP date."""

DateTimeUtcFromHttpDate: DecodeToSchema[datetime, str] = String.annotate(
    expected="an HTTP date string"
).pipe(
    decode_to(
        DateTimeUtc,
        T.transform_effect(
            decode=_parsed(_headers.parse_http_date, "an HTTP date string"),
            encode=_done(_headers.format_http_date),
        ),
    )
)
"""A UTC ``datetime`` from any HTTP date format (RFC 9110 §5.6.7),
written back as an IMF-fixdate."""

__all__ = [
    "Cookie",
    "Cookies",
    "DateTimeUtcFromHttpDate",
    "Headers",
    "JsonFromUrlParamsField",
    "RecordFromCookies",
    "RecordFromUrlParams",
    "RetryAfter",
    "RetryAfterFromString",
    "UrlParams",
]
