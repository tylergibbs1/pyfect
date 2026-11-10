"""Schemas the GraphQL errors and results share: ``HEADERS``, a string record
decoded into ``Headers``."""

from __future__ import annotations

from typing import TypeIs

from pyfect import schema as S
from pyfect.http.headers import Headers, from_input
from pyfect.schema import transformation as T


def _is_headers(value: object) -> TypeIs[Headers]:
    return isinstance(value, Headers)


def _plain(headers: Headers) -> dict[str, str]:
    return dict(headers)


HEADERS = S.Record(S.String, S.String).pipe(
    S.decode_to(
        S.declare(_is_headers, expected="Headers"),
        T.transform(decode=from_input, encode=_plain),
    )
)
