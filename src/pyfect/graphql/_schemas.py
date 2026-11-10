"""Schemas the GraphQL errors and results share: ``HEADERS`` (a string
record decoded into ``Headers``) and ``SECONDS_FROM_MILLIS`` (Effect's
``Schema.DurationFromMillis`` over ``Seconds``)."""

from __future__ import annotations

from typing import TypeIs

from pyfect import schema as S
from pyfect.duration import Duration, to_millis
from pyfect.http.headers import Headers, from_input
from pyfect.schema import transformation as T


def _is_seconds(value: object) -> TypeIs[Duration]:
    return isinstance(value, Duration)


def _is_headers(value: object) -> TypeIs[Headers]:
    return isinstance(value, Headers)


def _plain(headers: Headers) -> dict[str, str]:
    return dict(headers)


SECONDS_FROM_MILLIS = S.Finite.pipe(
    S.decode_to(
        S.declare(_is_seconds, expected="Seconds"),
        T.transform(decode=lambda millis: Duration(millis / 1000), encode=to_millis),
    )
)

HEADERS = S.Record(S.String, S.String).pipe(
    S.decode_to(
        S.declare(_is_headers, expected="Headers"),
        T.transform(decode=from_input, encode=_plain),
    )
)
